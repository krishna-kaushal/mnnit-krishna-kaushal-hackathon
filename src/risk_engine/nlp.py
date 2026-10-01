"""NLP components for the risk engine.

Backends are resolved lazily inside try/except so importing this module
never requires torch/transformers (and never triggers a model download):

  SentimentAnalyzer : "finbert" -> "vader_finance" -> "keyword"
  EventClassifier   : "bart_mnli" -> "keyword_rules"

Set SENTIMENT_BACKEND / EVENT_BACKEND env vars to force a choice for
debugging; unknown values fall back to "auto".
"""

import os
import re

# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------

# Small built-in finance keyword lexicon (last-resort backend).
_POSITIVE_WORDS = {
    "surge", "surging", "rally", "beat", "beats", "record", "profit", "profits",
    "growth", "upgrade", "upgraded", "bullish", "outperform", "gain", "gains",
    "soar", "soaring", "jump", "jumps", "strong", "optimistic", "buyback",
    "expansion", "breakthrough", "rebound", "boom", "outperforming",
}
_NEGATIVE_WORDS = {
    "plunge", "plunging", "slump", "miss", "misses", "loss", "losses",
    "downgrade", "downgraded", "bearish", "crash", "cut", "cuts", "layoff",
    "layoffs", "lawsuit", "fraud", "default", "bankrupt", "bankruptcy",
    "weak", "pessimistic", "selloff", "tumble", "tumbling", "drop", "fall",
    "falling", "decline", "fear", "fears", "warning", "crisis",
}

# Finance-specific valence tweaks applied on top of VADER's general lexicon
# (single tokens only; VADER matches lowercased tokens). Values follow
# VADER's -4..+4 scale.
FINANCE_LEXICON_TWEAK = {
    # positive
    "beat": 2.5, "beats": 2.5, "surge": 2.5, "surging": 2.5, "rally": 2.0,
    "rallying": 2.0, "record": 1.5, "soar": 2.5, "soaring": 2.5, "jump": 1.5,
    "jumps": 1.5, "upgrade": 2.0, "upgraded": 2.0, "bullish": 2.5,
    "outperform": 2.0, "outperforming": 2.0, "buyback": 1.5, "rebound": 1.8,
    "breakthrough": 2.0, "boom": 2.0, "strong": 1.8, "growth": 1.5,
    # negative
    "miss": -2.5, "misses": -2.5, "plunge": -2.8, "plunging": -2.8,
    "slump": -2.2, "downgrade": -2.2, "downgraded": -2.2, "bearish": -2.5,
    "crash": -3.0, "layoff": -2.0, "layoffs": -2.0, "lawsuit": -2.0,
    "fraud": -3.0, "default": -2.8, "bankruptcy": -3.0, "bankrupt": -3.0,
    "selloff": -2.5, "tumble": -2.3, "tumbling": -2.3, "recession": -2.0,
    "warning": -1.8, "crisis": -2.8, "probe": -1.5,
    # common inflections
    "downgrades": -2.2, "surges": 2.5, "plunges": -2.8, "rallies": 2.0,
    "soars": 2.5, "tumbles": -2.3, "upgrades": 2.0, "crashes": -3.0,
    "slumps": -2.2,
}

_WORD_RE = re.compile(r"[a-z]+")


