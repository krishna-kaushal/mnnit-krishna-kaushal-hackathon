"""End-to-end risk signal pipeline.

Orchestration:
  1. fetch items from each requested source (live sources degrade
     gracefully: a failed source logs a warning and the pipeline falls
     back to bundled synthetic data),
  2. run entity extraction + sentiment + event classification on each item,
  3. compute corroboration = number of DISTINCT sources mentioning the same
     (ticker, event_class) pair within this run,
  4. score impact and append deduplicated signals to data/signals.jsonl.

Runnable:
    PYTHONPATH=src python -m risk_engine.pipeline --sources synthetic_social --limit 40

All repo-relative paths are resolved from the repository root
(Path(__file__).resolve().parents[2]), so the CLI works from any cwd.
"""

import argparse
import hashlib
import json
import os
import warnings
from datetime import datetime, timezone
from pathlib import Path

from risk_engine.entity_map import extract_entities
from risk_engine.ingest import (
    IngestError,
    build_gdelt_query,
    fetch_gdelt,
    fetch_newsapi,
    load_news_jsonl,
    load_social_csv,
)
from risk_engine.nlp import EventClassifier, SentimentAnalyzer, impact_score

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
SAMPLE_TWEETS = DATA_DIR / "sample_tweets.csv"
SAMPLE_NEWS = DATA_DIR / "sample_news.jsonl"
DEFAULT_SIGNALS_PATH = DATA_DIR / "signals.jsonl"

SOURCE_CHOICES = ("gdelt", "newsapi", "synthetic_social", "synthetic_news")


def _signal_id(source, url, title):
    """Stable 12-char id = sha1(source + url + title)."""
    raw = f"{source}|{url}|{title}".encode("utf-8", errors="replace")
    return hashlib.sha1(raw).hexdigest()[:12]


def score_items(items, analyzer, classifier):
    """Attach NLP annotations + impact to normalized ingest items.

    Corroboration is computed batch-wide: for each (ticker, event_class)
    pair we count the distinct sources that mention it; a signal's
    corroboration_count is the max over its tickers (1 when no ticker was
    extracted).

    Returns a list of signal dicts matching the signals.jsonl schema.
    """
    annotated = []
    for item in items:
        blob = f"{item.get('title', '')} {item.get('text', '')}"
        entities = extract_entities(blob)
        text = item.get("text") or item.get("title") or ""
        annotated.append(
            {
                "item": item,
                "tickers": entities["tickers"],
                "sectors": entities["sectors"],
                "sentiment": analyzer.analyze(text),
                "event_class": classifier.classify(text),
            }
        )

    # Batch-wide corroboration groups: (ticker, event) -> {sources}.
    corroboration_groups = {}
    for entry in annotated:
        for ticker in entry["tickers"]:
            key = (ticker, entry["event_class"])
            corroboration_groups.setdefault(key, set()).add(
                entry["item"].get("source", "unknown")
            )

    signals = []
    for entry in annotated:
        item = entry["item"]
        if entry["tickers"]:
            corroboration_count = max(
                len(corroboration_groups[(t, entry["event_class"])])
                for t in entry["tickers"]
            )
        else:
            corroboration_count = 1
        impact, breakdown = impact_score(
            entry["sentiment"], entry["event_class"], corroboration_count
        )
        signals.append(
            {
                "id": _signal_id(
                    item.get("source", ""), item.get("url", ""), item.get("title", "")
                ),
                "timestamp": item.get("timestamp")
                or datetime.now(timezone.utc).isoformat(),
                "source": item.get("source", "unknown"),
                "title": item.get("title", ""),
                "text": item.get("text", ""),
                "url": item.get("url", ""),
                "tickers": entry["tickers"],
                "sectors": entry["sectors"],
                "sentiment": round(float(entry["sentiment"]), 4),
                "sentiment_model": analyzer.backend_used,
                "event_class": entry["event_class"],
                "event_model": classifier.backend_used,
                "impact": impact,
                "impact_breakdown": breakdown,
            }
        )
    return signals


