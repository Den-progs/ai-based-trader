"""
main.py — trading loop. Runs every 30 seconds.
Stocks: analyses every cycle, only places orders when NYSE is open.
Crypto: analyses and trades every cycle (markets are 24/7).
Off-hours stock signals are saved to pending_signals.json for the daily review.
"""

import time

import discord_notify as discord
from trader import get_price, get_crypto_price, get_position, buy, sell, is_market_open
from llama_brain import ask_llama
from news import get_headlines
from coach_io import (
    read_watchlist,
    read_crypto_watchlist,
    append_pending_signal,
)

LOOP_INTERVAL = 30  # seconds between each cycle
QTY_PER_TRADE = 1   # shares / coins to buy or sell per decision
CONFIDENCE_THRESHOLD = 0.7


def stock_cycle(symbols: list[str], market_open: bool) -> None:
    """
    Analyse each stock every cycle.
    If market is open: place orders (with position check).
    If market is closed: save signal to pending_signals.json for later review.
    """
    for symbol in symbols:
        try:
            price = get_price(symbol)
            decision = ask_llama(symbol, price, news=get_headlines(symbol))

            action = decision["action"]
            confidence = decision["confidence"]
            reason = decision["reason"]

            print(f"[stock][{symbol}] ${price:.2f} → {action} (conf={confidence:.2f}) — {reason}")

            if not market_open:
                # Save the signal so the daily coach can see what Llama wanted to do
                if action in ("BUY", "SELL") and confidence >= CONFIDENCE_THRESHOLD:
                    append_pending_signal(symbol, action, confidence, reason, price)
                    print(f"[stock][{symbol}] Market closed — signal saved for later review.")
                continue

            if action == "BUY" and confidence >= CONFIDENCE_THRESHOLD:
                if get_position(symbol) > 0:
                    print(f"[stock][{symbol}] Already holding position, skipping BUY.")
                else:
                    order = buy(symbol, QTY_PER_TRADE)
                    msg = f"BUY {QTY_PER_TRADE}x {symbol} @ ${price:.2f} | {reason}"
                    discord.send(msg)
                    print(f"[stock][{symbol}] Order placed: {order}")

            elif action == "SELL" and confidence >= CONFIDENCE_THRESHOLD:
                held = get_position(symbol)
                if held > 0:
                    qty = min(QTY_PER_TRADE, held)
                    order = sell(symbol, qty)
                    msg = f"SELL {qty}x {symbol} @ ${price:.2f} | {reason}"
                    discord.send(msg)
                    print(f"[stock][{symbol}] Order placed: {order}")
                else:
                    print(f"[stock][{symbol}] SELL signal but no position held, skipping.")

        except ConnectionError as e:
            msg = f"[stock][{symbol}] Ollama connection error: {e}"
            print(msg)
            discord.send(f"ERROR: {msg}")

        except Exception as e:
            msg = f"[stock][{symbol}] Unexpected error: {e}"
            print(msg)
            discord.send(f"ERROR: {msg}")


def crypto_cycle(symbols: list[str]) -> None:
    """
    Analyse and trade crypto every cycle — no market hours restriction.
    Same position check applies: only buy if we don't already hold it.
    """
    for symbol in symbols:
        try:
            price = get_crypto_price(symbol)
            decision = ask_llama(symbol, price, news=get_headlines(symbol))

            action = decision["action"]
            confidence = decision["confidence"]
            reason = decision["reason"]

            print(f"[crypto][{symbol}] ${price:.2f} → {action} (conf={confidence:.2f}) — {reason}")

            if action == "BUY" and confidence >= CONFIDENCE_THRESHOLD:
                if get_position(symbol) > 0:
                    print(f"[crypto][{symbol}] Already holding position, skipping BUY.")
                else:
                    order = buy(symbol, QTY_PER_TRADE)
                    msg = f"BUY {QTY_PER_TRADE}x {symbol} @ ${price:.2f} | {reason}"
                    discord.send(msg)
                    print(f"[crypto][{symbol}] Order placed: {order}")

            elif action == "SELL" and confidence >= CONFIDENCE_THRESHOLD:
                held = get_position(symbol)
                if held > 0:
                    qty = min(QTY_PER_TRADE, held)
                    order = sell(symbol, qty)
                    msg = f"SELL {qty}x {symbol} @ ${price:.2f} | {reason}"
                    discord.send(msg)
                    print(f"[crypto][{symbol}] Order placed: {order}")
                else:
                    print(f"[crypto][{symbol}] SELL signal but no position held, skipping.")

        except ConnectionError as e:
            msg = f"[crypto][{symbol}] Ollama connection error: {e}"
            print(msg)
            discord.send(f"ERROR: {msg}")

        except Exception as e:
            msg = f"[crypto][{symbol}] Unexpected error: {e}"
            print(msg)
            discord.send(f"ERROR: {msg}")


def main() -> None:
    discord.send("Trader bot started. Paper mode active.")
    print("[main] Bot started. Press Ctrl+C to stop.")

    while True:
        stocks = read_watchlist()
        crypto = read_crypto_watchlist()
        market_open = is_market_open()

        status = "OPEN" if market_open else "CLOSED (stock signals saved, crypto still trading)"
        print(f"\n[main] Market: {status}")
        print(f"[main] Stocks: {stocks} | Crypto: {crypto}")

        stock_cycle(stocks, market_open)
        crypto_cycle(crypto)

        print(f"[main] Sleeping {LOOP_INTERVAL}s...")
        time.sleep(LOOP_INTERVAL)


if __name__ == "__main__":
    main()