class SentimentAnalyzer:
    """Polarity scorer returning a float in [-1, 1].

    Backend priority ("auto"):
      1. "finbert"        HuggingFace ProsusAI/finbert, local_files_only=True
                          (never downloads; used only if cached locally).
                          score = P(positive) - P(negative).
      2. "vader_finance"  vaderSentiment compound score.
      3. "keyword"        built-in finance lexicon:
                          (pos - neg) / (pos + neg), 0.0 when no hits.

    Attributes:
        backend_used: one of "finbert" | "vader_finance" | "keyword".
    """

    FINBERT_MODEL = "ProsusAI/finbert"

    def __init__(self, backend="auto"):
        self.backend_used = None
        self._fn = None
        choice = (backend or "auto").lower()
        if choice in ("auto", "finbert"):
            self._fn = self._try_finbert()
            if self._fn is not None:
                self.backend_used = "finbert"
        if self._fn is None and choice in ("auto", "vader_finance", "vader"):
            self._fn = self._try_vader()
            if self._fn is not None:
                self.backend_used = "vader_finance"
        if self._fn is None:
            self._fn = self._keyword_score
            self.backend_used = "keyword"

    # -- backends ------------------------------------------------------
    def _try_finbert(self):
        """Load ProsusAI/finbert from the local HF cache only."""
        try:
            from transformers import (
                AutoModelForSequenceClassification,
                AutoTokenizer,
                pipeline as hf_pipeline,
            )
        except Exception:
            return None  # transformers/torch not installed
        try:
            tokenizer = AutoTokenizer.from_pretrained(
                self.FINBERT_MODEL, local_files_only=True, trust_remote_code=False
            )
            model = AutoModelForSequenceClassification.from_pretrained(
                self.FINBERT_MODEL, local_files_only=True, trust_remote_code=False
            )
            clf = hf_pipeline(
                "text-classification",
                model=model,
                tokenizer=tokenizer,
                top_k=None,
                truncation=True,
                max_length=512,
            )
        except Exception:
            return None  # not cached locally (or load failed) -> no download

        def score(text):
            if not text or not text.strip():
                return 0.0
            probs = {d["label"].lower(): d["score"] for d in clf(text[:2000])}
            return float(probs.get("positive", 0.0) - probs.get("negative", 0.0))

        return score

    def _try_vader(self):
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        except Exception:
            return None
        analyzer = SentimentIntensityAnalyzer()
        # Finance-tune VADER: boost/penalize market vocabulary that the
        # general lexicon scores weakly or gets wrong.
        analyzer.lexicon.update(FINANCE_LEXICON_TWEAK)

        def score(text):
            if not text or not text.strip():
                return 0.0
            return float(analyzer.polarity_scores(text)["compound"])

        return score

    def _keyword_score(self, text):
        words = _WORD_RE.findall((text or "").lower())
        pos = sum(1 for w in words if w in _POSITIVE_WORDS)
        neg = sum(1 for w in words if w in _NEGATIVE_WORDS)
        if pos == 0 and neg == 0:
            return 0.0
        return (pos - neg) / (pos + neg)

    # -- public API ----------------------------------------------------
    def analyze(self, text):
        """Return sentiment polarity in [-1, 1] (negative -> bearish)."""
        score = self._fn(text)
        return max(-1.0, min(1.0, float(score)))


# ---------------------------------------------------------------------------
# Event classification
# ---------------------------------------------------------------------------

EVENT_LABELS = [
    "Geopolitical",
    "Macroeconomic",
    "Credit Event",
    "Merger/Acquisition",
    "Product Launch",
]

# Deterministic keyword sets for the "keyword_rules" fallback. Kept
# deliberately narrow (finance/news vocabulary) to avoid false positives.
KEYWORD_RULES = {
    "Geopolitical": [
        "sanction", "tariff", "trade war", "embargo", "geopolitical", "export ban",
        "import ban", "retaliat", "invasion", "military", "war ", "conflict",
        "blockade", "ceasefire",
    ],
    "Macroeconomic": [
        "inflation", "interest rate", "rate hike", "rate cut", "federal reserve",
        "fed ", "recession", "gdp", "unemployment", "cpi", "payrolls",
        "monetary policy", "central bank", "treasury yield", "bond yield",
        "macroeconomic",
    ],
    "Credit Event": [
        "default", "downgrade", "bankrupt", "credit rating", "missed payment",
        "restructuring", "liquidity", "insolven", "junk bond", "spread",
        "credit event", "debt",
    ],
    "Merger/Acquisition": [
        "acquisition", "acquire", "acquiring", "merger", "takeover", "buyout",
        "bid for", "stake", "divestiture", "spin-off", "spinoff", "takeover",
    ],
    "Product Launch": [
        "launch", "unveil", "new product", "introduces",
        "debut", "rollout", "next-gen", "preorder",
    ],
}


