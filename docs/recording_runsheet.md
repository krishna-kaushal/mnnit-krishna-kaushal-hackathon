# Sentinel — Recording Run-Sheet

*Prepared 2026-10-06 from [docs/demo_script.md](demo_script.md). Hard target: 10:00 on the stopwatch. Print this, prop it under your monitor, and glance at the minute marks.*

## Before you hit record (5 min)

- [ ] `pip install -r requirements.txt` clean; `python -c "import streamlit, fastapi, yfinance"` works
- [ ] `rm -f data/signals.jsonl data/module_a_results.json data/module_b_results.json` (fresh outputs on camera)
- [ ] `PYTHONPATH=src streamlit run src/dashboard/app.py` loads once, then close it
- [ ] Port 8000 free; terminal ≥16pt; browser zoom 110–125%
- [ ] Do Not Disturb on; mic tested; `NEWSAPI_KEY` unset; water nearby

## Cue cards — watch the clock, not the words

| Stopwatch | Shot | On screen | Say / do | Guardrail |
|---|---|---|---|---|
| 0:00 | Intro | README rendered in browser, slow scroll | ~85 words: who you are, what Sentinel is, 3 outputs per signal, 2 modules, "runs live, no API keys, no GPU" | **Do not improvise here.** Read it straight. |
| 0:30 | Install | Fresh terminal | `pip install -r requirements.txt`; while it runs: one install, lightweight fallbacks, FinBERT optional | If pip is slow: "install trimmed in edit" and **move on at 1:00** |
| 1:00 | Risk engine | Terminal | `PYTHONPATH=src python -m risk_engine.pipeline --sources synthetic_social --limit 40`; narrate the 3 stages per item; `head -c 1200 data/signals.jsonl` → point at `sentiment`, `event_type`, `impact`, `tickers` | **This is the shot the jury remembers. If you're behind, cut the install segment, not this.** Leave at 2:30 no matter what |
| 2:30 | API | Terminal + curl | `uvicorn api.main:app --port 8000 &` → `curl .../signals?limit=3`; POST the rate-hike line, read the response: "negative sentiment, macro event, high impact — under a second" | Skip the second curl if behind; signals GET alone sells it |
| 4:00 | Module A | Terminal → Streamlit | `PYTHONPATH=src python -m module_a.backtest`; open dashboard Module A view; point at tilted vs baseline weights, equity curves, Sharpe/turnover/max-DD | Say the line: "de-risking ahead of negative event clusters, intraday, no analyst in the loop" |
| 6:30 | Module B | Terminal → dashboard | `PYTHONPATH=src python -m module_b.stress_test`; dashboard Module B view; before/after portfolio value + attribution | One scenario only. Two scenarios = you run long |
| 8:30 | Impact | Results JSONs / architecture.png | News-to-action loop: hours → minutes; no vendor contract, no GPU; numbers in the JSONs are auditable and generate the deck via `docs/build_deck.py` | architecture.png full-screen = visual close of this shot |
| 9:30 | Close | Title card / README header | "Sentinel: real-time NLP risk signals, risk-tilted rebalance, event-driven stress testing — one pipeline, fully open, fully reproducible. I'm Krishna Kaushal, MNNIT. Code, deck, demo linked below. Thank you." | End **before** 10:00. Stop recording. |

## If behind the clock

| Behind by | Cut |
|---|---|
| ~30s | The install narration (0:30–1:00) |
| ~60s | The second API curl (analyze endpoint) |
| ~90s | Module B second scenario; keep one |

## If something breaks on camera — narrate, don't re-record

| Failure | Say this |
|---|---|
| GDELT unreachable | "The live feed is down — watch it degrade gracefully to bundled samples instead of crashing. That's the designed behavior." |
| yfinance blocked | "No market data connection — the deterministic synthetic price fallback keeps the backtest reproducible." |
| Port 8000 busy | "Port's taken — one sec," → `lsof -ti:8000 \| xargs kill -9`, relaunch |
| Streamlit slow | Talk over the spinner: "First load compiles the dashboard — the data's already computed." |

## After recording (10 min)

1. Export as unlisted on YouTube
2. Paste the link into README.md line 3 (`Demo Video Link:`)
3. Live market data rolls daily, so on-camera Module A numbers may read higher than the deck's Oct-1 figures: run `python docs/build_deck.py` to regenerate the deck from the fresh JSONs, and push the regenerated `docs/presentation.pdf` together with the README link. (jury_qa.md figures are Oct-1 vintage — skim for drift before the pitch.)
4. `git add README.md docs/presentation.pdf` → tell me and I'll push it
