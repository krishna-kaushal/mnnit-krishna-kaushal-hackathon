"""Shock scenario library and valuation logic for Module B.

IMPORTANT — simplified illustrative model:
This module is built for a hackathon demo. The valuation formulas below
are deliberately simple first-order approximations, NOT a production
risk engine. In particular:

* There is no full cash-flow repricing, no convexity, no curve tenor
  structure, no basis risk, and no netting/collateral.
* ``duration_yrs`` is approximated as maturity/tenor (modified duration
  ~ maturity at par). Real floating-rate loans would have much shorter
  duration than their maturity — we keep the simple approximation so
  the model is transparent for the jury.
* Shocks are parallel, instantaneous, and deterministic; market liquidity
  effects and second-order moves are ignored.
* "Loss" is a positive number meaning value destroyed; "value_after"
  is simply before minus loss. There are no re-hedges between
  scenario application and revaluation.

Model:
    value_before = sum of notionals (exposure basis, USDm)

    bond / loan loss =
        notional * duration_yrs * (rates_shock + credit_spread_shock * rating_factor)

    equity_future loss (long, delta=1) =
        -equity_shock * notional * delta
        (loss is positive when the shock is negative)

    interest_rate_swap loss (receive-fixed) =
        notional * duration_yrs * rates_shock
        (receiving fixed loses when rates rise)

    value_after = value_before - total_loss

    Attribution is summed by asset class (loan / bond / derivative).
"""

# ---------------------------------------------------------------------------
# Shock library, keyed by event class. Units:
#   equity        — fractional spot shock (e.g. -0.10 = -10%)
#   rates         — absolute parallel shift in decimal (e.g. 0.02 = +200 bps)
#   credit_spread — absolute spread shift in decimal (e.g. 0.0150 = +150 bps)
# These are illustrative, not calibrated to any real event.
# ---------------------------------------------------------------------------
SHOCK_LIBRARY = {
    "Geopolitical": {"equity": -0.10, "rates": 0.02, "credit_spread": 0.0150},
    "Macroeconomic": {"equity": -0.05, "rates": 0.015, "credit_spread": 0.0100},
    "Credit Event": {"equity": -0.07, "rates": 0.005, "credit_spread": 0.0200},
    "Merger/Acquisition": {"equity": 0.04, "rates": 0.0, "credit_spread": -0.0025},
    "Product Launch": {"equity": 0.02, "rates": 0.0, "credit_spread": 0.0},
}

# Rating -> spread sensitivity multiplier. Lower-rated paper moves more
# for the same market-wide spread shock (illustrative ladder).
RATING_SPREAD_FACTOR = {
    "AAA": 0.5,
    "AA": 0.7,
    "A": 1.0,
    "BBB": 1.5,
    "BB": 2.5,
    "B": 3.5,
    "CCC": 5.0,
}


def get_shock(event_class):
    """Return the shock dict for an event class; raise KeyError if unknown."""
    return dict(SHOCK_LIBRARY[event_class])


def _num(row, key, default=0.0):
    val = row.get(key, "")
    if val in (None, ""):
        return default
    return float(val)


def position_loss(row, shocks):
    """Loss (positive = value destroyed, USDm) for one position row."""
    ptype = row["type"]
    notional = float(row["notional"])

    if ptype in ("loan", "bond"):
        duration = _num(row, "duration_yrs", default=float(row["maturity_yrs"]))
        rating_factor = RATING_SPREAD_FACTOR[row["rating"]]
        combined = shocks["rates"] + shocks["credit_spread"] * rating_factor
        return notional * duration * combined

    if ptype == "derivative":
        subtype = row["derivative_subtype"]
        if subtype == "equity_future":
            delta = _num(row, "delta", default=1.0)
            return -shocks["equity"] * notional * delta
        if subtype == "interest_rate_swap":
            duration = _num(row, "duration_yrs", default=float(row["maturity_yrs"]))
            return notional * duration * shocks["rates"]
        raise ValueError(f"unknown derivative_subtype: {subtype!r}")

    raise ValueError(f"unknown position type: {ptype!r}")


def stress_portfolio(rows, shocks):
    """Run one scenario over all rows.

    Returns a dict with totals, per-class attribution and per-position
    loss detail.
    """
    attribution = {}
    positions = []
    value_before = 0.0
    total_loss = 0.0

    for row in rows:
        notional = float(row["notional"])
        loss = position_loss(row, shocks)
        after = notional - loss
        value_before += notional
        total_loss += loss

        bucket = attribution.setdefault(
            row["type"], {"before": 0.0, "after": 0.0, "loss": 0.0}
        )
        bucket["before"] += notional
        bucket["after"] += after
        bucket["loss"] += loss

        positions.append(
            {
                "id": row["id"],
                "type": row["type"],
                "notional": round(notional, 2),
                "loss": round(loss, 2),
                "value_after": round(after, 2),
            }
        )

    value_after = value_before - total_loss
    loss_pct = (total_loss / value_before * 100.0) if value_before else 0.0

    return {
        "portfolio_value_before": round(value_before, 2),
        "portfolio_value_after": round(value_after, 2),
        "total_loss": round(total_loss, 2),
        "loss_pct": round(loss_pct, 2),
        "attribution": [
            {
                "asset_class": cls,
                "before": round(v["before"], 2),
                "after": round(v["after"], 2),
                "loss": round(v["loss"], 2),
            }
            for cls, v in sorted(attribution.items())
        ],
        "positions": positions,
    }
