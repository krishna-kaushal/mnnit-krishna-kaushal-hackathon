"""CLI entry point for Module B — event-driven portfolio stress test.

Reads the highest-impact risk signal (Module A output) and reprices the
synthetic portfolio under the matching shock scenario.

Usage:
    PYTHONPATH=src python -m module_b.stress_test [options]

Options:
    --signal-id ID       run the signal with this id (from data/signals.jsonl)
    --event-class CLASS  manual override: shock library event class
    --impact N           manual override: impact score recorded on the trigger
    --min-impact N       auto-select threshold (default 7): the highest-impact
                         signal with impact >= N wins

Trigger selection:
    1. If ``data/signals.jsonl`` exists at the repo root, the highest-impact
       signal with impact >= --min-impact is used (--signal-id forces a
       specific one; --event-class/--impact override the recorded values).
    2. Otherwise the run falls back to a default illustrative trigger
       {"event_class": "Geopolitical", "impact": 8,
        "signal_id": "synthetic-demo"} and says so on stdout.

Output: data/module_b_results.json + a readable before/after summary.
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
SIGNALS_PATH = DATA_DIR / "signals.jsonl"
PORTFOLIO_PATH = DATA_DIR / "synthetic_portfolio.csv"
RESULTS_PATH = DATA_DIR / "module_b_results.json"

DEFAULT_TRIGGER = {
    "event_class": "Geopolitical",
    "impact": 8,
    "signal_id": "synthetic-demo",
}

from module_b.portfolio import build_portfolio  # noqa: E402
from module_b.shocks import SHOCK_LIBRARY, get_shock, stress_portfolio  # noqa: E402


def _parse_args(argv=None):
    p = argparse.ArgumentParser(description="Module B portfolio stress test")
    p.add_argument("--signal-id", default=None, help="run a specific signal id")
    p.add_argument("--event-class", default=None, help="manual event-class override")
    p.add_argument("--impact", type=float, default=None,
                   help="manual impact override")
    p.add_argument("--min-impact", type=float, default=7,
                   help="auto-select threshold (default 7)")
    return p.parse_args(argv)


def _load_signals():
    """Yield signal dicts from data/signals.jsonl; empty list if missing."""
    if not SIGNALS_PATH.exists():
        return []
    signals = []
    with open(SIGNALS_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                signals.append(json.loads(line))
    return signals


def _select_trigger(signals, args):
    """Return (trigger_dict, source_note)."""
    if args.signal_id:
        for s in signals:
            if str(s.get("signal_id")) == str(args.signal_id):
                return _trigger_from_signal(s), "manual --signal-id"
        raise SystemExit(f"error: signal_id {args.signal_id!r} not found in "
                         f"{SIGNALS_PATH}")

    event_class = args.event_class
    impact = args.impact
    timestamp = None
    signal_id = "manual-override"

    if event_class is None:
        eligible = [s for s in signals if float(s.get("impact", 0)) >= args.min_impact]
        if not eligible:
            return (
                {
                    "signal_id": DEFAULT_TRIGGER["signal_id"],
                    "event_class": DEFAULT_TRIGGER["event_class"],
                    "impact": DEFAULT_TRIGGER["impact"],
                    "timestamp": None,
                },
                "default synthetic trigger (no signals file / no eligible signal)",
            )
        best = max(eligible, key=lambda s: float(s.get("impact", 0)))
        return _trigger_from_signal(best), "auto-selected highest-impact signal"

    # Manual event class; impact may also be manual.
    return {
        "signal_id": signal_id,
        "event_class": event_class,
        "impact": impact if impact is not None else DEFAULT_TRIGGER["impact"],
        "timestamp": timestamp,
    }, "manual --event-class/--impact"


def _trigger_from_signal(s):
    return {
        "signal_id": s.get("signal_id"),
        "event_class": s.get("event_class"),
        "impact": s.get("impact"),
        "timestamp": s.get("timestamp"),
    }


def _ensure_portfolio():
    """Build the synthetic portfolio CSV if it does not exist yet."""
    if not PORTFOLIO_PATH.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        build_portfolio(str(PORTFOLIO_PATH))
        print(f"note: generated synthetic portfolio at {PORTFOLIO_PATH}")
    with open(PORTFOLIO_PATH, newline="") as f:
        return list(csv.DictReader(f))


def _print_summary(trigger, source_note, result, shocks_applied):
    print("=" * 64)
    print("MODULE B — EVENT-DRIVEN PORTFOLIO STRESS TEST")
    print("=" * 64)
    print(f"Trigger:  {trigger['event_class']} "
          f"(signal {trigger['signal_id']}, impact {trigger['impact']})")
    print(f"Source:   {source_note}")
    print(f"Shocks:   equity {shocks_applied['equity']:+.2%}, "
          f"rates {shocks_applied['rates']:+.2%}, "
          f"credit spread {shocks_applied['credit_spread']:+.2%}")
    print("-" * 64)
    print(f"Portfolio value BEFORE: ${result['portfolio_value_before']:>10,.2f}M")
    print(f"Portfolio value AFTER:  ${result['portfolio_value_after']:>10,.2f}M")
    print(f"Total loss:             ${result['total_loss']:>10,.2f}M "
          f"({result['loss_pct']:+.2f}%)")
    print("-" * 64)
    print(f"{'Asset class':<14}{'Before ($M)':>12}{'After ($M)':>12}{'Loss ($M)':>12}")
    for a in result["attribution"]:
        print(f"{a['asset_class']:<14}{a['before']:>12,.2f}"
              f"{a['after']:>12,.2f}{a['loss']:>12,.2f}")
    print("=" * 64)


def main(argv=None):
    args = _parse_args(argv)

    signals = _load_signals()
    trigger, source_note = _select_trigger(signals, args)

    event_class = trigger["event_class"]
    if event_class not in SHOCK_LIBRARY:
        raise SystemExit(
            f"error: unknown event_class {event_class!r}; "
            f"known: {sorted(SHOCK_LIBRARY)}"
        )
    shocks_applied = get_shock(event_class)

    rows = _ensure_portfolio()
    result = stress_portfolio(rows, shocks_applied)

    payload = {
        "trigger": trigger,
        "portfolio_value_before": result["portfolio_value_before"],
        "portfolio_value_after": result["portfolio_value_after"],
        "total_loss": result["total_loss"],
        "loss_pct": result["loss_pct"],
        "attribution": result["attribution"],
        "shocks_applied": shocks_applied,
        "positions": result["positions"],
        "notes": "simplified illustrative model",
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w") as f:
        json.dump(payload, f, indent=2)
    print(f"results written to {RESULTS_PATH}")

    _print_summary(trigger, source_note, result, shocks_applied)
    return 0


if __name__ == "__main__":
    sys.exit(main())
