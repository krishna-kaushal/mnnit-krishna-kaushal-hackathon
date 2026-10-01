"""News/social source fetchers for the risk engine.

All fetchers return normalized items with the shape::

    {
        "source":    "gdelt" | "newsapi" | "synthetic_social" | "synthetic_news",
        "title":     str,
        "text":      str,
        "url":       str,
        "timestamp": ISO8601 string (UTC where possible),
    }

Design rules:
  * Live network fetchers NEVER crash the caller on network failure: they
    raise IngestError, which the pipeline catches and converts into a
    warning + fallback.
  * Synthetic sources are clearly labelled via the `source` field (and a
    `data_origin="synthetic"` column in the CSV) so they can never be
    mistaken for live data downstream.
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
from dateutil import parser as date_parser

from risk_engine.entity_map import COMPANY_TO_TICKER

GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
NEWSAPI_URL = "https://newsapi.org/v2/everything"
REQUEST_TIMEOUT = 20


class IngestError(Exception):
    """Raised when a source cannot be fetched. Callers catch and fall back."""


def build_gdelt_query(companies=None):
    """Build a GDELT Doc API OR-query from company display names.

    e.g. "(Apple OR Microsoft OR Nvidia)".

    Args:
        companies: iterable of names; defaults to every canonical company
            in COMPANY_TO_TICKER (aliases excluded to avoid double counting).
    """
    if companies is None:
        seen = set()
        companies = []
        for name, ticker in COMPANY_TO_TICKER.items():
            if ticker not in seen:  # drop aliases like "Google"
                seen.add(ticker)
                companies.append(name)
    return "(" + " OR ".join(companies) + ")"


def _norm_timestamp(value):
    """Best-effort normalization to ISO8601; falls back to now (UTC)."""
    if value:
        try:
            dt = date_parser.parse(str(value))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except (ValueError, TypeError, OverflowError):
            pass
    return datetime.now(timezone.utc).isoformat()


def fetch_gdelt(query, limit=40, hours=24):
    """Fetch recent articles from the GDELT 2.1 Document API.

    Args:
        query:  GDELT query string (see build_gdelt_query).
        limit:  max articles to return.
        hours:  lookback window.

    Raises:
        IngestError: on any network/HTTP/parse failure.
    """
    params = {
        "query": query,
        "mode": "artlist",
        "format": "json",
        "maxrecords": limit,
        "timespan": f"{hours}h",
        "sortby": "datedesc",
    }
    try:
        resp = requests.get(GDELT_DOC_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        raise IngestError(f"GDELT request failed: {exc}") from exc
    except ValueError as exc:  # bad JSON
        raise IngestError(f"GDELT returned invalid JSON: {exc}") from exc

    items = []
    for art in payload.get("articles", []) or []:
        title = art.get("title") or ""
        # The artlist mode returns metadata, not body text; the title is the
        # only reliable text signal, so it doubles as `text`.
        items.append(
            {
                "source": "gdelt",
                "title": title,
                "text": title,
                "url": art.get("url") or "",
                "timestamp": _norm_timestamp(art.get("seendate")),
            }
        )
        if len(items) >= limit:
            break
    return items


def fetch_newsapi(api_key, query, limit=40):
    """Fetch recent articles from NewsAPI (https://newsapi.org/v2/everything).

    Raises:
        IngestError: if `api_key` is falsy or the request fails.
    """
    if not api_key:
        raise IngestError(
            "NEWSAPI_KEY is not set: export NEWSAPI_KEY=<key> to enable NewsAPI; "
            "skipping this source."
        )
    params = {
        "q": query,
        "pageSize": min(limit, 100),
        "sortBy": "publishedAt",
        "language": "en",
        "apiKey": api_key,
    }
    try:
        resp = requests.get(NEWSAPI_URL, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        raise IngestError(f"NewsAPI request failed: {exc}") from exc
    except ValueError as exc:
        raise IngestError(f"NewsAPI returned invalid JSON: {exc}") from exc

    if payload.get("status") != "ok":
        raise IngestError(f"NewsAPI error: {payload.get('message', 'unknown')}")

    items = []
    for art in payload.get("articles", []) or []:
        title = art.get("title") or ""
        text = art.get("description") or art.get("content") or title
        items.append(
            {
                "source": "newsapi",
                "title": title,
                "text": text,
                "url": art.get("url") or "",
                "timestamp": _norm_timestamp(art.get("publishedAt")),
            }
        )
        if len(items) >= limit:
            break
    return items


def load_social_csv(path):
    """Load the synthetic social CSV (data/sample_tweets.csv).

    Expected columns: id, timestamp, text, ticker, event_hint, data_origin
    (every row must carry data_origin="synthetic").

    Raises:
        IngestError: if the file is missing or malformed.
    """
    path = Path(path)
    try:
        df = pd.read_csv(path, dtype=str).fillna("")
    except FileNotFoundError as exc:
        raise IngestError(f"social CSV not found: {path}") from exc
    except Exception as exc:
        raise IngestError(f"could not parse social CSV {path}: {exc}") from exc

    required = {"id", "timestamp", "text"}
    missing = required - set(df.columns)
    if missing:
        raise IngestError(f"social CSV {path} missing columns: {sorted(missing)}")

    items = []
    for _, row in df.iterrows():
        text = str(row["text"]).strip()
        if not text:
            continue
        title = text if len(text) <= 80 else text[:77] + "..."
        items.append(
            {
                "source": "synthetic_social",
                "title": title,
                "text": text,
                "url": f"synthetic://social/{row['id']}",
                "timestamp": _norm_timestamp(row["timestamp"]),
            }
        )
    return items


def load_news_jsonl(path):
    """Load the synthetic offline news fallback (data/sample_news.jsonl).

    Each line: {"source": "synthetic_news", "title", "text", "url",
    "timestamp", "ticker_hint"}.

    Raises:
        IngestError: if the file is missing or malformed.
    """
    path = Path(path)
    items = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError as exc:
                    warnings.warn(f"skipping bad JSONL line {lineno} in {path}: {exc}")
                    continue
                items.append(
                    {
                        "source": "synthetic_news",
                        "title": obj.get("title") or "",
                        "text": obj.get("text") or obj.get("title") or "",
                        "url": obj.get("url") or f"synthetic://news/{lineno}",
                        "timestamp": _norm_timestamp(obj.get("timestamp")),
                    }
                )
    except FileNotFoundError as exc:
        raise IngestError(f"news JSONL not found: {path}") from exc
    if not items:
        raise IngestError(f"news JSONL {path} contained no usable items")
    return items
