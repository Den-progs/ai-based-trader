"""
daily_coach.py — runs once a day. Uses Claude Code CLI (claude -p) to review
trades and update strategy + watchlist. No ANTHROPIC_API_KEY needed — uses
your existing Claude Code subscription.
"""

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus
from dotenv import load_dotenv

import discord_notify as discord
from coach_io import (
    read_strategy, read_watchlist, write_strategy, write_watchlist,
    read_crypto_watchlist, write_crypto_watchlist,
    read_pending_signals, clear_pending_signals,
)
from news import get_headlines

load_dotenv()

API_KEY = os.environ["ALPACA_API_KEY"]
API_SECRET = os.environ["ALPACA_SECRET_KEY"]

# Paper mode only — same safety rule as trader.py
_live = (
    os.environ.get("LIVE_TRADING") == "true"
    and os.environ.get("CONFIRM_LIVE") == "YES_I_MEAN_IT"
)
PAPER = not _live

trading_client = TradingClient(API_KEY, API_SECRET, paper=PAPER)

PROMPT_TEMPLATE = """You are an aggressive day trading coach for a paper trading bot.

Your job:
1. Review the recent trades — what worked, what didn't, what patterns do you see?
2. Look at off-hours signals — what was Llama consistently bullish or bearish on?
3. Write a short aggressive day trading strategy for tomorrow
4. Pick 20–50 stocks for the watchlist — prioritise high-momentum, high-volume names
   that are likely to have big intraday moves tomorrow based on news and recent trends
5. Pick 1–3 crypto pairs for the crypto watchlist

Rules:
- Stocks must be real US-listed equities (NYSE/NASDAQ). Prefer S&P 500 but include
  any high-momentum name that has a strong catalyst right now
- Crypto must be real pairs available on Alpaca (e.g. BTC/USD, ETH/USD, SOL/USD)
- Strategy: 2-3 sentences max, day-trading focused (enter and exit same day)
- Be aggressive — the bot closes all stock positions before market close anyway
- Be honest if there is not enough data yet

Respond ONLY with a JSON object in this exact format (no extra text before or after):
{{
  "strategy": "2-3 sentence aggressive day trading strategy for tomorrow",
  "watchlist": ["SYMBOL1", "SYMBOL2", ..., up to 50 symbols],
  "crypto_watchlist": ["BTC/USD", "ETH/USD"],
  "summary": "1-2 sentence review of what happened and why you made these changes"
}}

---

Today's date: {date}

Current strategy: {strategy}

Current stock watchlist: {watchlist}

Current crypto watchlist: {crypto_watchlist}

Open positions:
{positions}

Recent trades (last 7 days):
{trades}

Off-hours stock signals (what Llama wanted to do while market was closed):
{pending_signals}

Recent news:
{news}"""


def get_recent_trades() -> list[dict]:
    """Get closed orders from the last 7 days."""
    since = datetime.now(timezone.utc) - timedelta(days=7)
    try:
        orders = trading_client.get_orders(
            GetOrdersRequest(
                status=QueryOrderStatus.CLOSED,
                after=since,
                limit=50,
            )
        )
        return [
            {
                "symbol": o.symbol,
                "side": o.side.value,
                "qty": str(o.qty),
                "filled_price": str(o.filled_avg_price),
                "filled_at": str(o.filled_at),
                "status": o.status.value,
            }
            for o in orders
        ]
    except Exception as e:
        print(f"[coach] Error fetching orders: {e}")
        return []


def get_positions() -> list[dict]:
    """Get current open positions."""
    try:
        positions = trading_client.get_all_positions()
        return [
            {
                "symbol": p.symbol,
                "qty": str(p.qty),
                "market_value": str(p.market_value),
                "unrealized_pl": str(p.unrealized_pl),
            }
            for p in positions
        ]
    except Exception as e:
        print(f"[coach] Error fetching positions: {e}")
        return []


def ask_claude_code(
    trades: list[dict],
    positions: list[dict],
    strategy: str,
    watchlist: list[str],
    crypto_watchlist: list[str],
    pending_signals: list[dict],
) -> dict:
    """
    Send trade history + news + pending signals to Claude Code CLI and parse the JSON response.
    Uses `claude -p` (print mode) — non-interactive, exits after one response.
    """
    # Gather headlines for every symbol on both watchlists
    all_symbols = watchlist + crypto_watchlist
    news_lines = []
    for symbol in all_symbols:
        for headline in get_headlines(symbol, max_headlines=3):
            news_lines.append(f"- [{symbol}] {headline}")
    news_text = "\n".join(news_lines) if news_lines else "No recent news found."

    if pending_signals:
        pending_text = json.dumps(pending_signals, indent=2)
    else:
        pending_text = "No off-hours signals recorded."

    prompt = PROMPT_TEMPLATE.format(
        date=datetime.now().strftime("%Y-%m-%d"),
        strategy=strategy,
        watchlist=watchlist,
        crypto_watchlist=crypto_watchlist,
        positions=json.dumps(positions, indent=2) if positions else "None",
        trades=json.dumps(trades, indent=2) if trades else "No trades in the last 7 days.",
        pending_signals=pending_text,
        news=news_text,
    )

    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=120,  # Claude Code can take a moment
        )
    except FileNotFoundError:
        raise RuntimeError("claude CLI not found — make sure Claude Code is installed and in your PATH.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Claude Code timed out after 120 seconds.")

    if result.returncode != 0:
        raise RuntimeError(f"Claude Code exited with error:\n{result.stderr.strip()}")

    raw = result.stdout

    # Extract JSON even if Claude adds surrounding text
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON found in Claude Code output:\n{raw!r}")

    return json.loads(raw[start:end])


def run() -> None:
    print("[coach] Starting daily review...")
    discord.send("Daily coach running — reviewing trades with Claude Code...")

    trades = get_recent_trades()
    positions = get_positions()
    strategy = read_strategy()
    watchlist = read_watchlist()
    crypto_watchlist = read_crypto_watchlist()
    pending_signals = read_pending_signals()

    print(f"[coach] {len(trades)} recent trades, {len(positions)} open positions, {len(pending_signals)} pending signals.")

    try:
        result = ask_claude_code(trades, positions, strategy, watchlist, crypto_watchlist, pending_signals)
    except Exception as e:
        msg = f"Daily coach error: {e}"
        print(f"[coach] {msg}")
        discord.send(f"ERROR: {msg}")
        return

    new_strategy = result.get("strategy", strategy)
    new_watchlist = result.get("watchlist", watchlist)
    new_crypto_watchlist = result.get("crypto_watchlist", crypto_watchlist)
    summary = result.get("summary", "No summary provided.")

    write_strategy(new_strategy)
    write_watchlist(new_watchlist)
    write_crypto_watchlist(new_crypto_watchlist)
    clear_pending_signals()

    print(f"[coach] New strategy: {new_strategy}")
    print(f"[coach] New stock watchlist: {new_watchlist}")
    print(f"[coach] New crypto watchlist: {new_crypto_watchlist}")
    print(f"[coach] Summary: {summary}")

    discord.send(
        f"**Daily coach complete**\n"
        f"Summary: {summary}\n"
        f"Stocks: {', '.join(new_watchlist)}\n"
        f"Crypto: {', '.join(new_crypto_watchlist)}\n"
        f"Strategy: {new_strategy}"
    )


if __name__ == "__main__":
    run()
