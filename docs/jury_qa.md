# Sentinel — Jury Q&A Drill

Read these cold before the pitch. Every number below is the **real output** of your
pipeline (`data/module_a_results.json`, `data/module_b_results.json`). The jury will
attack the weakest numbers — that's where the answers below are honest, not defensive.

## The numbers you must have memorised

- **Module A:** 15 tickers (AAPL, MSFT, NVDA, AMZN, META, GOOGL, AVGO, TSLA, JPM, V,
  XOM, UNH, MA, PG, HD) · 2026-04-01 → 2026-10-01 (6 months) · yfinance prices
  · 35 signals consumed · daily rebalance at close.
  - Risk-tilted: **+17.93%** cumulative, **Sharpe 2.66**, max DD **5.43%**, turnover **82.8%/yr**
  - Equal-weight baseline: **+18.02%**, Sharpe 2.68, max DD 5.43%, turnover 0
  - Tilt rule: r_i = clip(1 + 2.0 · s_i, 0, 2), s_i = trailing-5-day mean sentiment (−1..1),
    long-only, fully invested, **no transaction costs**
- **Module B:** Geopolitical-9 trigger → **$3,015.5M → $2,222.9M = −26.28% (−$792.59M)**
  - Attribution: bonds −$449.47M, loans −$260.71M, derivatives −$82.4M
  - Shocks: equities −10%, rates +200 bps, credit spreads +150 bps · 30 synthetic positions
- **Risk engine:** 40 signals · sentiment = finance-tuned VADER (−1..1) · event class =
  keyword rules (Earnings/Macro/ESG/Geopolitical) · impact = magnitude × novelty × credibility
  (sentiment_term + severity_term + corroboration_term) · optional HF backends (FinBERT/BART)
  behind an env var · sources: GDELT 15-min live feed (no key), NewsAPI (optional),
  bundled synthetic fallback · FastAPI: `/signals` + `/analyze`

---

## Likely questions and answers

**1. "Your Module A doesn't beat the baseline. Why should we care?"**
> It doesn't, on raw return — and we reported it honestly rather than tuning until it did.
> The thesis is *systematic de-risking ahead of negative event clusters*, not alpha.
> In 6 months with 35 signals, the tilt kept pace with equal-weight (+17.93% vs +18.02%)
> while cutting exposure to stressed names daily. The interesting test is a longer window
> with an event-heavy sample, and a cost-aware version — both are the stated next steps.

**2. "82.8% annualised turnover with no transaction costs — isn't that flattering the result?"**
> Yes, and it's disclosed. Turnover is reported precisely so you can haircut it yourself:
> every 10 bps of round-trip cost would cost roughly 8 bps/year at this turnover —
> small against a ~18% six-month return, but real. A cost-aware rebalancer is the first
> thing we'd ship next.

**3. "n = 35 signals. Is that statistically meaningful?"**
> No, and we don't claim it is. 35 is what the reproducible offline sample produces.
> The live GDELT path ingests continuously, so the sample scales; the demo uses synthetic
> data so a jury can rerun the exact same numbers. Reproducibility first, sample size second.

**4. "How is this better than a human analyst reading the news?"**
> It isn't better *judgment* — it's latency and consistency. A desk analyst reads hundreds
> of items a day with delay and bias; this scores every item the same way, writes it to an
> append-only contract (`signals.jsonl`) any downstream system can consume, and serves
> it over an API in under a second. The analyst moves up to interpreting the signal.

**5. "Sarcasm, rumours, adversarial headlines — won't your lexicon choke?"**
> VADER's valence plus finance lexicon tweaks handles tone poorly; we don't hide that.
> The impact score's *corroboration term* and *source credibility* exist exactly to
> down-weight single noisy items, and the HF backend (FinBERT + zero-shot BART) is the
> upgrade path — one pip install, one env var. Heuristics ship first; models swap in.

**6. "Your demo runs on synthetic data. Does it work on real news?"**
> The ingest path is identical — `python -m risk_engine.pipeline` without `--sources`
> pulls GDELT's live 15-minute feed. Synthetic is a demo choice for reproducibility
> (and for the jury to rerun it), not an architecture limit.

**7. "In Module B, why did bonds lose the most?"**
> Because the scenario is rates-led: +200 bps against a $1,267.6M bond book with real
> duration exposure — bonds took $449.47M of the $792.59M loss. Loans were next at
> $260.71M on spread widening. The attribution is the point: a CRO sees *which* book
> drives the loss, not just the −26.28%.

**8. "Event-driven stress tests are only as good as the scenario. Where do yours come from?"**
> Currently they're parameterized scenarios (rate shock, earnings-miss cluster, geo flare-up)
> keyed to event classes. The real design is closed-loop: an impact-9 Geopolitical signal
> from the engine should *auto-instantiate* a scenario and price it — that's the roadmap,
> and the `trigger.signal_id` field in `module_b_results.json` is already reserved for it.

**9. "How do you avoid lookahead bias in the backtest?"**
> Sentiment s_i is the trailing-5-calendar-day mean ending the day *before* the rebalance
> bar; rebalance executes at close on that signal only. Tickers default to s_i = 0
> (no signal → neutral weight) rather than being dropped, so there's no survivorship tilt.

**10. "What would you do with three more months?"**
> Cost-aware rebalancing (turnover penalty in the tilt), a live GDELT evaluation window
> with recorded precision on event classification, and closing the loop from Module B:
> engine signals auto-spawning stress scenarios. Then position sizing instead of a
> fixed 15-name universe.

**11. "Who buys this?"**
> Risk desks that can't afford a Bloomberg-class contract, wealth managers who want a
> explainable overlay, and compliance teams that need an audit trail — every number
> we show is written to a JSON file you can diff. That's the differentiator against
> black-box sentiment APIs: auditable, reproducible, runs on a laptop.

**12. "What breaks if GDELT goes down during the demo?"**
> Nothing — the pipeline degrades to bundled samples by design and says so on camera.
> That's a feature of the pitch: graceful degradation is the story.

## Delivery rules

- Never round the honest numbers up: say "+17.93% vs +18.02%", not "about 18%".
- When attacked on a weakness, concede first, then pivot to what the number *does* show.
- The deck was built from these exact JSONs via `docs/build_deck.py` — if a number in
  the slides differs from this page, this page wins; regenerate the deck.
