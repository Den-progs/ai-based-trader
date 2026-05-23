# What We Built — AI Paper Trader

A fully automated paper trading bot that uses two AI models to make stock decisions, reviews its own performance daily, and notifies you on Discord.

---

## The Big Picture

```
Every 30 seconds:
  Check if the market is open (NYSE clock via Alpaca).
  For each stock on the watchlist:
    1. Grab the latest price (Alpaca)
    2. Grab recent news headlines (Alpaca) — always, even if market is closed
    3. Ask local Llama → BUY / SELL / HOLD?
    4. Print the decision to the console every cycle
    If market is OPEN:
      5. If BUY and confidence ≥ 0.7 and we don't already own it → buy 1 share
      6. If SELL and confidence ≥ 0.7 and we hold shares → sell up to 1 share
      7. Send the trade to Discord
    If market is CLOSED:
      (just logs the decision, no orders placed)

Once a day:
    1. Pull full trade history from Alpaca (last 7 days)
    2. Grab current open positions
    3. Grab news for each watchlist symbol
    4. Ask Claude Code CLI → what should we do differently?
    5. Save the new strategy + updated watchlist to disk
    6. Send a summary to Discord
```

---

## Files We Built

### `discord_notify.py`
Sends messages to a Discord channel via a webhook URL stored in `.env`.

One function: `send(message)`. Every other file calls this to report what's happening. If the webhook URL is missing it just logs to console instead of crashing.

---

### `trader.py`
Wraps the Alpaca paper-trading API. Five functions:

- `is_market_open()` — asks Alpaca's clock API if NYSE is currently open
- `get_price(symbol)` — latest ask price
- `get_position(symbol)` — how many shares we currently hold (0.0 if none)
- `buy(symbol, qty)` — place a market buy order
- `sell(symbol, qty)` — place a market sell order

**Safety:** always runs in paper mode (`paper=True`) unless two specific environment variables are set. Real money requires both `LIVE_TRADING=true` AND `CONFIRM_LIVE=YES_I_MEAN_IT`.

---

### `llama_brain.py`
Talks to a local Llama 3.2 model running via Ollama (free, no internet needed, fast).

`ask_llama(symbol, price, news)` sends a prompt with the stock info and headlines, then parses the JSON response:
```json
{ "action": "BUY", "confidence": 0.82, "reason": "Strong earnings beat" }
```
Raises a `ConnectionError` if Ollama is down, `ValueError` if the response can't be parsed. Both are caught in `main.py` and logged.

---

### `news.py`
Fetches recent news headlines from Alpaca's news API.

`get_headlines(symbol, max_headlines=5)` returns a list of headline strings from the last 2 days. Returns an empty list if anything goes wrong so the bot keeps running even without news.

---

### `coach_io.py`
Simple file I/O — reads and writes two files:
- `strategy.txt` — the current trading strategy (a few sentences)
- `watchlist.json` — the list of stock symbols to trade

Both have sensible defaults if the files don't exist yet.

---

### `daily_coach.py`
Runs once a day. Powered by **Claude Code CLI** (`claude -p`) — no `ANTHROPIC_API_KEY` needed, uses your existing Claude Code subscription.

What it does:
1. Pulls the last 7 days of closed orders from Alpaca
2. Gets current open positions
3. Fetches recent news for each watchlist symbol
4. Reads the current strategy from `strategy.txt`
5. Builds a prompt and runs `claude -p "..."` as a subprocess
6. Parses the JSON that Claude prints back
7. Saves the new strategy + watchlist to disk
8. Posts a summary to Discord

---

### `main.py`
The main trading loop. Runs forever (every 30 seconds).

Each cycle:
1. Loads the watchlist from `watchlist.json`
2. Checks if the market is open right now
3. For each symbol — fetches price + news and asks Llama what to do
4. **Always prints the decision** (BUY/SELL/HOLD, confidence, reason) — even when market is closed, so you can watch what the bot would do
5. If market is **closed** → skips orders, keeps analysing (news overnight can set up a trade for open)
6. If market is **open** and Llama says BUY with confidence ≥ 0.7 → only buys if we don't already hold that stock
7. If market is **open** and Llama says SELL with confidence ≥ 0.7 → sells if we hold shares
8. Notifies Discord on every actual trade

The watchlist is re-loaded each cycle, so changes from `daily_coach.py` take effect automatically.

---

## How the Two AIs Work Together

|  | Llama 3.2 (local) | Claude Code CLI |
|---|---|---|
| **Runs** | Every 30 seconds | Once a day |
| **Job** | Fast BUY/SELL/HOLD decisions | Deep review of performance |
| **Cost** | Free (runs on your machine) | Free (uses your Claude Code subscription) |
| **How** | HTTP call to Ollama on localhost | Subprocess: `claude -p "..."` |
| **Input** | Price + news headlines | Full trade history + positions + news |
| **Output** | Action + confidence + reason | Updated strategy + watchlist + summary |

---

## Order Safety Rules

Before any buy order goes through, ALL of these must be true:

1. Market is open right now (Alpaca clock API)
2. Llama says BUY
3. Confidence ≥ 0.7
4. We don't already hold shares in that stock

Before any sell order goes through:

1. Market is open right now
2. Llama says SELL
3. Confidence ≥ 0.7
4. We actually hold shares to sell

---

## Data Flow

```
.env
 ├── ALPACA_API_KEY / ALPACA_SECRET_KEY
 │     ├── trader.py      (buy/sell/positions/price/market clock)
 │     └── news.py        (headlines)
 └── DISCORD_WEBHOOK_URL
       └── discord_notify.py

Claude Code CLI (no API key needed — uses your subscription)
 └── daily_coach.py runs: claude -p "..."

watchlist.json  ←──────────── daily_coach.py (writes)
     └── main.py reads this every 30s

strategy.txt    ←──────────── daily_coach.py (writes)
     └── daily_coach.py reads this as context for next review
```

---

## What's NOT Done Yet (Future Ideas)
- **Real money** — paper only until we're confident
- **Multiple exchanges** — Alpaca only for now
- **Backtesting** — test strategy on historical data
- **Web dashboard** — Discord notifications are enough for now
- **More news sources** — currently only Alpaca's built-in news API
- **Pending order check** — currently we check open positions but not pending/queued orders

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

# Run the daily review manually (or schedule it with cron):
python daily_coach.py
```
