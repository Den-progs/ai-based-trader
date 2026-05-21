# AI Trader Bot — Project Rules

## What this is
A paper-trading bot built by two friends (Mac + Windows). Uses Alpaca for
stocks + crypto, local Llama 3.2 (via Ollama) for fast decisions, and Claude
API once a day to review trades and pick a watchlist. Sends Discord
notifications for every trade.

## Hard rules — never break these
- **NEVER use real money.** Alpaca client must always have `paper=True` unless
  a `LIVE_TRADING=true` env var is set AND `CONFIRM_LIVE=YES_I_MEAN_IT` is set.
  Both required. Default everywhere is paper.
- **Never commit secrets.** Anything sensitive goes in `.env`, which is in
  `.gitignore`.
- **Cross-platform.** Code must work on Mac and Windows. Use `pathlib.Path`,
  never hardcode `/` or `\`. Use `python-dotenv` for env vars.
- **No silent failures.** Wrap API calls in try/except and log errors to
  Discord + console.

## Code style
- Keep it SIMPLE. We're learning. Prefer readable over clever.
- Comment any non-obvious logic in plain English.
- One responsibility per file. Don't make one giant `main.py`.
- Type hints where they help, not everywhere.
- No new dependencies without asking — keep the requirements list short.

## Architecture
- `main.py` — trading loop, runs every 30s
- `daily_coach.py` — runs once a day, Claude reviews + picks watchlist
- `discord_notify.py` — sends webhook messages
- `trader.py` — Alpaca wrappers (buy, sell, get position)
- `llama_brain.py` — Ollama prompts + decision parsing
- `news.py` — Alpaca news API wrapper
- `coach_io.py` — reads/writes strategy.txt + watchlist.json
- `config.py` — all settings in one place (loop interval, qty, etc.)

## What's done
- Repo created, venv set up, packages installed
- `.env` and `.gitignore` exist
- Ollama installed with llama3.2:3b

## What's next (in order)
1. Build `trader.py` with paper-mode-only Alpaca wrappers
2. Build `discord_notify.py` and test webhook works
3. Build `llama_brain.py` and test it returns valid JSON
4. Wire it all together in `main.py`
5. Then `daily_coach.py` with Claude API
6. Then add news context

## Don't do yet
- Multiple exchanges (Binance, Coinbase, etc.) — Alpaca only for v1
- Real money trading — paper only until we're confident
- Fancy UI / web dashboard — Discord is enough for now
- Backtesting — later, after live paper works