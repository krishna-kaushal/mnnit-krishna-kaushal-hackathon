"""REST API for the NLP risk engine.

Run:
    PYTHONPATH=src uvicorn api.main:app --port 8000

Endpoints:
    GET  /health            service status + signal count
    GET  /signals           list signals, newest first
    GET  /signals/latest    most recent signal
    POST /analyze           run the NLP pipeline on ad-hoc text
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dateutil import parser as date_parser
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from risk_engine.nlp import EVENT_LABELS, EventClassifier, SentimentAnalyzer
from risk_engine.pipeline import REPO_ROOT, save_signals, score_items

SIGNALS_PATH = REPO_ROOT / "data" / "signals.jsonl"

app = FastAPI(title="Risk Engine API", version="1.0.0")

_analyzer = None
_classifier = None


def get_analyzer():
    global _analyzer
    if _analyzer is None:
        _analyzer = SentimentAnalyzer(
            backend=os.environ.get("SENTIMENT_BACKEND", "auto")
        )
    return _analyzer


def get_classifier():
    global _classifier
    if _classifier is None:
        _classifier = EventClassifier(backend=os.environ.get("EVENT_BACKEND", "auto"))
    return _classifier


def _read_signals():
    """Read all signals from signals.jsonl (tolerates missing/bad lines)."""
    signals = []
    if SIGNALS_PATH.exists():
        with SIGNALS_PATH.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    signals.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return signals


def _sort_key(signal):
    try:
        return date_parser.parse(signal.get("timestamp", ""))
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "risk-engine-api",
        "signals": len(_read_signals()),
        "sentiment_backend": get_analyzer().backend_used,
        "event_backend": get_classifier().backend_used,
    }


@app.get("/signals")
def list_signals(
    limit: int = Query(100, ge=1, le=1000),
    event_class: str | None = Query(
        None, description=f"filter by event class, one of {EVENT_LABELS}"
    ),
    min_impact: int | None = Query(None, ge=1, le=10, description="min impact 1..10"),
):
    signals = _read_signals()
    if event_class is not None:
        signals = [s for s in signals if s.get("event_class") == event_class]
    if min_impact is not None:
        signals = [s for s in signals if (s.get("impact") or 0) >= min_impact]
    signals.sort(key=_sort_key, reverse=True)
    return {"count": len(signals), "signals": signals[:limit]}


@app.get("/signals/latest")
def latest_signal():
    signals = _read_signals()
    if not signals:
        raise HTTPException(status_code=404, detail="no signals recorded yet")
    signals.sort(key=_sort_key, reverse=True)
    return signals[0]


class AnalyzeRequest(BaseModel):
    text: str = Field(..., min_length=1, description="text to analyze")
    title: str | None = Field(None, description="optional headline")
    persist: bool = Field(False, description="append the signal to signals.jsonl")


@app.post("/analyze")
def analyze_text(req: AnalyzeRequest):
    """Run the NLP pipeline on ad-hoc text and return the signal.

    Corroboration is 1 (single ad-hoc input); impact follows the same
    documented formula as the batch pipeline.
    """
    title = req.title or (req.text if len(req.text) <= 80 else req.text[:77] + "...")
    item = {
        "source": "api",
        "title": title,
        "text": req.text,
        "url": "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    signal = score_items([item], get_analyzer(), get_classifier())[0]
    if req.persist:
        save_signals([signal])
    return signal
