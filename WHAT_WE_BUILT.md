# What We Built — AI Paper Trader

A fully automated paper trading bot that uses two AI models to make stock and crypto decisions, reviews its own performance daily, and notifies you on Discord.

---

## The Big Picture

```
Every 30 seconds:
  Check if the stock market is open (NYSE clock via Alpaca).

  For each STOCK on the watchlist (up to 50, analysed in parallel):
    1. If unrealized profit >= $150 → sell immediately, skip Llama
    2. Grab the latest price (Alpaca, 3 retries on error)
    3. Grab recent news headlines (Alpaca + Google News, cached 5 min)
    4. Ask local Llama → BUY / SELL / HOLD?
    If market is OPEN:
      5. If BUY and confidence >= 0.7:
           - Check 10-min cooldown (no repeat buys too fast)
           - Check we're under the 15-share position limit
           - Check we have enough cash; if not, sell worst P&L stocks to fund it
           - Buy 3 shares, notify Discord
      6. If SELL and confidence >= 0.7 and we hold shares → sell 3 shares
    If market is CLOSED:
      - Save BUY/SELL signals to pending_signals.json for the daily review

  If near market close (10 min before):
    - Sell ALL stock positions (end-of-day liquidation)

  For each CRYPTO pair (15 pairs, analysed in parallel, 24/7):
    1. If unrealized profit >= $150 → sell immediately, skip Llama
    2. Grab the latest price
    3. Grab news headlines
    4. Ask Llama → BUY / SELL / HOLD?
    5. If BUY and confidence >= 0.7:
         - Check 10-min cooldown
         - Check we're under the $2000 position value limit
         - Buy $300 worth of the coin
    6. If SELL → sell $300 worth

Once a day (run daily_coach.py manually):
    1. Pull full trade history from Alpaca (last 7 days)
    2. Read current open positions, strategy, pending signals, and news
    3. Ask Claude Code CLI → review + pick tomorrow's watchlist
    4. Save new strategy + stock watchlist + crypto watchlist to disk
    5. Clear pending signals
    6. Send a summary to Discord

On every startup:
    - Check all open positions and immediately sell any already above $150 profit
```

---

## Project Structure

```
main.py              ← run this to start the bot (runs forever)
daily_coach.py       ← run this once a day for the Claude review
config.py            ← all settings in one place

bot/                 ← all the core modules
  trader.py          ← Alpaca buy/sell/price/position wrappers
  llama_brain.py     ← talks to local Llama via Ollama
  news.py            ← fetches headlines from Alpaca + Google News
  discord_notify.py  ← sends messages to Discord webhook
  coach_io.py        ← reads/writes all files in data/

data/                ← persistent state (watchlists, strategy, runtime files)
  watchlist.json     ← stock symbols to trade (set by daily coach)
  crypto_watchlist.json
  strategy.txt       ← current trading strategy (written by Claude)
  pending_signals.json   ← off-hours signals (gitignored)
  last_buy.json          ← cooldown timestamps (gitignored)
```

---

## Files Explained

### `bot/trader.py`
All Alpaca wrappers. Always paper mode unless two env vars confirm live trading.

Functions: `is_market_open()`, `is_near_close()`, `get_price()`, `get_crypto_price()`, `get_position()`, `get_position_value()`, `get_position_pl()`, `get_account_cash()`, `get_stock_positions_by_pl()`, `get_all_positions()`, `buy()`, `sell()`, `close_all_stock_positions()`

Handles the Alpaca quirk where positions come back as `ETHUSD` (no slash) but orders use `ETH/USD` — `_is_crypto()` handles both formats.

---

### `bot/llama_brain.py`
Talks to local Llama 3.2 running via Ollama (free, runs on your machine, no internet needed).

`ask_llama(symbol, price, news)` sends a prompt and parses the JSON response:
```json
{ "action": "BUY", "confidence": 0.82, "reason": "Strong earnings beat" }
```
Handles Llama sometimes cutting off before the closing `}`.

---

### `bot/news.py`
Fetches headlines from two sources in parallel:
- **Alpaca News API** — financial news, uses your API key
- **Google News RSS** — free, no key, built-in XML parser