class EventClassifier:
    """Assign one of EVENT_LABELS to a text.

    Backend priority ("auto"):
      1. "bart_mnli"      facebook/bart-large-mnli zero-shot, loaded with
                          local_files_only=True (never downloads).
      2. "keyword_rules"  deterministic: count keyword hits per label, pick
                          the max; ties break by EVENT_LABELS order; texts
                          with no hits default to "Macroeconomic".

    Attributes:
        backend_used: "bart_mnli" | "keyword_rules".
    """

    ZERO_SHOT_MODEL = "facebook/bart-large-mnli"

    def __init__(self, backend="auto", labels=None):
        self.labels = list(labels or EVENT_LABELS)
        self.backend_used = None
        self._fn = None
        choice = (backend or "auto").lower()
        if choice in ("auto", "bart_mnli", "bart"):
            self._fn = self._try_zero_shot()
            if self._fn is not None:
                self.backend_used = "bart_mnli"
        if self._fn is None:
            self._fn = self._keyword_classify
            self.backend_used = "keyword_rules"

    def _try_zero_shot(self):
        try:
            from transformers import pipeline as hf_pipeline
        except Exception:
            return None
        try:
            clf = hf_pipeline(
                "zero-shot-classification",
                model=self.ZERO_SHOT_MODEL,
                local_files_only=True,
                trust_remote_code=False,
            )
        except Exception:
            return None  # not cached locally -> no download

        def classify(text):
            if not text or not text.strip():
                return "Macroeconomic"
            out = clf(text[:2000], self.labels, multi_label=False)
            return out["labels"][0]

        return classify

    def _keyword_classify(self, text):
        lowered = f" {(text or '').lower()} "
        scores = {}
        for label in self.labels:
            hits = sum(
                1 for kw in KEYWORD_RULES.get(label, []) if kw.lower() in lowered
            )
            scores[label] = hits
        best = max(self.labels, key=lambda lb: scores[lb])
        return best if scores[best] > 0 else "Macroeconomic"

    def classify(self, text):
        """Return the single best event label for `text`."""
        label = self._fn(text)
        return label if label in self.labels else "Macroeconomic"


# ---------------------------------------------------------------------------
# Impact scoring
# ---------------------------------------------------------------------------

# Per-event severity weights used by impact_score().
SEVERITY_WEIGHTS = {
    "Geopolitical": 2.5,
    "Macroeconomic": 2.0,
    "Credit Event": 3.0,
    "Merger/Acquisition": 1.0,
    "Product Launch": 0.5,
}


def impact_score(sentiment, event_class, corroboration_count):
    """Map (sentiment, event class, corroboration) to an impact of 1..10.

    Formula (documented for the jury):

        sentiment_term     = 5.0 * abs(sentiment)          # in [0, 5]
        severity_term      = SEVERITY_WEIGHTS[event_class] # 0.5 .. 3.0
        corroboration_term = min(1.5, 0.5 * (n_sources - 1))
                             # 0.0 for a single source, +0.5 per extra
                             # distinct source, capped at 1.5
        raw                = 2.0 + sentiment_term + severity_term
                                   + corroboration_term
        impact             = clamp(round(raw), 1, 10)

    Intuition: strong directional sentiment, severe event types (credit
    events, geopolitics), and multi-source corroboration all raise impact;
    the 2.0 base keeps mildly negative single-source chatter low.

    Args:
        sentiment: float in [-1, 1].
        event_class: one of EVENT_LABELS.
        corroboration_count: number of DISTINCT sources mentioning the same
            ticker + event_class (1 = seen in a single source only).

    Returns:
        (impact: int, breakdown: dict) where breakdown has
        {"sentiment_term", "severity_term", "corroboration_term"}.
    """
    sentiment_term = 5.0 * abs(float(sentiment))
    severity_term = float(SEVERITY_WEIGHTS.get(event_class, 1.0))
    n = max(1, int(corroboration_count or 1))
    corroboration_term = min(1.5, 0.5 * (n - 1))
    raw = 2.0 + sentiment_term + severity_term + corroboration_term
    impact = int(round(max(1.0, min(10.0, raw))))
    breakdown = {
        "sentiment_term": round(sentiment_term, 3),
        "severity_term": round(severity_term, 3),
        "corroboration_term": round(corroboration_term, 3),
    }
    return impact, breakdown
