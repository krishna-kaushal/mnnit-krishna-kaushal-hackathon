#!/usr/bin/env python3
"""Build the Sentinel slide deck for the S&P Global & Crisil Campus Hackathon 2026.

Reads real run metrics from data/module_a_results.json and
data/module_b_results.json when they exist; otherwise the results slide
carries a "run the pipeline to populate" placeholder.

Outputs:
    docs/presentation.pptx
    docs/presentation.pdf   (only if LibreOffice/soffice is available;
                             the script still succeeds without it)

Usage:
    python3 docs/build_deck.py        # run from the repo root
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (resolved from this file's location so CWD doesn't matter)
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA = ROOT / "data"
PPTX_OUT = DOCS / "presentation.pptx"
PDF_OUT = DOCS / "presentation.pdf"
ARCH_IMG = DOCS / "architecture.png"
MODULE_A_JSON = DATA / "module_a_results.json"
MODULE_B_JSON = DATA / "module_b_results.json"
SIGNALS_JSONL = DATA / "signals.jsonl"

# ---------------------------------------------------------------------------
# Metric extraction (defensive: tries several likely key spellings,
# searches one level of nested dicts)
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _candidates(node: dict) -> dict:
    """Lower-cased key -> value for all entries (scalars and containers).

    Containers are legitimate hits too: fmt_metric() renders dict/list
    values for kind="count" and extracts a name field from dicts.
    """
    return {str(k).lower(): v for k, v in node.items()}


def find_metric(data: dict, aliases: list[str], sections: list[str] | None = None):
    """Return the first value found for any alias, else None.

    Search order:
      1. alias directly at top level (scalar values only);
      2. if *sections* given: DFS for a dict keyed by a section name
         (e.g. data["metrics"]["baseline"]), then alias search inside it.
         Never falls back to other sections (no cross-contamination);
      3. if no sections: generic DFS for the alias anywhere.
    """
    top = _candidates(data)
    for a in aliases:
        if a in top:
            return top[a]

    def scoped(node: dict, depth: int):
        if depth > 5 or not isinstance(node, dict):
            return None
        s = _candidates(node)
        for a in aliases:
            if a in s:
                return s[a]
        for v in node.values():
            if isinstance(v, dict):
                hit = scoped(v, depth + 1)
                if hit is not None:
                    return hit
        return None

    if sections:
        def in_sections(node: dict, depth: int):
            if depth > 4 or not isinstance(node, dict):
                return None
            keymap = {str(k).lower(): k for k in node.keys()}
            for s in sections:
                if s in keymap:
                    sec = node[keymap[s]]
                    if isinstance(sec, dict):
                        hit = scoped(sec, depth + 1)
                        if hit is not None:
                            return hit
            for v in node.values():
                if isinstance(v, dict):
                    hit = in_sections(v, depth + 1)
                    if hit is not None:
                        return hit
            return None
        return in_sections(data, 0)

    return scoped(data, 0)


def fmt_metric(value, kind: str = "num") -> str:
    """Format a raw JSON value for display. Never raises."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    if kind == "count" and isinstance(value, (dict, list)):
        return str(len(value))
    if isinstance(value, dict):
        # e.g. a "trigger" object -> pick its most name-like field
        for k in ("name", "event_class", "scenario", "label", "title"):
            v = value.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()[:40]
        return "—"
    if isinstance(value, (int, float)):
        if kind == "pct":
            # Heuristic: |v| <= 1.5 looks like a fraction -> convert to %.
            v = value * 100.0 if abs(value) <= 1.5 else float(value)
            return f"{v:.2f}%"
        if isinstance(value, float):
            return f"{value:,.3f}"
        return f"{value:,}"
    text = str(value)
    return text if len(text) <= 40 else text[:37] + "..."