Results are cached per symbol for 5 minutes so the bot doesn't spam the APIs across 50+ parallel threads.

---

### `bot/discord_notify.py`
One function: `send(message)`. Every file calls this to report trades and errors. Silent if the webhook URL is missing.

---

### `bot/coach_io.py`
Reads and writes all files in `data/`. Thread-safe (uses locks for concurrent writes). Manages: strategy, watchlists, pending signals, buy cooldown timestamps.

---

### `daily_coach.py`
Runs once a day. Uses **Claude Code CLI** (`claude -p`) — no `ANTHROPIC_API_KEY` needed, uses your Claude Code subscription.

Passes the full trade history, open positions, off-hours signals, and news to Claude. Gets back a new strategy, stock watchlist (20–50 names), and crypto watchlist. Writes them to `data/` and posts a summary to Discord.

---

### `main.py`
The trading loop. Runs forever. Reloads the watchlist from disk every cycle so daily coach changes take effect immediately.

---

## How the Two AIs Work Together

|  | Llama 3.2 (local) | Claude Code CLI |
|---|---|---|
| **Runs** | Every 30 seconds | Once a day |
| **Job** | Fast BUY/SELL/HOLD decisions | Deep review + pick tomorrow's watchlist |
| **Cost** | Free (runs on your machine) | Free (uses your Claude Code subscription) |
| **Speed** | ~2s per symbol | ~60–90 seconds total |
| **Input** | Price + news headlines | Trade history + positions + pending signals + news |
| **Output** | Action + confidence + reason | Updated strategy + stock watchlist + crypto watchlist |

---

## Safety Rules

**Before any stock buy:**
1. Market is open
2. Llama says BUY with confidence >= 0.7
3. 10-minute cooldown since last buy of that symbol has passed
4. Position is under 15 shares
5. Enough cash available (sells worst positions if not)

**Before any crypto buy:**
1. Confidence >= 0.7 (no market hours check — crypto is 24/7)
2. 10-minute cooldown
3. Position value is under $2000

**Auto-sell triggers:**
- Unrealized profit >= $150 (take-profit, checked before Llama runs)
- 10 minutes before market close (EOD liquidation, stocks only)

**Real money:** requires BOTH `LIVE_TRADING=true` AND `CONFIRM_LIVE=YES_I_MEAN_IT` in `.env`. Default everywhere is paper.

---

## Data Flow

```
.env
 ├── ALPACA_API_KEY / ALPACA_SECRET_KEY
 │     ├── bot/trader.py    (buy/sell/positions/price/market clock)
 │     └── bot/news.py      (Alpaca news headlines)
 └── DISCORD_WEBHOOK_URL
       └── bot/discord_notify.py

Ollama (local, port 11434)
 └── bot/llama_brain.py  ← called every 30s for every symbol

Claude Code CLI (no API key — uses your subscription)
 └── daily_coach.py runs: claude -p "..."

data/watchlist.json        ←── daily_coach.py (writes) / main.py (reads every cycle)
data/crypto_watchlist.json ←── daily_coach.py (writes) / main.py (reads every cycle)
data/strategy.txt          ←── daily_coach.py (writes and reads as context)
data/pending_signals.json  ←── main.py (writes off-hours signals) / daily_coach.py (reads + clears)
data/last_buy.json         ←── main.py (persists buy cooldowns across restarts)
```

---

## What's NOT Done Yet (Future Ideas)
- **Stop-loss** — auto-sell if a position drops X dollars (opposite of take-profit)
- **Strategy fed to Llama** — daily coach writes a strategy but Llama doesn't read it yet
- **Real money** — paper only until we're confident
- **Backtesting** — test strategy on historical data
- **Web dashboard** — Discord notifications are enough for now
- **Multiple exchanges** — Alpaca only for now

---

## Running It

```bash
# Add keys to .env first:
# ALPACA_API_KEY=...
# ALPACA_SECRET_KEY=...
# DISCORD_WEBHOOK_URL=...

# Make sure Ollama is running with Llama:
ollama run llama3.2:3b

# Make sure Claude Code CLI is installed:
npm install -g @anthropic-ai/claude-code

# Start the trading loop:
python main.py

# Run the daily review manually (or schedule it):
python daily_coach.py
```
