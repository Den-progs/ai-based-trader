"""
main.py — trading loop. Runs every 30 seconds.
For each symbol in the watchlist: get price, ask Llama, act on decision.
"""

import time
import json
from pathlib import Path

import discord_notify as discord
from trader import get_price, get_position, buy, sell, is_market_open
from llama_brain import ask_llama
from news import get_headlines

LOOP_INTERVAL = 30  # seconds between each cycle
QTY_PER_TRADE = 1   # shares to buy/sell per decision

# Watchlist lives in watchlist.json (written by daily_coach.py).
# Fall back to a default list until the coach runs for the first time.
WATCHLIST_FILE = Path(__file__).parent / "watchlist.json"
DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA"]


def load_watchlist() -> list[str]:
    if WATCHLIST_FILE.exists():
        try:
            return json.loads(WATCHLIST_FILE.read_text())
        except Exception as e:
            print(f"[main] Could not read watchlist.json: {e}")
    return DEFAULT_WATCHLIST


def run_cycle(symbols: list[str]) -> None:
    market_open = is_market_open()
    if not market_open:
        print("[main] Market is closed — analysing news only, no orders.")

    for symbol in symbols:
        try:
            price = get_price(symbol)
            decision = ask_llama(symbol, price, news=get_headlines(symbol))

            action = decision["action"]
            confidence = decision["confidence"]
            reason = decision["reason"]

            print(f"[{symbol}] ${price:.2f} → {action} (conf={confidence:.2f}) — {reason}")

            if not market_open:
                # Keep analysing but don't touch the account
                continue

            if action == "BUY" and confidence >= 0.7:
                if get_position(symbol) > 0:
                    print(f"[{symbol}] Already holding position, skipping BUY.")
                else:
                    order = buy(symbol, QTY_PER_TRADE)
                    msg = f"BUY {QTY_PER_TRADE}x {symbol} @ ${price:.2f} | {reason}"
                    discord.send(msg)
                    print(f"[{symbol}] Order placed: {order}")

            elif action == "SELL" and confidence >= 0.7:
                held = get_position(symbol)
                if held > 0:
                    qty = min(QTY_PER_TRADE, held)
                    order = sell(symbol, qty)
                    msg = f"SELL {qty}x {symbol} @ ${price:.2f} | {reason}"
                    discord.send(msg)
                    print(f"[{symbol}] Order placed: {order}")
                else:
                    print(f"[{symbol}] SELL signal but no position held, skipping.")

            # HOLD or low confidence — do nothing

        except ConnectionError as e:
            msg = f"[{symbol}] Ollama connection error: {e}"
            print(msg)
            discord.send(f"ERROR: {msg}")

        except Exception as e:
            msg = f"[{symbol}] Unexpected error: {e}"
            print(msg)
            discord.send(f"ERROR: {msg}")


def main() -> None:
    discord.send("Trader bot started. Paper mode active.")
    print("[main] Bot started. Press Ctrl+C to stop.")

    while True:
        watchlist = load_watchlist()
        print(f"\n[main] Running cycle for: {watchlist}")
        run_cycle(watchlist)
        print(f"[main] Sleeping {LOOP_INTERVAL}s...")
        time.sleep(LOOP_INTERVAL)


if __name__ == "__main__":
    main()
