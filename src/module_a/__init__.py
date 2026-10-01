"""Module A — Tactical Index Rebalancer.

Turns sentiment signals from the risk engine (``data/signals.jsonl``) into a
daily-rebalanced, long-only tilt on a fixed 15-stock S&P 500 universe, and
backtests it against a daily-rebalanced equal-weight baseline.

Rebalancing rule (see ``backtest.py`` for the exact implementation):

* daily rebalance; for each ticker and day ``t``,
  ``s_i = mean`` sentiment of signals mentioning that ticker in the trailing
  5 calendar days (0 if none);
* raw score ``r_i = clip(1 + k * s_i, 0, 2)`` with ``k = 2.0``;
* portfolio weight ``w_i = r_i / sum(r)`` — long-only, fully invested.

Assumptions: rebalance at each day's close using signals timestamped through
that day; no transaction costs; signal sentiment is on a [-1, 1] scale
(out-of-range values are clipped by the score formula).
"""
