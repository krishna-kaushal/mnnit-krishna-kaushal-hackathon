"""
Sentinel — AI/NLP Risk Engine dashboard.

The 10-minute demo vehicle for the S&P Global & Crisil Campus Hackathon
"Code to Connect" case study. Three tabs:

1. Live Risk Feed  — signals produced by risk_engine.pipeline
2. Index Rebalancer — Module A backtest results (strategy vs baseline)
3. Stress Tester    — Module B portfolio stress-test results

Run:  PYTHONPATH=src streamlit run src/dashboard/app.py   (from repo root)

Everything here is defensive: if a data file doesn't exist yet, each tab
renders an `st.info(...)` empty state instead of crashing. The dashboard
never writes outside data/ or src/dashboard — pipeline/backtest buttons
just invoke the corresponding modules via subprocess.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Repo-root resolution: src/dashboard/app.py -> parents[2] == repo root
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SRC = ROOT / "src"

SIGNALS_FILE = DATA / "signals.jsonl"
WEIGHTS_FILE = DATA / "weights_history.csv"
CURVES_FILE = DATA / "equity_curves.csv"
MODULE_A_FILE = DATA / "module_a_results.json"
PORTFOLIO_FILE = DATA / "synthetic_portfolio.csv"
MODULE_B_FILE = DATA / "module_b_results.json"

st.set_page_config(page_title="Sentinel — AI/NLP Risk Engine", layout="wide")

# ---------------------------------------------------------------------------
# Data loaders (all return None / empty on missing or malformed data)
# ---------------------------------------------------------------------------


def load_signals() -> pd.DataFrame:
    """Read data/signals.jsonl -> DataFrame (newest first), [] if missing."""
    rows = []
    if not SIGNALS_FILE.exists():
        return pd.DataFrame(rows)
    try:
        with open(SIGNALS_FILE, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.sort_values("timestamp", ascending=False).reset_index(drop=True)
    return df


def load_json(path: Path):
    """Load a JSON file, returning None on any failure."""
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def load_csv(path: Path) -> pd.DataFrame:
    """Load a CSV file, returning an empty DataFrame on any failure."""
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:  # malformed CSV should not kill the demo
        return pd.DataFrame()


def run_module(args, label: str) -> bool:
    """Run a module as `python -m <...>`, showing progress and the outcome.

    Returns True when the subprocess exits 0.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    with st.spinner(f"{label} — this can take a moment…"):
        try:
            proc = subprocess.run(
                [sys.executable, "-m", *args],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except subprocess.TimeoutExpired:
            st.error(f"{label} timed out after 10 minutes.")
            return False
        except OSError as exc:
            st.error(f"Could not start {label}: {exc}")
            return False
    if proc.returncode == 0:
        st.success(f"{label} finished.")
        if proc.stdout.strip():
            with st.expander("Command output"):
                st.code(proc.stdout.strip()[-4000:])
        return True
    st.error(f"{label} failed (exit {proc.returncode}).")
    detail = (proc.stderr or proc.stdout or "").strip()[-4000:]
    if detail:
        with st.expander("Error output"):
            st.code(detail)
    return False


def fmt_pct(x) -> str:
    try:
        return f"{float(x):.2%}"
    except (TypeError, ValueError):
        return "—"


def fmt_num(x, digits=2) -> str:
    try:
        return f"{float(x):.{digits}f}"
    except (TypeError, ValueError):
        return "—"


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("Sentinel — AI/NLP Risk Engine")
st.caption(
    "AI/NLP-driven risk sensing for Indian markets: live sentiment & event "
    "signals feeding an index rebalancer and a portfolio stress tester."
)

tab_feed, tab_rebalancer, tab_stress = st.tabs(
    ["Live Risk Feed", "Index Rebalancer", "Stress Tester"]
)

# ===========================================================================
# TAB 1 — Live Risk Feed
# ===========================================================================
with tab_feed:
    st.subheader("Risk signal feed")
    col_refresh, _ = st.columns([1, 3])
    with col_refresh:
        if st.button("🔄 Refresh signals", use_container_width=True):
            ok = run_module(
                [
                    "risk_engine.pipeline",
                    "--sources",
                    "synthetic_social",
                    "--limit",
                    "40",
                ],
                "Signal pipeline",
            )
            if ok:
                st.rerun()

    signals = load_signals()
    if signals.empty:
        st.info(
            "No signals yet — run the pipeline first: "
            "`python -m risk_engine.pipeline --sources synthetic_social --limit 40` "
            "or hit **🔄 Refresh signals** above."
        )
    else:
        # ---- backend badges: show the jury what's real vs fallback --------
        models = []
        for col in ("sentiment_model", "event_model"):
            if col in signals.columns and signals[col].notna().any():
                vals = sorted(signals[col].dropna().astype(str).unique())
                models.append(f"`{col}`: {', '.join(vals)}")
        if models:
            st.caption("Backend: " + "  ·  ".join(models))

        # ---- filters -------------------------------------------------------
        f1, f2, f3 = st.columns(3)
        with f1:
            classes = (
                sorted(signals["event_class"].dropna().astype(str).unique())
                if "event_class" in signals.columns
                else []
            )
            chosen_classes = st.multiselect(
                "Event class", options=classes, default=classes
            )
        with f2:
            min_impact = st.slider("Min impact", 1, 10, 1)
        with f3:
            sources = (
                sorted(signals["source"].dropna().astype(str).unique())
                if "source" in signals.columns
                else []
            )
            chosen_sources = st.multiselect("Source", options=sources, default=sources)

        view = signals.copy()
        if "event_class" in view.columns and chosen_classes:
            view = view[view["event_class"].astype(str).isin(chosen_classes)]
        if "source" in view.columns and chosen_sources:
            view = view[view["source"].astype(str).isin(chosen_sources)]
        if "impact" in view.columns:
            view = view[pd.to_numeric(view["impact"], errors="coerce") >= min_impact]

        st.caption(f"Showing {len(view)} of {len(signals)} signals (newest first)")

        # ---- impact distribution ------------------------------------------
        if not view.empty and "impact" in view.columns:
            imp = pd.to_numeric(view["impact"], errors="coerce").dropna()
            fig_imp = px.histogram(
                imp,
                x="impact",
                nbins=10,
                title="Impact distribution",
                labels={"impact": "Impact (1–10)"},
            )
            fig_imp.update_layout(bargap=0.15, height=320)
            st.plotly_chart(fig_imp, use_container_width=True)

        # ---- signal table --------------------------------------------------
        if view.empty:
            st.info("No signals match the current filters.")
        else:
            table = pd.DataFrame()
            table["time"] = (
                pd.to_datetime(view.get("timestamp"), errors="coerce").dt.strftime(
                    "%Y-%m-%d %H:%M"
                )
                if "timestamp" in view.columns
                else ""
            )
            table["source"] = view.get("source", "")
            table["tickers"] = view.get("tickers", []).apply(
                lambda t: ", ".join(t) if isinstance(t, list) else ""
            )
            table["sentiment"] = pd.to_numeric(
                view.get("sentiment"), errors="coerce"
            ).round(2)
            table["event class"] = view.get("event_class", "")
            table["impact"] = view.get("impact", "")
            st.dataframe(table, use_container_width=True, hide_index=True)

            # expandable detail per signal (top 10 of the filtered view)
            st.markdown("**Signal detail**")
            for _, row in view.head(10).iterrows():
                label = f"{row.get('event_class', '?')} · impact {row.get('impact', '?')} · {str(row.get('title', ''))[:80]}"
                with st.expander(label):
                    st.write(row.get("text", ""))
                    meta = {
                        k: row.get(k)
                        for k in ("id", "timestamp", "url", "sectors",
                                  "sentiment_model", "event_model",
                                  "impact_breakdown")
                        if k in row and row.get(k) not in (None, "")
                    }
                    if meta:
                        st.json(meta, expanded=False)

# ===========================================================================
# TAB 2 — Index Rebalancer (Module A)
# ===========================================================================
with tab_rebalancer:
    st.subheader("Module A — Risk-aware index rebalancer")

    results_a = load_json(MODULE_A_FILE)
    curves = load_csv(CURVES_FILE)
    weights = load_csv(WEIGHTS_FILE)

    if st.button("▶ Run backtest", use_container_width=False):
        # No --offline: tries yfinance live, falls back to synthetic automatically.
        if run_module(["module_a.backtest"], "Module A backtest"):
            st.rerun()

    if results_a is None and curves.empty:
        st.info(
            "No backtest results yet — run the backtest first: "
            "`python -m module_a.backtest` or hit **▶ Run backtest** above."
        )
    else:
        metrics = (results_a or {}).get("metrics", {})
        strat = metrics.get("strategy", {}) or {}
        base = metrics.get("baseline", {}) or {}

        st.caption(
            f"Universe: `{(results_a or {}).get('universe', '—')}`  ·  "
            f"Period: `{(results_a or {}).get('period', '—')}`  ·  "
            f"Signals used: `{(results_a or {}).get('n_signals', '—')}`"
        )

        # ---- metric cards --------------------------------------------------
        cards = [
            ("Cumulative return", "cumulative_return", fmt_pct),
            ("Sharpe ratio", "sharpe", lambda x: fmt_num(x, 2)),
            ("Max drawdown", "max_drawdown", fmt_pct),
            ("Turnover", "turnover", fmt_pct),
        ]
        m1, m2 = st.columns(2)
        m1.markdown("**Risk-aware strategy**")
        m2.markdown("**Baseline (equal-weight)**")
        for label, key, fmt in cards:
            c1, c2 = st.columns(2)
            c1.metric(label, fmt(strat.get(key)))
            c2.metric(label, fmt(base.get(key)))

        notes = (results_a or {}).get("notes")
        if notes:
            st.caption(f"Notes: {notes}")

        # ---- equity curves -------------------------------------------------
        if not curves.empty and {"date", "strategy", "baseline"}.issubset(curves.columns):
            fig = go.Figure()
            dates = pd.to_datetime(curves["date"], errors="coerce")
            fig.add_trace(
                go.Scatter(x=dates, y=curves["strategy"], mode="lines",
                           name="Risk-aware strategy")
            )
            fig.add_trace(
                go.Scatter(x=dates, y=curves["baseline"], mode="lines",
                           name="Baseline", line=dict(dash="dash"))
            )
            fig.update_layout(
                title="Equity curves", xaxis_title="Date",
                yaxis_title="Cumulative return", height=380,
            )
            st.plotly_chart(fig, use_container_width=True)
        elif not curves.empty:
            st.warning(
                "equity_curves.csv found but missing required columns "
                "(date, strategy, baseline)."
            )

        # ---- weight evolution (stacked area, top 8 + Other) ----------------
        if not weights.empty and {"date", "ticker", "weight"}.issubset(weights.columns):
            w = weights.copy()
            w["date"] = pd.to_datetime(w["date"], errors="coerce")
            pivot = (
                w.pivot_table(index="date", columns="ticker",
                              values="weight", aggfunc="sum")
                .fillna(0.0)
                .sort_index()
            )
            top8 = pivot.sum().nlargest(8).index.tolist()
            stack = pivot[top8].copy()
            other = pivot.drop(columns=top8, errors="ignore").sum(axis=1)
            if (other != 0).any():
                stack["Other"] = other
            fig_w = px.area(
                stack.reset_index(), x="date", y=stack.columns.tolist(),
                title="Weight evolution (top 8 tickers + Other)",
                labels={"date": "Date", "value": "Weight"},
            )
            fig_w.update_layout(height=380)
            st.plotly_chart(fig_w, use_container_width=True)
        elif not weights.empty:
            st.warning(
                "weights_history.csv found but missing required columns "
                "(date, ticker, weight)."
            )

        data_source = (results_a or {}).get("data_source", "unknown")
        st.caption(
            f"Data source: **{data_source}** "
            + ("(live yfinance prices)" if data_source == "yfinance"
               else "(synthetic prices — yfinance unavailable)")
            if data_source != "unknown"
            else "Data source: unknown — rerun the backtest to record it."
        )

# ===========================================================================
# TAB 3 — Stress Tester (Module B)
# ===========================================================================
with tab_stress:
    st.subheader("Module B — Portfolio stress tester")

    results_b = load_json(MODULE_B_FILE)
    portfolio = load_csv(PORTFOLIO_FILE)

    # ---- trigger selection -------------------------------------------------
    trigger_mode = st.selectbox(
        "Trigger signal",
        ["Latest high-impact signal (≥7)", "Manual trigger"],
    )
    manual_class, manual_impact, latest_signal = None, None, None
    if trigger_mode == "Latest high-impact signal (≥7)":
        signals_b = load_signals()
        if not signals_b.empty and "impact" in signals_b.columns:
            hi = signals_b[
                pd.to_numeric(signals_b["impact"], errors="coerce") >= 7
            ]
            if not hi.empty:
                latest_signal = hi.iloc[0].to_dict()
                st.caption(
                    f"Using signal `{latest_signal.get('id', '?')}` — "
                    f"{latest_signal.get('event_class', '?')} "
                    f"(impact {latest_signal.get('impact', '?')})"
                )
            else:
                st.info("No signal with impact ≥ 7 yet — run the pipeline first.")
        else:
            st.info("No signals yet — run the pipeline first, or use manual trigger.")
    else:
        mc1, mc2 = st.columns(2)
        with mc1:
            signals_b = load_signals()
            class_opts = (
                sorted(signals_b["event_class"].dropna().astype(str).unique())
                if not signals_b.empty and "event_class" in signals_b.columns
                else []
            ) or [
                "earnings", "regulatory", "geopolitical",
                "fraud", "macro", "natural_disaster",
            ]
            manual_class = st.selectbox("Event class", class_opts)
        with mc2:
            manual_impact = st.slider("Impact", 1, 10, 8)

    if st.button("▶ Run stress test", use_container_width=False):
        cmd = ["module_b.stress_test"]
        # Flags are best-effort: pass the chosen trigger through so the
        # module can use it; the module decides how to honour them.
        if latest_signal is not None and latest_signal.get("id"):
            cmd += ["--signal-id", str(latest_signal["id"])]
        elif manual_class is not None:
            cmd += ["--event-class", manual_class, "--impact", str(manual_impact)]
        if run_module(cmd, "Module B stress test"):
            st.rerun()

    # ---- results -----------------------------------------------------------
    if results_b is None:
        st.info(
            "No stress-test results yet — run the stress test first: "
            "`python -m module_b.stress_test` or hit **▶ Run stress test** above."
        )
    else:
        before = results_b.get("portfolio_value_before")
        after = results_b.get("portfolio_value_after")
        loss = results_b.get("total_loss")
        loss_pct = results_b.get("loss_pct")

        def fmt_money(x) -> str:
            try:
                return f"₹{float(x):,.0f}"
            except (TypeError, ValueError):
                return "—"

        b1, b2, b3 = st.columns(3)
        b1.metric("Portfolio value — before", fmt_money(before))
        b2.metric("Portfolio value — after", fmt_money(after))
        b3.metric("Loss", f"{fmt_money(loss)} ({fmt_pct(loss_pct)})")

        # loss attribution bar chart
        attribution = results_b.get("attribution") or []
        attr_df = pd.DataFrame(attribution)
        if not attr_df.empty and {"asset_class", "loss"}.issubset(attr_df.columns):
            fig_a = px.bar(
                attr_df, x="asset_class", y="loss",
                title="Loss attribution by asset class",
                labels={"asset_class": "Asset class", "loss": "Loss (₹)"},
                color="asset_class",
            )
            fig_a.update_layout(height=360, showlegend=False)
            st.plotly_chart(fig_a, use_container_width=True)
        elif attribution:
            st.caption("Attribution data present but not in asset_class/loss form:")
            st.json(attribution)

        # triggering signal
        trigger = results_b.get("trigger") or {}
        st.markdown("**Triggering signal**")
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Signal ID", str(trigger.get("signal_id", "—")))
        t2.metric("Event class", str(trigger.get("event_class", "—")))
        t3.metric("Impact", str(trigger.get("impact", "—")))
        t4.metric("Timestamp", str(trigger.get("timestamp", "—"))[:16])

        # shocks applied
        shocks = results_b.get("shocks_applied")
        if shocks:
            st.markdown("**Shocks applied**")
            if isinstance(shocks, dict):
                st.json(shocks)
            elif isinstance(shocks, list):
                st.dataframe(pd.DataFrame(shocks), use_container_width=True,
                             hide_index=True)
            else:
                st.write(shocks)

        # positions snapshot
        positions = results_b.get("positions")
        if positions:
            with st.expander("Positions"):
                if isinstance(positions, list):
                    st.dataframe(pd.DataFrame(positions), use_container_width=True,
                                 hide_index=True)
                else:
                    st.json(positions)

        # optional: current synthetic portfolio composition
        if not portfolio.empty:
            with st.expander("Current portfolio holdings (synthetic_portfolio.csv)"):
                st.dataframe(portfolio, use_container_width=True, hide_index=True)

        notes_b = results_b.get("notes")
        if notes_b:
            st.caption(f"Notes: {notes_b}")

st.divider()
st.caption("Sentinel · S&P Global & Crisil Campus Hackathon 2026 — Phase III")
