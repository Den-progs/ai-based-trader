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
from coach_io import read_strategy, read_watchlist, write_strategy, write_watchlist
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

PROMPT_TEMPLATE = """You are a trading coach reviewing paper trading performance for a learning bot.

Your job:
1. Review the recent trades and identify what worked and what didn't
2. Suggest an improved strategy for tomorrow (keep it simple and concrete)
3. Pick 3-5 stock symbols for the watchlist based on the patterns you see

Rules:
- Keep the strategy short (2-3 sentences max)
- Only suggest well-known large-cap stocks (S&P 500)
- Be honest if there is not enough data yet

Respond ONLY with a JSON object in this exact format (no extra text before or after):
{{
  "strategy": "2-3 sentence strategy for tomorrow",
  "watchlist": ["SYMBOL1", "SYMBOL2", "SYMBOL3"],
  "summary": "1-2 sentence review of what happened and why you made these changes"
}}

---

Today's date: {date}

Current strategy: {strategy}

Current watchlist: {watchlist}

Open positions:
{positions}

Recent trades (last 7 days):
{trades}

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


def ask_claude_code(trades: list[dict], positions: list[dict], strategy: str, watchlist: list[str]) -> dict:
    """
    Send trade history + news to Claude Code CLI and parse the JSON response.
    Uses `claude -p` (print mode) — non-interactive, exits after one response.
    """
    # Gather headlines for every symbol on the watchlist
    news_lines = []
    for symbol in watchlist:
        for headline in get_headlines(symbol, max_headlines=3):
            news_lines.append(f"- [{symbol}] {headline}")
    news_text = "\n".join(news_lines) if news_lines else "No recent news found."

    prompt = PROMPT_TEMPLATE.format(
        date=datetime.now().strftime("%Y-%m-%d"),
        strategy=strategy,
        watchlist=watchlist,
        positions=json.dumps(positions, indent=2) if positions else "None",
        trades=json.dumps(trades, indent=2) if trades else "No trades in the last 7 days.",
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

    print(f"[coach] {len(trades)} recent trades, {len(positions)} open positions.")

    try:
        result = ask_claude_code(trades, positions, strategy, watchlist)
    except Exception as e:
        msg = f"Daily coach error: {e}"
        print(f"[coach] {msg}")
        discord.send(f"ERROR: {msg}")
        return

    new_strategy = result.get("strategy", strategy)
    new_watchlist = result.get("watchlist", watchlist)
    summary = result.get("summary", "No summary provided.")

    write_strategy(new_strategy)
    write_watchlist(new_watchlist)

    print(f"[coach] New strategy: {new_strategy}")
    print(f"[coach] New watchlist: {new_watchlist}")
    print(f"[coach] Summary: {summary}")

    discord.send(
        f"**Daily coach complete**\n"
        f"Summary: {summary}\n"
        f"Watchlist: {', '.join(new_watchlist)}\n"
        f"Strategy: {new_strategy}"
    )


if __name__ == "__main__":
    run()
