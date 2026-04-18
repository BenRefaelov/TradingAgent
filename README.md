# Trading Agent — Technical Edge Playbook V23

Automated technical analysis agent that scans a watchlist of stocks and crypto
assets 3–4 times per day, builds evidence-based trade theses, tracks them over
time, and delivers Hebrew-language push notifications to Telegram.

**Total infrastructure cost: $0/month.**

---

## How it works

```
GitHub Actions (cron)
   │
   ├─ fetch OHLCV  ──── yfinance (stocks) / ccxt/Binance (crypto)
   │
   ├─ Phase A ─ 5 pre-signal detectors
   │   Higher Low · Bullish Divergence · Reversal Candle · VSA Climax · SMA Curl Up
   │
   ├─ Phase B ─ 6 confluence checks
   │   SMA150 · SMA200 · Fibonacci · Volume · Gap · RSI Oversold
   │
   ├─ Score → Recommendation: BUY / WATCH / DCA / AVOID
   │
   ├─ Supabase (PostgreSQL) ── persist theses + scan logs
   │
   └─ Telegram ── push alerts (new BUY, status change, scan summary)
```

---

## Scoring thresholds

| Signal | Phase A | Phase B | Trend    |
|--------|---------|---------|----------|
| BUY    | ≥ 3/5   | ≥ 4/6   | BULLISH  |
| WATCH  | ≥ 2/5   | ≥ 3/6   | any      |
| DCA    | any     | ≥ 2/6   | RSI < 35 |
| AVOID  | < 2/5   | < 2/6   | BEARISH  |

---

## Project structure

```
trading-agent/
├── .github/workflows/scan.yml   GitHub Actions — 4 cron triggers
├── src/
│   ├── main.py                  Entry point & scan orchestrator
│   ├── analyzer.py              Technical analysis engine (Phase A + B)
│   ├── thesis_engine.py         Supabase thesis lifecycle (create/monitor/log)
│   └── notifier.py              Telegram push notifications (Hebrew, HTML)
├── supabase/
│   └── schema.sql               One-time DB setup (3 tables + indexes + seed)
├── requirements.txt
├── test_single.py               Offline single-ticker smoke test
└── SETUP.md                     Step-by-step deployment guide
```

---

## Tech stack

| Layer         | Technology                | Cost  |
|---------------|---------------------------|-------|
| Scheduler     | GitHub Actions (cron)     | $0    |
| Database      | Supabase (PostgreSQL)     | $0    |
| Notifications | Telegram Bot (push only)  | $0    |
| Data — stocks | yfinance (Yahoo Finance)  | $0    |
| Data — crypto | ccxt / Binance public API | $0    |
| LLM (optional)| Gemini Flash API          | $0    |

---

## Quick start

See [SETUP.md](SETUP.md) for full step-by-step instructions.

```bash
# Local smoke test — no credentials needed
pip install -r requirements.txt
python test_single.py NVDA stock
python test_single.py BTC  crypto
```

---

## Scan schedule

| UTC   | Israel (summer) | Coverage          |
|-------|-----------------|-------------------|
| 13:45 | 16:45           | stocks + crypto   |
| 17:00 | 20:00           | stocks + crypto   |
| 19:30 | 22:30           | stocks + crypto   |
| 03:00 | 06:00           | crypto only (7d)  |

~270 GitHub Actions minutes/month out of the 2,000 free.

---

## Database tables

- **watchlist** — tickers to scan (add/disable without touching code)
- **theses** — one active thesis per ticker; auto-updated on score improvement
- **scan_log** — immutable append-only log of every scan result (JSONB raw data)

The schema is forward-compatible with a future Next.js / React Native dashboard
reading directly from the same Supabase project.
