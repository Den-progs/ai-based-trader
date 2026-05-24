# AI Trader Bot - Project Rules

## What this is
A paper-trading bot built by two friends (Mac + Windows). Trades US stocks
(NYSE/NASDAQ, market hours only) and crypto (24/7) via Alpaca. Uses local
Llama 3.2:3b (via Ollama) for fast per-symbol BUY/SELL/HOLD decisions every
30 seconds, and Claude Code CLI once a day to review trades, update the
strategy, and refresh the watchlists. Sends Discord notifications on every
trade and error.

## Hard rules - never break these
- **NEVER use real money.** Alpaca client must always have `paper=True` unless
  both `LIVE_TRADING=true` AND `CONFIRM_LIVE=YES_I_MEAN_IT` env vars are set.
  Default everywhere is paper.
- **Never commit secrets.** Anything sensitive goes in `.env`, which is in
  `.gitignore`.
- **Cross-platform.** Code must work on Mac and Windows. Use `pathlib.Path`,
  never hardcode `/` or `\`. Use `python-dotenv` for env vars.
- **No silent failures.** Wrap API calls in try/except and log errors to
  Discord + console.
- **Risk controls are non-negotiable.** Every position is protected by
  TAKE_PROFIT_PCT and STOP_LOSS_PCT auto-exits. Never remove or weaken these
  without explicit discussion - they are the only thing standing between the
  bot and unbounded losses.

## Code style
- Keep it SIMPLE. We're learning. Prefer readable over clever.
- Comment any non-obvious logic in plain English.
- One responsibility per file. Don't make one giant `main.py`.
- Type hints where they help, not everywhere.
- No new dependencies without asking - keep the requirements list short.

## Architecture
- `main.py` - trading loop, every `LOOP_INTERVAL` seconds. Threaded across
  `THREAD_WORKERS` workers. Runs stock cycle (skipped off-hours, signals
  saved instead) + crypto cycle (24/7). Handles take-profit, stop-loss,
  cash rebalancing, EOD liquidation.
- `daily_coach.py` - runs once a day (manual or scheduled via cron / Task
  Scheduler). Uses Claude Code CLI (`claude -p`) - no `ANTHROPIC_API_KEY`
  needed. Reviews last 7 days of trades + off-hours signals + news, writes
  new strategy and watchlists.
- `discord_notify.py` - sends webhook messages. Silent skip if URL missing.
- `trader.py` - Alpaca wrappers: buy, sell, get_position, get_position_pl,
  get_position_pl_pct, get_account_cash, get_stock_positions_by_pl,
  get_all_positions, is_market_open, is_near_close, close_all_stock_positions.
- `llama_brain.py` - Ollama HTTP call + JSON parsing with truncation recovery.
- `news.py` - parallel Alpaca + Google News RSS fetch, 5-min per-symbol cache.
- `coach_io.py` - reads/writes strategy.txt, watchlist.json,
  crypto_watchlist.json, pending_signals.json, last_buy.json. Thread-safe
  signal append.
- `config.py` - all tunables in one place.

## Risk controls (all configurable in `config.py`)
- **TAKE_PROFIT_PCT** - auto-sell winning positions at +X% (default 5%).
  Bypasses Llama. Scales correctly across position sizes since it's relative.
- **STOP_LOSS_PCT** - auto-sell losing positions at -X% (default 3%).
  Bypasses Llama. Only automatic loss control for crypto (no EOD liquidation).
- **BUY_COOLDOWN_SECONDS** - minimum gap between BUY orders for the same
  symbol (default 600s / 10 min). Persisted to `last_buy.json` across restarts.
- **CONFIDENCE_THRESHOLD** - minimum Llama confidence to act (default 0.70).
- **MAX_POSITION_SHARES** / **MAX_CRYPTO_POSITION_VALUE** - position caps.
- **EOD_LIQUIDATE_MINUTES_BEFORE_CLOSE** - close all stock positions N
  minutes before market close. Avoids overnight risk + PDT issues.
- **CASH_FILL_WAIT_SECONDS** - how long to wait for sell orders to fill
  when freeing cash for a new buy. Prevents race condition where buy fires
  before sell settles.

## What's done
- All 7 modules built and wired together (`trader`, `llama_brain`, `news`,
  `discord_notify`, `coach_io`, `daily_coach`, `main`)
- Stock day-trading: parallel analysis, scaling into positions, EOD liquidation
- Crypto 24/7 trading: dollar-based position sizing, separate watchlist
- Cash rebalancing: sells worst performers (with fill-wait) when cash runs low
- Take-profit AND stop-loss (percent-based, both stocks and crypto, plus
  startup sweep that catches positions breached while bot was down)
- Off-hours signal logging - consumed by daily coach
- BUY cooldowns persisted across restarts (`last_buy.json`)
- Two news sources (Alpaca + Google News RSS) fetched in parallel, cached 5 min
- Daily coach via Claude Code CLI subprocess (no API key needed)
- Discord notifications on every trade + error
- `requirements.txt` and `.env.example` in repo root

## What's next (open ideas, rough priority)
1. Schedule `daily_coach.py` automatically (cron on Mac, Task Scheduler on
   Windows, or have `main.py` invoke it once per day)
2. Add MAX_DAILY_LOSS circuit breaker - pause trading after N dollars lost
3. Include position size + cost basis in Llama prompt (currently decides
   blind to portfolio context)
4. Persist `_eod_liquidated_on` to disk so restart doesn't double-trigger
5. Backtest framework - replay historical data through the same decision path
6. Refactor `_process_stock` / `_process_crypto` duplication

## Don't do yet
- Multiple exchanges (Binance, Coinbase) - Alpaca only for v1
- Real money trading - paper only until backtest proves edge
- Fancy UI / web dashboard - Discord is enough
- Bigger Llama models (8B+) - would blow the 30s loop budget on Ryzen 7 4700U
