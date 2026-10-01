"""Synthetic portfolio generator for Module B.

Generates a small (~30 row), fully synthetic portfolio CSV so the stress
test can be demonstrated without any real client holdings.

Every row is labelled ``data_origin="synthetic"``. The generator is
deterministic (seed 42) so the same file is produced on every run —
important for a reproducible jury demo.

Portfolio mix (30 rows):
    * 10 floating-rate loans        — sensitive to rates + credit spreads
    * 12 fixed-coupon bonds         — sensitive to rates + credit spreads
    *  4 equity futures (long)      — sensitive to equity moves (delta=1)
    *  4 interest-rate swaps        — receive-fixed, sensitive to rates

Notionals are in USD millions, drawn realistically between 10 and 200.
"""

import csv

import numpy as np

SEED = 42
N_ROWS = 30

SECTORS = ["Technology", "Energy", "Financials", "Healthcare", "Industrials", "Consumer"]
RATINGS = ["AAA", "AA", "A", "BBB", "BB", "B", "CCC"]

COLUMNS = [
    "id",
    "type",
    "notional",
    "sector",
    "maturity_yrs",
    "rating",
    "coupon_pct",
    "derivative_subtype",
    "delta",
    "duration_yrs",
    "data_origin",
]


def _loan(rng, i):
    maturity = round(float(rng.uniform(2, 7)), 1)
    return {
        "id": f"L{i:02d}",
        "type": "loan",
        "notional": round(float(rng.uniform(10, 200)), 1),
        "sector": str(rng.choice(SECTORS)),
        "maturity_yrs": maturity,
        "rating": str(rng.choice(RATINGS, p=[0.05, 0.15, 0.25, 0.25, 0.15, 0.10, 0.05])),
        "coupon_pct": round(float(rng.uniform(4.0, 10.0)), 2),  # floating spread level
        "derivative_subtype": "",
        "delta": "",
        # Simplified: duration ~ maturity (real floating-rate loans would
        # have much shorter duration; noted in shocks.py).
        "duration_yrs": maturity,
        "data_origin": "synthetic",
    }


def _bond(rng, i):
    maturity = round(float(rng.uniform(1, 15)), 1)
    return {
        "id": f"B{i:02d}",
        "type": "bond",
        "notional": round(float(rng.uniform(10, 200)), 1),
        "sector": str(rng.choice(SECTORS)),
        "maturity_yrs": maturity,
        "rating": str(rng.choice(RATINGS, p=[0.05, 0.15, 0.25, 0.25, 0.15, 0.10, 0.05])),
        "coupon_pct": round(float(rng.uniform(2.0, 8.0)), 2),
        "derivative_subtype": "",
        "delta": "",
        "duration_yrs": maturity,
        "data_origin": "synthetic",
    }


def _equity_future(rng, i):
    return {
        "id": f"D-EQ{i:02d}",
        "type": "derivative",
        "notional": round(float(rng.uniform(10, 120)), 1),
        "sector": str(rng.choice(SECTORS)),
        "maturity_yrs": 0.25,
        "rating": str(rng.choice(["AA", "A", "BBB"])),  # clearing counterparty
        "coupon_pct": "",
        "derivative_subtype": "equity_future",
        "delta": 1.0,  # long
        "duration_yrs": "",
        "data_origin": "synthetic",
    }


def _interest_rate_swap(rng, i):
    tenor = round(float(rng.uniform(2, 10)), 1)
    return {
        "id": f"D-IRS{i:02d}",
        "type": "derivative",
        "notional": round(float(rng.uniform(20, 150)), 1),
        "sector": str(rng.choice(SECTORS)),
        "maturity_yrs": tenor,
        "rating": str(rng.choice(["AA", "A", "BBB"])),  # dealer counterparty
        "coupon_pct": round(float(rng.uniform(3.0, 6.0)), 2),  # fixed leg
        "derivative_subtype": "interest_rate_swap",
        "delta": "",
        "duration_yrs": tenor,  # swap duration ~ tenor (simplified)
        "data_origin": "synthetic",
    }


def build_portfolio(path):
    """Build the deterministic synthetic portfolio and write it to ``path``.

    Returns the list of row dicts.
    """
    rng = np.random.default_rng(SEED)
    rows = []
    for i in range(1, 11):
        rows.append(_loan(rng, i))
    for i in range(1, 13):
        rows.append(_bond(rng, i))
    for i in range(1, 5):
        rows.append(_equity_future(rng, i))
    for i in range(1, 5):
        rows.append(_interest_rate_swap(rng, i))

    # Guarantee the full rating ladder is represented so the jury demo
    # exercises every spread-sensitivity factor (AAA..CCC).
    rows[9]["rating"] = "B"      # L10
    rows[21]["rating"] = "CCC"   # B12

    assert len(rows) == N_ROWS, f"expected {N_ROWS} rows, got {len(rows)}"

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


if __name__ == "__main__":
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "data/synthetic_portfolio.csv"
    rows = build_portfolio(out)
    print(f"Wrote {len(rows)} synthetic positions to {out}")