def count_signals() -> int | None:
    try:
        with open(SIGNALS_JSONL, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return None


# (label, key aliases, format kind, parent-section aliases to search)
_TILTED = ["strategy", "tilted", "risk_tilted", "risk-tilted"]
_BASE = ["baseline", "equal_weight", "equal-weight", "benchmark"]
METRICS_A = [
    ("Sharpe — risk-tilted", ["sharpe", "sharpe_ratio", "sharpe_tilted", "tilted_sharpe"], "num", _TILTED),
    ("Sharpe — baseline", ["sharpe", "sharpe_ratio", "baseline_sharpe", "sharpe_baseline", "equal_weight_sharpe"], "num", _BASE),
    ("Cum. return — tilted", ["cumulative_return", "cum_return", "total_return", "tilted_return", "strategy_return"], "pct", _TILTED),
    ("Cum. return — baseline", ["cumulative_return", "cum_return", "total_return", "baseline_return", "baseline_cumulative_return", "equal_weight_return"], "pct", _BASE),
    ("Max drawdown", ["max_drawdown", "max_dd", "drawdown"], "pct", _TILTED + _BASE),
    ("Turnover", ["turnover", "avg_turnover"], "pct", _TILTED),
]
METRICS_B = [
    ("Worst scenario loss", ["worst_loss_pct", "max_loss_pct", "worst_scenario_loss", "portfolio_loss_pct", "max_portfolio_loss", "loss_pct"], "pct", None),
    ("Worst scenario", ["worst_scenario", "worst_scenario_name", "scenario", "trigger", "event_class"], "text", None),
    ("Scenarios tested", ["n_scenarios", "num_scenarios", "scenario_count", "shocks_applied", "scenarios"], "count", None),
]


def collect_metrics():
    a = load_json(MODULE_A_JSON)
    b = load_json(MODULE_B_JSON)
    cards_a = [(label, fmt_metric(find_metric(a, aliases, sections), kind))
               for label, aliases, kind, sections in METRICS_A]
    cards_b = [(label, fmt_metric(find_metric(b, aliases, sections), kind))
               for label, aliases, kind, sections in METRICS_B]
    # A metric counts as "real" if we found anything that isn't the em-dash.
    real_a = any(v != "—" for _, v in cards_a)
    real_b = any(v != "—" for _, v in cards_b)
    n_signals = count_signals()
    if n_signals is not None:
        real_a = real_b = True  # signals file alone is real pipeline output
        cards_a = [("Signals processed", f"{n_signals:,}")] + cards_a
    return cards_a, cards_b, (real_a or real_b)


# ---------------------------------------------------------------------------
# Deck construction (python-pptx)
# ---------------------------------------------------------------------------
try:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.enum.shapes import MSO_SHAPE
except ImportError:  # pragma: no cover
    print("ERROR: python-pptx is not installed. Run: pip install python-pptx",
          file=sys.stderr)
    sys.exit(1)

DARK_BG = RGBColor(0x0F, 0x17, 0x2A)
NAVY = RGBColor(0x1E, 0x3A, 0x8A)
TEAL = RGBColor(0x14, 0xB8, 0xA6)
INK = RGBColor(0x11, 0x18, 0x27)
MUTED = RGBColor(0x64, 0x74, 0x8B)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_BG = RGBColor(0xF8, 0xFA, 0xFC)
BORDER = RGBColor(0xE2, 0xE8, 0xF0)

FONT = "Calibri"
SW, SH = Inches(13.333), Inches(7.5)


def _bg(slide, color):
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def _textbox(slide, left, top, width, height):
    return slide.shapes.add_textbox(left, top, width, height)


def _para(tf, text, size, bold=False, color=INK, alignment=PP_ALIGN.LEFT,
          space_after=Pt(6)):
    p = tf.add_paragraph()
    p.text = text
    p.font.size = Pt(size)
    p.font.bold = bold
    p.font.color.rgb = color
    p.font.name = FONT
    p.alignment = alignment
    p.space_after = space_after
    p.level = 0
    return p


def _bullets(slide, left, top, width, height, items, size=18,
             bullet="▸ ", color=INK):
    tb = _textbox(slide, left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    first = True
    for item in items:
        if isinstance(item, tuple):
            head, rest = item
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            run = p.add_run()
            run.text = bullet + head
            run.font.size = Pt(size)
            run.font.bold = True
            run.font.color.rgb = color
            run.font.name = FONT
            run2 = p.add_run()
            run2.text = rest
            run2.font.size = Pt(size)
            run2.font.color.rgb = color
            run2.font.name = FONT
        else:
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            p.text = bullet + item
            p.font.size = Pt(size)
            p.font.color.rgb = color
            p.font.name = FONT
        p.space_after = Pt(10)
        p.level = 0
        first = False
    return tb


def _content_slide(prs, title, subtitle=None):
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # blank
    _bg(slide, WHITE)
    _textbox(slide, Inches(0.6), Inches(0.25), Inches(12.1), Inches(0.7)) \
        .text_frame.paragraphs[0].text = title
    tf = slide.shapes[-1].text_frame
    tf.paragraphs[0].font.size = Pt(30)
    tf.paragraphs[0].font.bold = True
    tf.paragraphs[0].font.color.rgb = NAVY
    tf.paragraphs[0].font.name = FONT
    # teal accent rule under the title
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                  Inches(0.6), Inches(0.95),
                                  Inches(1.4), Pt(5))
    rule.fill.solid()
    rule.fill.fore_color.rgb = TEAL
    rule.line.fill.background()
    if subtitle:
        tb = _textbox(slide, Inches(0.6), Inches(1.05), Inches(12.1), Inches(0.5))
        _para(tb.text_frame, subtitle, 15, color=MUTED)
    return slide


def _metric_card(slide, left, top, width, height, label, value):
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                  left, top, width, height)
    card.fill.solid()
    card.fill.fore_color.rgb = LIGHT_BG
    card.line.color.rgb = BORDER
    card.line.width = Pt(1.25)
    tb = _textbox(slide, left + Pt(10), top + Pt(8),
                  width - Pt(20), height - Pt(16))
    tf = tb.text_frame
    tf.word_wrap = True
    _para(tf, label, 13, color=MUTED, alignment=PP_ALIGN.CENTER,
          space_after=Pt(4))
    _para(tf, value, 26, bold=True, color=NAVY, alignment=PP_ALIGN.CENTER)


