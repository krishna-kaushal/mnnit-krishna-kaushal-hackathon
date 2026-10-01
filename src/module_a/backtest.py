"""Module A — Tactical Index Rebalancer (backtest runner).

Rebalancing rule (documented per spec):

* **Frequency:** daily. Weights are set at each trading day's close using all
  signals timestamped on or before that day (signals are also allowed on the
  same calendar day — they are assumed available before the close).
* **Per ticker, per day:** ``s_i`` = mean sentiment of signals mentioning that
  ticker in the *trailing 5 calendar days* (``(t - 5d, t]``); ``s_i = 0`` if
  no signal mentions the ticker in the window.
* **Raw score:** ``r_i = clip(1 + k * s_i, 0, 2)`` with ``k = 2.0``.
* **Weights:** ``w_i = r_i / sum_j(r_j)`` — long-only, fully invested,
  no transaction costs.

The strategy's daily return on date ``t`` applies the previous close's
weights to that day's price returns. The baseline is equal-weight
(``1/15``), rebalanced daily.

Metrics (annualized on 252 trading days, risk-free rate = 0) for both
strategy and baseline:

* cumulative return ``= equity[-1] - 1`` (equity normalized to 1.0 at start);
* Sharpe ``= mean(daily_ret) * 252 / (std(daily_ret) * sqrt(252))``;
* max drawdown ``= max((peak - equity) / peak)`` over the equity curve;
* turnover ``= mean_t(sum_i |w_t - w_{t-1}| / 2) * 252`` — the average daily
  two-way rotation of the portfolio, annualized. (Simple definition using
  consecutive target weights; the equal-weight baseline therefore has zero
  turnover.)

Price data: daily closes for the universe via yfinance (``period="6mo"``,
``auto_adjust=True``). On any failure — no network, yfinance missing — or
with ``--offline``, a deterministic synthetic price panel is generated
(seeded geometric Brownian motion, ``numpy.random.default_rng(42)``,
per-ticker drift/vol, ~126 business days ending today). The panel actually
used is always written to ``data/sample_prices.csv``.

Signals: read from ``data/signals.jsonl`` (repo root), one JSON object per
line. Flexible schema — each line must carry a timestamp, a ticker mention
and a sentiment value under any of these keys:

* timestamp: ``date`` | ``timestamp`` | ``ts`` (ISO-8601; date-only OK);
* ticker: ``ticker`` (single) | ``tickers`` | ``symbols`` (list);
* sentiment: ``sentiment`` | ``sentiment_score`` | ``score``.

Signal sentiment is assumed to be on a [-1, 1] scale; anything outside is
handled by the ``clip`` in the score formula. If the file is missing or
empty, all sentiments are 0 (strategy == equal weight) and the results JSON
records ``"signals_used": false``.

Outputs (all under repo-root ``data/``):

* ``weights_history.csv`` — ``date,ticker,weight`` (weights sum to 1 per date);
* ``equity_curves.csv`` — ``date,strategy,baseline`` (normalized to 1.0);
* ``module_a_results.json`` — parameters, period, data source, metrics.

Usage: ``PYTHONPATH=src python -m module_a.backtest [--offline]``

Dependencies: numpy, pandas, yfinance (optional), python-dateutil.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
SIGNALS_PATH = DATA_DIR / "signals.jsonl"
PRICES_CSV_PATH = DATA_DIR / "sample_prices.csv"
WEIGHTS_CSV_PATH = DATA_DIR / "weights_history.csv"
EQUITY_CSV_PATH = DATA_DIR / "equity_curves.csv"
RESULTS_JSON_PATH = DATA_DIR / "module_a_results.json"

UNIVERSE = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "AVGO",
            "TSLA", "JPM", "V", "XOM", "UNH", "MA", "PG", "HD"]

K = 2.0
LOOKBACK_DAYS = 5
N_SYNTH_DAYS = 126
RNG_SEED = 42
ANNUALIZATION = 252

TIMESTAMP_KEYS = ("date", "timestamp", "ts")
TICKER_KEYS = ("ticker", "tickers", "symbols")
SENTIMENT_KEYS = ("sentiment", "sentiment_score", "score")


# ---------------------------------------------------------------------------
# Price panel
# ---------------------------------------------------------------------------

def load_yfinance_prices(universe: list[str]) -> pd.DataFrame:
    """Download daily closes via yfinance. Raises on any problem."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is not installed") from exc
    frame = yf.download(
        tickers=" ".join(universe),
        period="6mo",
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if frame is None or frame.empty:
        raise RuntimeError("yfinance returned no data")
    # yfinance >= 0.2.32 returns MultiIndex columns; keep the Close level.
    if isinstance(frame.columns, pd.MultiIndex):
        closes = frame["Close"]
    else:
        closes = frame
    closes = closes.reindex(columns=universe).dropna(how="all")
    closes = closes.dropna()
    if closes.empty or closes.shape[1] != len(universe):
        raise RuntimeError("yfinance data incomplete for universe")
    closes.index = pd.to_datetime(closes.index).date
    return closes


def synthetic_prices(universe: list[str],
                     n_days: int = N_SYNTH_DAYS,
                     seed: int = RNG_SEED) -> pd.DataFrame:
    """Deterministic seeded-GBM price panel (~n_days biz days ending today)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=date.today(), periods=n_days).date
    dt = 1.0 / ANNUALIZATION
    cols = {}
    for ticker in universe:
        mu = float(rng.uniform(-0.10, 0.30))      # annual drift
        sigma = float(rng.uniform(0.15, 0.45))    # annual vol
        s0 = float(rng.uniform(50.0, 400.0))
        z = rng.standard_normal(len(dates))
        log_ret = (mu - 0.5 * sigma ** 2) * dt + sigma * math.sqrt(dt) * z
        cols[ticker] = s0 * np.exp(np.cumsum(log_ret))
    return pd.DataFrame(cols, index=pd.Index(dates, name="date"))


def load_price_panel(universe: list[str], offline: bool) -> tuple[pd.DataFrame, str]:
    """Return (price panel, data_source). Falls back to synthetic on failure."""
    if not offline:
        try:
            return load_yfinance_prices(universe), "yfinance"
        except Exception as exc:  # noqa: BLE001 - any failure -> synthetic
            print(f"[module_a] yfinance failed ({exc}); using synthetic prices.",
                  file=sys.stderr)
    return synthetic_prices(universe), "synthetic_sample"


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def _parse_timestamp(value) -> date | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value).date()
        text = str(value).strip()
        if not text:
            return None
        # dateutil is a declared dependency; fall back to fromisoformat.
        try:
            from dateutil import parser as date_parser
            return date_parser.parse(text).date()
        except Exception:  # noqa: BLE001
            return datetime.fromisoformat(text[:19]).date()
    except Exception:  # noqa: BLE001
        return None


def load_signals(path: Path) -> tuple[pd.DataFrame, bool]:
    """Parse signals.jsonl -> DataFrame(date, ticker, sentiment).

    Returns (signals, signals_used). Missing/empty/unparseable file yields
    an empty frame with signals_used=False.
    """
    records: list[tuple[date, str, float]] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = next((obj.get(k) for k in TIMESTAMP_KEYS if obj.get(k) is not None), None)
            ts_date = _parse_timestamp(ts)
            tickers: list[str] = []
            for key in TICKER_KEYS:
                val = obj.get(key)
                if val is None:
                    continue
                tickers = [val] if isinstance(val, str) else list(val)
                break
            sent = next((obj.get(k) for k in SENTIMENT_KEYS if obj.get(k) is not None), None)
            if ts_date is None or not tickers or sent is None:
                continue
            try:
                sentiment = float(sent)
            except (TypeError, ValueError):
                continue
            for t in tickers:
                ticker = str(t).strip().upper()
                if ticker:
                    records.append((ts_date, ticker, sentiment))
    signals = pd.DataFrame(records, columns=["date", "ticker", "sentiment"])
    return signals, bool(not signals.empty)


def trailing_sentiment(signals: pd.DataFrame, day: date,
                       universe: list[str]) -> dict[str, float]:
    """Mean sentiment per ticker over the trailing 5 calendar days (t-5d, t]."""
    start = day - timedelta(days=LOOKBACK_DAYS)
    window = signals[(signals["date"] > start) & (signals["date"] <= day)]
    means = window.groupby("ticker")["sentiment"].mean()
    return {t: float(means.get(t, 0.0)) for t in universe}


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------

def compute_weights(signals: pd.DataFrame, dates: list[date],
                    universe: list[str], k: float = K) -> pd.DataFrame:
    """Daily target weights: r_i = clip(1 + k*s_i, 0, 2); w_i = r_i / sum(r)."""
    rows = []
    for day in dates:
        s = trailing_sentiment(signals, day, universe)
        raw = np.array([min(max(1.0 + k * s[t], 0.0), 2.0) for t in universe])
        w = raw / raw.sum()  # sum(r) > 0 always (each r_i >= 0, max <= 2; degenerate all-0 -> guarded)
        if not np.isfinite(w).all() or w.sum() == 0:
            w = np.full(len(universe), 1.0 / len(universe))
        for ticker, weight in zip(universe, w):
            rows.append((day, ticker, float(weight)))
    return pd.DataFrame(rows, columns=["date", "ticker", "weight"])


def run_backtest(prices: pd.DataFrame, weights: pd.DataFrame,
                 universe: list[str]) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Return (equity_curves, strategy_daily_ret, baseline_daily_ret).

    Strategy applies previous-close weights to each day's price returns;
    baseline is equal-weight rebalanced daily.
    """
    dates = list(prices.index)
    daily_ret = prices.pct_change().iloc[1:]  # first day has no prior close
    w_pivot = weights.pivot(index="date", columns="ticker", values="weight")
    w_pivot = w_pivot.reindex(columns=universe).loc[dates[:-1]]  # weights set at prior close
    strat_ret = (w_pivot.values * daily_ret.values).sum(axis=1)
    strat_ret = pd.Series(strat_ret, index=daily_ret.index, name="strategy")
    base_ret = daily_ret.mean(axis=1).rename("baseline")

    equity = pd.DataFrame({"strategy": (1 + strat_ret).cumprod(),
                           "baseline": (1 + base_ret).cumprod()})
    # Normalize to 1.0 at the first date of the panel.
    first = pd.DataFrame({"strategy": [1.0], "baseline": [1.0]},
                         index=pd.Index([dates[0]], name="date"))
    equity_curves = pd.concat([first, equity])
    equity_curves.index.name = "date"
    return equity_curves, strat_ret, base_ret


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    return float(((peak - equity) / peak).max())


def turnover(weights: pd.DataFrame, universe: list[str]) -> float:
    """Annualized turnover: mean_t(sum_i |w_t - w_{t-1}| / 2) * 252."""
    w = weights.pivot(index="date", columns="ticker", values="weight") \
               .reindex(columns=universe).sort_index()
    daily = w.diff().abs().sum(axis=1).iloc[1:] / 2.0
    return float(daily.mean() * ANNUALIZATION)


def summarize(returns: pd.Series, equity: pd.Series) -> dict[str, float]:
    vol = float(returns.std())
    sharpe = float(returns.mean() * ANNUALIZATION / (vol * math.sqrt(ANNUALIZATION))) \
        if vol > 0 else 0.0
    return {
        "cumulative_return": float(equity.iloc[-1] - 1.0),
        "sharpe": sharpe,
        "max_drawdown": max_drawdown(equity),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Module A — tactical index rebalancer backtest.")
    parser.add_argument("--offline", action="store_true",
                        help="skip yfinance; use deterministic synthetic prices")
    args = parser.parse_args(argv)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    prices, data_source = load_price_panel(UNIVERSE, offline=args.offline)
    prices.to_csv(PRICES_CSV_PATH, index_label="date")

    signals, signals_used = load_signals(SIGNALS_PATH)
    n_signals = int(len(signals))

    dates = list(prices.index)
    weights = compute_weights(signals, dates, UNIVERSE, k=K)
    weights.to_csv(WEIGHTS_CSV_PATH, index=False)

    equity_curves, strat_ret, base_ret = run_backtest(prices, weights, UNIVERSE)
    equity_curves.to_csv(EQUITY_CSV_PATH, index_label="date")

    baseline_weights = pd.DataFrame(
        [(d, t, 1.0 / len(UNIVERSE)) for d in dates for t in UNIVERSE],
        columns=["date", "ticker", "weight"])
    strategy_metrics = summarize(strat_ret, equity_curves["strategy"])
    baseline_metrics = summarize(base_ret, equity_curves["baseline"])
    strategy_metrics["turnover"] = turnover(weights, UNIVERSE)
    baseline_metrics["turnover"] = turnover(baseline_weights, UNIVERSE)

    notes = (
        "Daily rebalance at close; per ticker s_i = mean sentiment over trailing "
        f"{LOOKBACK_DAYS} calendar days (0 if none), r_i = clip(1 + {K}*s_i, 0, 2), "
        "w_i = r_i / sum(r); long-only, fully invested, no transaction costs. "
        "Signal sentiment assumed on a [-1, 1] scale. Turnover = mean_t("
        "sum|w_t - w_{t-1}|/2) * 252. Baseline is equal-weight, daily rebalanced."
    )
    if not signals_used:
        notes += " No usable signals found at data/signals.jsonl; sentiment = 0 for all tickers."
    if data_source == "synthetic_sample":
        notes += (" Prices are deterministic synthetic samples "
                  "(seeded GBM, numpy default_rng(42)), not market data.")

    results = {
        "universe": UNIVERSE,
        "params": {"k": K, "lookback_days": LOOKBACK_DAYS, "rebalance": "daily"},
        "period": {"start": str(dates[0]), "end": str(dates[-1])},
        "data_source": data_source,
        "signals_used": signals_used,
        "n_signals": n_signals,
        "metrics": {"strategy": strategy_metrics, "baseline": baseline_metrics},
        "notes": notes,
    }
    RESULTS_JSON_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")

    # ---- stdout summary ----------------------------------------------------
    def fmt(m: dict[str, float]) -> str:
        return (f"cum_ret={m['cumulative_return']:+.2%}  "
                f"sharpe={m['sharpe']:+.2f}  "
                f"max_dd={m['max_drawdown']:.2%}  "
                f"turnover={m['turnover']:.2f}x")

    print("=" * 64)
    print("Module A — Tactical Index Rebalancer  |  "
          f"{dates[0]} -> {dates[-1]}  ({len(dates)} trading days)")
    print(f"data_source={data_source}  signals_used={signals_used} "
          f"(n={n_signals})  k={K}  lookback={LOOKBACK_DAYS}d")
    print("-" * 64)
    print(f"strategy : {fmt(strategy_metrics)}")
    print(f"baseline : {fmt(baseline_metrics)}")
    print("-" * 64)
    print(f"wrote {PRICES_CSV_PATH.relative_to(REPO_ROOT)}")
    print(f"wrote {WEIGHTS_CSV_PATH.relative_to(REPO_ROOT)}")
    print(f"wrote {EQUITY_CSV_PATH.relative_to(REPO_ROOT)}")
    print(f"wrote {RESULTS_JSON_PATH.relative_to(REPO_ROOT)}")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    sys.exit(main())
