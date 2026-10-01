"""Risk Engine: NLP-powered market risk signal extraction.

Modules:
    entity_map  company <-> ticker/sector mapping + entity extraction
    ingest      source fetchers (GDELT, NewsAPI, synthetic fallbacks)
    nlp         sentiment analysis, event classification, impact scoring
    pipeline    end-to-end orchestration + CLI
"""

__all__ = ["entity_map", "ingest", "nlp", "pipeline"]