# ---------------------------------------------------------------------------
# Slides
# ---------------------------------------------------------------------------

def slide_title(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _bg(slide, DARK_BG)
    # thin teal top rule
    rule = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SW, Pt(8))
    rule.fill.solid()
    rule.fill.fore_color.rgb = TEAL
    rule.line.fill.background()

    tb = _textbox(slide, Inches(0.8), Inches(1.6), Inches(11.7), Inches(1.4))
    _para(tb.text_frame, "Sentinel", 54, bold=True, color=WHITE,
          alignment=PP_ALIGN.CENTER, space_after=Pt(2))
    tb = _textbox(slide, Inches(0.8), Inches(2.9), Inches(11.7), Inches(1.0))
    _para(tb.text_frame, "AI/NLP Risk Engine for Real-Time Market Risk",
          26, color=TEAL, alignment=PP_ALIGN.CENTER)
    tb = _textbox(slide, Inches(0.8), Inches(4.3), Inches(11.7), Inches(2.2))
    tf = tb.text_frame
    tf.word_wrap = True
    _para(tf, "S&P Global & Crisil Campus Hackathon 2026", 18,
          color=WHITE, alignment=PP_ALIGN.CENTER)
    _para(tf, "Krishna Kaushal  ·  MNNIT", 18, bold=True,
          color=WHITE, alignment=PP_ALIGN.CENTER)
    _para(tf, "October 2026", 15, color=MUTED, alignment=PP_ALIGN.CENTER)


