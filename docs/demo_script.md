# Sentinel — 10-Minute Demo Script

Target length: **10:00**. Record as one continuous screen capture (OBS / QuickTime) with voiceover; edit only for dead air. All commands below assume you start in the repo root with `requirements.txt` installed and Python 3.10+.

---

## Pre-recording checklist

- [ ] `pip install -r requirements.txt` completed cleanly; `python -c "import streamlit, fastapi, yfinance"` succeeds.
- [ ] Repo is the **public** submission repo; no API keys, tokens, or personal paths in the terminal history or files. (`NEWSAPI_KEY` unset — we demo the graceful fallback.)
- [ ] Delete stale outputs so the run is live on camera: `rm -f data/signals.jsonl data/module_a_results.json data/module_b_results.json`
- [ ] Terminal font ≥ 16pt, window maximised; browser zoom 110–125%.
- [ ] Streamlit dashboard opens cleanly once: `PYTHONPATH=src streamlit run src/dashboard/app.py` → loads at `http://localhost:8501` (then close it; you'll relaunch on camera).
- [ ] FastAPI port 8000 free (`lsof -ti:8000 | xargs kill -9` if needed).
- [ ] Internet available for the GDELT/yfinance live path — but be ready to narrate the synthetic fallback if the network drops (it is a *feature*: "graceful degradation").
- [ ] Do Not Disturb on; notifications off; mic levels tested.
- [ ] Water nearby. Breathe.

---

## Shot 1 — Intro (0:00–0:30)

**On screen:** Title card or README.md open in the browser (rendered GitHub view).

**Say:**

> "I'm Krishna Kaushal from MNNIT. This is **Sentinel** — a real-time AI/NLP risk engine built for the S&P Global and Crisil Campus Hackathon.
> It reads financial news and social chatter as it happens, turns it into structured risk signals — sentiment, event type, and impact per ticker — and feeds two downstream modules: an index rebalancer and a portfolio stress tester.
> Everything you're about to see runs live, on a laptop, with no API keys and no GPU."

**Do:** nothing typed; slow scroll of the README header → architecture section.

---

## Shot 2 — Setup & install (0:30–1:00)

**On screen:** fresh terminal, repo root.

**Type:**

```bash
pip install -r requirements.txt
```

**Say (while it runs; trim in edit if slow):**

> "One install, Python 3.10 plus. The heavy NLP models are optional — by default Sentinel runs on lightweight fallback backends, so the whole demo works offline. If you want real FinBERT, it's one pip install and one environment variable — details are in requirements.txt."

**Do:** `ls src data docs` to show the repo layout briefly.

---

## Shot 3 — Risk engine live: ingest → signals (1:00–2:30)

**On screen:** terminal.

**Type:**

```bash
PYTHONPATH=src python -m risk_engine.pipeline --sources synthetic_social --limit 40
```

**Say:**

> "First, the risk engine. I'm running it on forty bundled synthetic social samples — clearly labeled synthetic, so the demo is reproducible offline.
> In production this same command pulls GDELT's fifteen-minute live news feed — no API key needed — plus NewsAPI if you have a key.
> Watch the three stages per item: sentiment scoring, zero-shot event classification — earnings, macro, ESG, geo-risk — and an impact score combining magnitude, novelty, and source credibility."

**Do:** when it finishes, `head -c 1200 data/signals.jsonl` — point at the JSON fields: `sentiment`, `event_type`, `impact`, `tickers`.

**Say:**

> "Every signal lands in signals.jsonl — this append-only file is the contract everything downstream consumes."

---

## Shot 4 — Signals API (2:30–4:00)

**On screen:** terminal (start API in background) + second terminal or `curl`.

**Type:**

```bash
PYTHONPATH=src uvicorn api.main:app --port 8000 &
sleep 3
curl -s "http://localhost:8000/signals?limit=3" | python -m json.tool | head -40
```

**Say:**

> "The signals are served over FastAPI. Here's the live signal store — same JSON contract.
> And the analyze endpoint scores arbitrary text on the fly:"

**Type:**

```bash
curl -s -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"text": "Central bank surprises with an emergency 75 bps rate hike as inflation spikes"}' \
  | python -m json.tool
```

**Say:**

> "Negative sentiment, macro event, high impact — in under a second. Any risk system can poll this endpoint or push to it."

**Do:** leave the API running for the dashboard segment (or kill it after; the dashboard reads the JSONL directly — say so).

---

## Shot 5 — Module A: index rebalancer (4:00–6:30)

**On screen:** terminal, then Streamlit dashboard in browser.

**Type:**

```bash
PYTHONPATH=src python -m module_a.backtest
cat data/module_a_results.json | python -m json.tool
```

**Say:**

> "Module A takes the risk signals and tilts index weights *away* from names under negative risk pressure, then backtests the tilt against an equal-weight baseline.
> Prices come from yfinance, with a deterministic synthetic fallback if we're offline — reproducibility first."

**Do:** open `http://localhost:8501` (launch Streamlit now if not running: `PYTHONPATH=src streamlit run src/dashboard/app.py`). Navigate to the Module A view.

**Say (pointing at the dashboard):**

> "Here are the risk-tilted weights versus baseline — note how the stressed names get cut.
> And the equity curves: cumulative return and Sharpe for the tilted portfolio against the baseline, plus turnover and max drawdown.
> The point isn't beating the market every quarter — it's *systematically de-risking* ahead of negative event clusters, intraday, without an analyst in the loop."

---

## Shot 6 — Module B: stress tester (6:30–8:30)

**On screen:** terminal, then dashboard Module B view.

**Type:**

```bash
PYTHONPATH=src python -m module_b.stress_test
cat data/module_b_results.json | python -m json.tool
```

**Say:**

> "Module B answers the risk committee's favorite question: *what breaks, and by how much?*
> It takes event-driven scenarios — rate shock, earnings miss cluster, geopolitical flare-up — applies them to a synthetic wholesale portfolio, and reports portfolio loss percent per scenario."

**Do:** switch to the Module B dashboard view.

**Say (pointing):**

> "Pick a scenario — here's the trigger event, the before-and-after portfolio value, and the attribution: which positions and which risk factors drive the loss.
> This is the bridge from NLP signals to a number a CRO can put in a board pack."

---

## Shot 7 — Results & domain impact (8:30–9:30)

**On screen:** dashboard overview or the results JSONs side by side; then the architecture diagram.

**Say:**

> "So, end to end: raw headlines in, structured signals out — sentiment, event, impact per ticker — consumed by a rebalancer that de-risks systematically and a stress tester that prices the worst case.
> For a risk desk, that compresses the news-to-action loop from hours to minutes, on a laptop, with no data-vendor contract and no GPU.
> All metrics you saw are written to `data/module_a_results.json` and `data/module_b_results.json` — reproducible, auditable, and they're what generate the slide deck automatically via `docs/build_deck.py`."

**Do:** briefly show `docs/architecture.png` full-screen as the visual summary.

---

## Shot 8 — Close (9:30–10:00)

**On screen:** title card / README header.

**Say:**

> "Sentinel: real-time NLP risk signals, a risk-tilted index rebalance, and event-driven stress testing — one pipeline, fully open, fully reproducible.
> I'm Krishna Kaushal, MNNIT — code, deck, and demo are linked below. Thank you."

**Do:** stop recording. Upload as **unlisted** to YouTube; paste the link into the README header ("Demo Video Link").

---

## If something goes wrong live (don't re-record — narrate it)

| Failure | Line to say |
|---|---|
| GDELT unreachable | "The live feed is down — watch the pipeline degrade gracefully to bundled samples instead of crashing. That's the designed behavior." |
| yfinance blocked | "No market data connection — the deterministic synthetic price fallback keeps the backtest reproducible." |
| Port 8000 busy | "Port's taken — one sec," then `lsof -ti:8000 \| xargs kill -9` and relaunch. |
| Streamlit slow to load | Talk over the spinner: "First load compiles the dashboard — the data's already computed." |