def run_pipeline(sources=("gdelt", "newsapi", "synthetic_social"), limit=40, query=None):
    """Fetch, annotate, score, and persist risk signals.

    Args:
        sources: iterable of source names (see SOURCE_CHOICES).
        limit:   total number of items processed (cap after aggregation).
        query:   optional custom query for live sources; GDELT defaults to
                 an OR-query built from the company universe.

    Returns:
        list of signal dicts that were newly appended.
    """
    sources = [s.strip() for s in sources]
    items = []

    if "gdelt" in sources:
        try:
            items.extend(fetch_gdelt(query or build_gdelt_query(), limit=limit))
        except IngestError as exc:
            warnings.warn(f"GDELT unavailable ({exc}); falling back to synthetic_news.")
            try:
                items.extend(load_news_jsonl(SAMPLE_NEWS))
            except IngestError as fallback_exc:
                warnings.warn(f"synthetic_news fallback failed: {fallback_exc}")

    if "newsapi" in sources:
        api_key = os.environ.get("NEWSAPI_KEY")
        try:
            items.extend(
                fetch_newsapi(api_key, query or "stock market finance", limit=limit)
            )
        except IngestError as exc:
            warnings.warn(f"NewsAPI skipped: {exc}")

    if "synthetic_social" in sources:
        try:
            items.extend(load_social_csv(SAMPLE_TWEETS))
        except IngestError as exc:
            warnings.warn(f"synthetic_social unavailable: {exc}")

    if "synthetic_news" in sources:
        try:
            items.extend(load_news_jsonl(SAMPLE_NEWS))
        except IngestError as exc:
            warnings.warn(f"synthetic_news unavailable: {exc}")

    items = items[: max(0, limit)]
    if not items:
        warnings.warn("pipeline produced no items; nothing to score.")
        return []

    analyzer = SentimentAnalyzer(backend=os.environ.get("SENTIMENT_BACKEND", "auto"))
    classifier = EventClassifier(backend=os.environ.get("EVENT_BACKEND", "auto"))
    signals = score_items(items, analyzer, classifier)
    n_new = save_signals(signals)

    print(
        f"[pipeline] items={len(items)} signals={len(signals)} "
        f"new={n_new} sentiment_backend={analyzer.backend_used} "
        f"event_backend={classifier.backend_used}"
    )
    return signals


def save_signals(signals, path="data/signals.jsonl"):
    """Append signals to a JSONL file, deduplicating by signal id.

    Args:
        signals: list of signal dicts.
        path:    repo-relative (from repo root) or absolute path.

    Returns:
        number of signals actually appended.
    """
    out_path = Path(path)
    if not out_path.is_absolute():
        out_path = REPO_ROOT / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    existing_ids = set()
    if out_path.exists():
        with out_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    existing_ids.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    continue

    appended = 0
    seen_in_batch = set()
    with out_path.open("a", encoding="utf-8") as fh:
        for signal in signals:
            sid = signal.get("id")
            if sid in existing_ids or sid in seen_in_batch:
                continue
            seen_in_batch.add(sid)
            fh.write(json.dumps(signal, ensure_ascii=False) + "\n")
            appended += 1
    return appended


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the NLP risk-signal pipeline."
    )
    parser.add_argument(
        "--sources",
        default=",".join(("gdelt", "newsapi", "synthetic_social")),
        help=f"comma-separated sources from {list(SOURCE_CHOICES)}",
    )
    parser.add_argument("--limit", type=int, default=40, help="max items to process")
    parser.add_argument(
        "--query", default=None, help="custom query for live sources (optional)"
    )
    args = parser.parse_args(argv)

    sources = [s for s in (p.strip() for p in args.sources.split(",")) if s]
    unknown = [s for s in sources if s not in SOURCE_CHOICES]
    if unknown:
        raise SystemExit(f"unknown sources: {unknown} (choose from {SOURCE_CHOICES})")

    run_pipeline(sources=sources, limit=args.limit, query=args.query)


if __name__ == "__main__":
    main()
