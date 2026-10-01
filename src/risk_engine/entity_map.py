"""Company <-> ticker/sector mapping and case-insensitive entity extraction.

Coverage: 15 large-cap companies used as the entity universe for the
risk engine. Text mentions are resolved to tickers, tickers to GICS-style
sectors. Matching is deliberately simple (regex word boundaries) so the
behaviour is transparent and reproducible for the jury.
"""

import re

# Canonical company name -> ticker. Extra aliases (e.g. "Google") are kept
# here so extract_entities() treats them as the same entity.
COMPANY_TO_TICKER = {
    "Apple": "AAPL",
    "Microsoft": "MSFT",
    "Nvidia": "NVDA",
    "Amazon": "AMZN",
    "Meta Platforms": "META",
    "Alphabet": "GOOGL",
    "Google": "GOOGL",  # alias of Alphabet
    "Broadcom": "AVGO",
    "Tesla": "TSLA",
    "JPMorgan": "JPM",
    "Visa": "V",
    "Exxon Mobil": "XOM",
    "UnitedHealth": "UNH",
    "Mastercard": "MA",
    "Procter & Gamble": "PG",
    "Home Depot": "HD",
}

TICKER_TO_SECTOR = {
    "AAPL": "Technology",
    "MSFT": "Technology",
    "NVDA": "Technology",
    "AMZN": "Consumer Discretionary",
    "META": "Technology",
    "GOOGL": "Technology",
    "AVGO": "Technology",
    "TSLA": "Consumer Discretionary",
    "JPM": "Financials",
    "V": "Financials",
    "XOM": "Energy",
    "UNH": "Healthcare",
    "MA": "Financials",
    "PG": "Consumer Staples",
    "HD": "Consumer Discretionary",
}


def extract_entities(text):
    """Extract tickers and sectors mentioned in free text.

    Case-insensitive whole-word match against COMPANY_TO_TICKER names
    (aliases included). Returns tickers ordered by first appearance,
    sectors in matching order, both deduplicated.

    Args:
        text: headline/body text (str or None).

    Returns:
        {"tickers": [...], "sectors": [...]}
    """
    if not text:
        return {"tickers": [], "sectors": []}

    hits = []  # (first_match_pos, ticker)
    for name, ticker in COMPANY_TO_TICKER.items():
        match = re.search(r"\b" + re.escape(name) + r"\b", text, re.IGNORECASE)
        if match:
            hits.append((match.start(), ticker))

    hits.sort(key=lambda h: h[0])
    tickers = list(dict.fromkeys(ticker for _, ticker in hits))
    sectors = list(dict.fromkeys(TICKER_TO_SECTOR[t] for t in tickers))
    return {"tickers": tickers, "sectors": sectors}
