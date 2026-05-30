# TrumpTruthTrading

An automated pipeline that monitors Donald Trump's Truth Social account in real time, uses Claude (Anthropic LLM) to analyze each post for market-moving signals, and executes trades on Alpaca based on high-confidence findings.

Runs entirely on **GitHub Actions** (free tier on public repos) — no server required.

---

## How It Works

```
Truth Social (every 5 min)
        |
        v
  New post detected?
        |
       YES
        |
        v
  Claude analyzes post
  - Is a specific company/sector mentioned?
  - Is the sentiment clearly positive or negative?
  - Confidence: HIGH / MEDIUM / LOW
  + Past performance context injected
        |
   HIGH confidence only
        |
        v
  Market open? + Under position limit?
        |
       YES
        |
        v
  Alpaca bracket order placed
  (5% of buying power, 15% TP, 5% SL)
        |
        v
  Outcome tracked → feeds back into
  next LLM analysis as performance context
```

---

## Features

- **Real-time polling** — Truth Social checked every 5 minutes via GitHub Actions cron
- **LLM signal extraction** — Claude evaluates each post against strict criteria; only direct, explicit company/sector mentions reach HIGH confidence
- **Conservative trading** — 5% position sizing, bracket orders with automatic 15% take-profit and 5% stop-loss
- **Automated learning** — closed trade outcomes (TP/SL hit, PnL%) are fed back into Claude's prompt so it calibrates confidence over time
- **Full audit trail** — every post analyzed and every trade placed is logged to `data/posts_log.csv` and `data/trades.csv`, committed back to this repo after each run
- **Zero infrastructure cost** — runs entirely on GitHub Actions; only cost is Anthropic API calls (~$0.01–0.05/day)

---

## Pipeline Files

| File | Purpose |
|---|---|
| `main.py` | Orchestrator — `--once` for CI, loops for local |
| `scraper.py` | Truth Social API polling, HTML stripping, state management |
| `analyzer.py` | Claude LLM prompt + signal parsing |
| `trader.py` | Alpaca order execution |
| `trade_tracker.py` | Record trades, check bracket order outcomes, build performance context |
| `alpaca_client.py` | Shared Alpaca client singleton |
| `config.py` | All tunable settings |

---

## Data Files (auto-updated by Actions)

| File | Contents |
|---|---|
| `data/last_post_id.txt` | Most recently processed Truth Social post ID |
| `data/trump_id.txt` | Cached Truth Social account ID (resolved once) |
| `data/posts_log.csv` | Every post seen: text preview, signal, confidence, tickers, whether a trade was placed |
| `data/trades.csv` | Every trade placed: entry/exit price, PnL%, outcome (TP_HIT / SL_HIT) |

---

## Trading Rules

Claude only triggers a trade when **all** of these are true:

1. Trump directly names a specific public company or sector by name
2. Sentiment is unambiguously positive (BUY) or negative (SELL)
3. Confidence is rated **HIGH** by the LLM
4. US stock market is currently open
5. Fewer than 3 concurrent positions are open from this pipeline

Examples that **do** trade:
- *"I love what Tesla is doing for American manufacturing"* → BUY TSLA
- *"Amazon is ripping off small businesses, we're going after them"* → SELL AMZN

Examples that **do not** trade:
- General tariff announcements without naming a company
- Political attacks on individuals
- Vague patriotism / economy commentary

---

## Performance Learning

After 3+ closed trades, Claude receives a context block before each analysis:

```
PAST TRADING PERFORMANCE (use to calibrate your confidence):
• 12 closed trades | Win rate: 67% | Avg win: +8.4% | Avg loss: -4.9%
• BUY trades won: 7/9 (78%) | SELL trades won: 1/3 (33%)
• Recent (newest first): TSLA BUY +12.1%✓ | FXI SELL -4.9%✗ | AAPL BUY +7.2%✓
```

This lets the model raise or lower its bar dynamically based on what has actually been working.

---

## Setup (run locally or fork)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure API keys
```bash
cp .env.example .env
# Edit .env with your keys
```

Required keys:
- `ANTHROPIC_API_KEY` — [console.anthropic.com](https://console.anthropic.com)
- `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` — [alpaca.markets](https://alpaca.markets) (paper trading by default)

### 3. Run locally
```bash
# Continuous loop (local use)
python main.py

# Single pass and exit (same as GitHub Actions)
python main.py --once
```

---

## GitHub Actions (free, zero server)

The workflow at `.github/workflows/poll.yml` runs on a `*/5 * * * *` cron (every 5 minutes).

To deploy your own copy:

1. Fork this repo (must be **public** for unlimited Actions minutes)
2. Add three repository secrets under **Settings → Secrets and variables → Actions**:
   - `ANTHROPIC_API_KEY`
   - `ALPACA_API_KEY`
   - `ALPACA_SECRET_KEY`
3. The workflow activates automatically — no further setup needed

After each run the workflow commits updated `data/` files back to the repo with `[skip ci]` so the commit doesn't retrigger the workflow.

---

## Configuration

All tunable parameters are in `config.py`:

| Setting | Default | Description |
|---|---|---|
| `POLL_INTERVAL_SECONDS` | 120 | Local loop poll frequency |
| `POSITION_SIZE_PCT` | 0.05 | Fraction of buying power per trade |
| `STOP_LOSS_PCT` | 0.05 | Stop-loss distance from entry |
| `TAKE_PROFIT_PCT` | 0.15 | Take-profit distance from entry |
| `MAX_POSITIONS` | 3 | Max concurrent open positions |
| `CLAUDE_MODEL` | claude-sonnet-4-6 | LLM model for analysis |
| `ALPACA_PAPER` | true | Paper vs live trading |

---

## Disclaimer

This project is for educational and research purposes. It trades on paper by default (`ALPACA_PAPER=true`). Past performance of any automated system does not guarantee future results. Do not trade with money you cannot afford to lose.