def _section_col(slide, left, top, width, height, header, items, size=17):
    """One textbox holding a teal section header plus its bullet list,
    so the header can never collide with the bullets."""
    bullet = "▸ "
    tb = _textbox(slide, left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    p0 = tf.paragraphs[0]
    p0.text = header
    p0.font.size = Pt(14)
    p0.font.bold = True
    p0.font.color.rgb = TEAL
    p0.font.name = FONT
    p0.space_after = Pt(12)
    p0.level = 0
    for item in items:
        p = tf.add_paragraph()
        if isinstance(item, tuple):
            head, rest = item
            run = p.add_run()
            run.text = bullet + head
            run.font.size = Pt(size)
            run.font.bold = True
            run.font.color.rgb = INK
            run.font.name = FONT
            run2 = p.add_run()
            run2.text = rest
            run2.font.size = Pt(size)
            run2.font.color.rgb = INK
            run2.font.name = FONT
        else:
            p.text = bullet + item
            p.font.size = Pt(size)
            p.font.color.rgb = INK
            p.font.name = FONT
        p.space_after = Pt(10)
        p.level = 0
    return tb


def slide_problem(prs):
    slide = _content_slide(prs, "Problem & Approach")
    _section_col(slide, Inches(0.6), Inches(1.25), Inches(5.8), Inches(5.5),
                 "THE PROBLEM", [
        ("Risk desks drown in headlines. ",
         "Analysts can't read every wire, tweet, and filing intraday — material events get priced before they're read."),
        ("Sentiment alone isn't a signal. ",
         "A polarity score with no event type, no ticker linkage, and no impact estimate can't drive a portfolio decision."),
        ("Stress tests lag the news. ",
         "Scenario shocks are run quarterly on stale assumptions while the market reprices in minutes."),
    ], size=17)
    _section_col(slide, Inches(6.9), Inches(1.25), Inches(5.8), Inches(5.5),
                 "OUR APPROACH", [
        ("Three-stage NLP risk engine. ",
         "FinBERT-style sentiment → zero-shot event classification → impact scorer (magnitude × novelty × credibility)."),
        ("Ticker-linked signal store. ",
         "Every signal lands in signals.jsonl and a FastAPI layer (/signals, /analyze) — one contract for all consumers."),
        ("Two downstream modules. ",
         "(A) Index rebalancer tilts weights away from negative-risk names; (B) stress tester prices event-driven scenarios with loss attribution."),
    ], size=17)


def slide_design(prs):
    slide = _content_slide(prs, "System Design",
                           "Sources → Ingestion → NLP Risk Engine → Signal Store + API → Modules A/B → Dashboard")
    if ARCH_IMG.exists():
        # Fit the diagram into the remaining area, preserving aspect ratio.
        max_w, max_h = Inches(12.1), Inches(5.4)
        left, top = Inches(0.6), Inches(1.7)
        slide.shapes.add_picture(str(ARCH_IMG), left, top,
                                 width=max_w, height=max_h)
    else:
        tb = _textbox(slide, Inches(0.6), Inches(2.5), Inches(12.1), Inches(3))
        _para(tb.text_frame,
              "docs/architecture.png not found — generate it before building the deck.",
              18, color=MUTED, alignment=PP_ALIGN.CENTER)


def slide_implementation(prs):
    slide = _content_slide(prs, "Implementation Highlights")
    _bullets(slide, Inches(0.6), Inches(1.5), Inches(12.1), Inches(5.4), [
        ("Modular pipeline (risk_engine / module_a / module_b / api / dashboard). ",
         "Each stage is runnable standalone — `PYTHONPATH=src python -m risk_engine.pipeline --sources synthetic_social --limit 40`."),
        ("Zero-model default, real-model upgrade path. ",
         "VADER-style lexicon sentiment + heuristic event classifier run with no downloads; set RISK_ENGINE_BACKEND=hf with torch for FinBERT/zero-shot via transformers."),
        ("Keyless, offline-capable data. ",
         "GDELT 2.1 needs no API key; NewsAPI is optional; yfinance prices and the wholesale portfolio both have deterministic synthetic fallbacks."),
        ("Reproducible metrics pipeline. ",
         "Backtest and stress test write data/module_a_results.json / data/module_b_results.json — this deck is generated from those files."),
        ("Typed API + interactive dashboard. ",
         "FastAPI serves signals and ad-hoc analysis; Streamlit/Plotly renders weights, equity curves, and loss attribution."),
    ], size=17)


def slide_results(prs, cards_a, cards_b, has_real):
    slide = _content_slide(prs, "Key Results",
                           "Module A backtest vs. equal-weight baseline  ·  Module B event-driven stress test")
    if not has_real:
        tb = _textbox(slide, Inches(0.6), Inches(2.6), Inches(12.1), Inches(3))
        tf = tb.text_frame
        tf.word_wrap = True
        _para(tf, "Metrics populate after a full run:", 20, bold=True,
              color=NAVY, alignment=PP_ALIGN.CENTER)
        _para(tf, "PYTHONPATH=src python -m risk_engine.pipeline --sources synthetic_social --limit 40\n"
                  "PYTHONPATH=src python -m module_a.backtest\n"
                  "PYTHONPATH=src python -m module_b.stress_test\n"
                  "then re-run:  python3 docs/build_deck.py",
              16, color=MUTED, alignment=PP_ALIGN.CENTER)
        return

    # Section labels sit well clear of the cards below them.
    tb = _textbox(slide, Inches(0.6), Inches(1.40), Inches(12.1), Inches(0.35))
    _para(tb.text_frame, "MODULE A — INDEX REBALANCER", 14, bold=True, color=TEAL)
    cols, cw, chh = 4, Inches(2.85), Inches(1.30)
    gap = Inches(0.22)
    cards_top = Inches(2.15)
    for i, (label, value) in enumerate(cards_a[:8]):
        r, c = divmod(i, cols)
        _metric_card(slide, Inches(0.6) + c * (cw + gap),
                     cards_top + r * (chh + gap), cw, chh, label, value)

    n_rows_a = (min(len(cards_a), 8) + cols - 1) // cols
    base = cards_top + n_rows_a * (chh + gap) + Inches(0.30)
    tb = _textbox(slide, Inches(0.6), base, Inches(12.1), Inches(0.35))
    _para(tb.text_frame, "MODULE B — STRESS TESTER", 14, bold=True, color=TEAL)
    for i, (label, value) in enumerate(cards_b[:4]):
        _metric_card(slide, Inches(0.6) + i * (cw + gap), base + Inches(0.40),
                     cw, chh, label, value)


def slide_impact(prs):
    slide = _content_slide(prs, "Domain Impact",
                           "What a risk desk gains from Sentinel")
    _bullets(slide, Inches(0.6), Inches(1.6), Inches(12.1), Inches(5.2), [
        ("News-to-action in minutes, not hours. ",
         "Ticker-linked risk signals flow intraday — no analyst required to read every headline first."),
        ("Systematic de-risking. ",
         "Module A trims exposure to names under negative event pressure before clusters compound."),
        ("Board-ready worst cases. ",
         "Module B turns 'what if rates spike?' into a loss % with per-position attribution a CRO can defend."),
        ("Zero vendor lock-in. ",
         "Keyless feeds, offline fallbacks, laptop-grade compute — deployable on a desk or a free-tier cloud box."),
        ("Auditable by construction. ",
         "Every signal, weight, and scenario result is a JSON artifact — reproducible and inspectable."),
    ], size=19)


def slide_next(prs):
    slide = _content_slide(prs, "Limitations & Next Steps")
    _section_col(slide, Inches(0.6), Inches(1.25), Inches(5.8), Inches(5.0),
                 "LIMITATIONS", [
        "Backtests ignore transaction costs and slippage.",
        "Entity→ticker mapping covers a fixed large-cap watchlist.",
        "Synthetic samples model headline structure, not market outcomes.",
        "Free-tier feeds can lag; no streaming WebSocket yet.",
    ], size=17)
    _section_col(slide, Inches(6.9), Inches(1.25), Inches(5.8), Inches(5.0),
                 "NEXT STEPS", [
        "Fine-tune FinBERT on finance headlines; add multilingual ingestion.",
        "Live WebSocket push for breaking-signal alerts.",
        "Transaction-cost-aware rebalancing and turnover penalties.",
        "Expand scenario library (credit, liquidity, climate) with regulator templates.",
    ], size=17)
    # closing line
    tb = _textbox(slide, Inches(0.6), Inches(6.6), Inches(12.1), Inches(0.5))
    _para(tb.text_frame, "Sentinel — real-time NLP risk signals, risk-tilted rebalancing, event-driven stress testing.",
          15, bold=True, color=NAVY, alignment=PP_ALIGN.CENTER)


# ---------------------------------------------------------------------------
# PDF conversion
# ---------------------------------------------------------------------------

def convert_to_pdf() -> bool:
    """Convert the pptx to PDF via LibreOffice if available. Never raises."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        print("LibreOffice not found — skipping PDF conversion "
              "(docs/presentation.pptx was still written).")
        return False
    try:
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf",
             "--outdir", str(DOCS), str(PPTX_OUT)],
            check=True, capture_output=True, text=True, timeout=180)
    except (subprocess.SubprocessError, OSError) as exc:
        print(f"PDF conversion failed ({exc}) — pptx is still available.")
        return False
    if PDF_OUT.exists():
        print(f"Wrote {PDF_OUT} ({PDF_OUT.stat().st_size // 1024} KB)")
        return True
    print("PDF conversion reported success but no PDF found.")
    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    DOCS.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    cards_a, cards_b, has_real = collect_metrics()
    if has_real:
        print("Using real metrics from data/*.json")
    else:
        print("No result JSONs found — results slide will carry placeholders.")

    prs = Presentation()
    prs.slide_width = SW
    prs.slide_height = SH

    slide_title(prs)                       # 1
    slide_problem(prs)                     # 2
    slide_design(prs)                      # 3
    slide_implementation(prs)              # 4
    slide_results(prs, cards_a, cards_b, has_real)  # 5
    slide_impact(prs)                      # 6
    slide_next(prs)                        # 7

    assert len(prs.slides) == 7, f"expected 7 slides, got {len(prs.slides)}"
    prs.save(PPTX_OUT)
    print(f"Wrote {PPTX_OUT} ({PPTX_OUT.stat().st_size // 1024} KB, "
          f"{len(prs.slides)} slides)")

    convert_to_pdf()
    return 0


if __name__ == "__main__":
    sys.exit(main())
