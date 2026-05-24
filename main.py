"""
main.py — aggressive day trading loop.
Stocks: parallel analysis across up to 50 symbols, orders only when NYSE is open,
        scales into positions up to MAX_POSITION_SHARES, liquidates everything
        EOD_LIQUIDATE_MINUTES_BEFORE_CLOSE minutes before market close.
Crypto: parallel analysis and trading 24/7.
Off-hours stock signals saved to pending_signals.json for the daily review.
"""

import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import config
import discord_notify as discord
from trader import (
    get_price, get_crypto_price, get_position,
    buy, sell, is_market_open, is_near_close, close_all_stock_positions,
    get_account_cash, get_stock_positions_by_pl,
)
from llama_brain import ask_llama
from news import get_headlines
from coach_io import read_watchlist, read_crypto_watchlist, append_pending_signal

# Tracks whether we've already liquidated today so we don't spam sell orders
_eod_liquidated_on: str = ""

# Prevents two threads from simultaneously deciding to free up cash and
# selling the same position twice
_buy_lock = threading.Lock()


def free_up_cash(needed: float, exclude_symbol: str) -> float:
    """
    Sell worst-performing stock positions (by unrealized P&L) until we've freed
    at least `needed` dollars. Skips `exclude_symbol` (the stock we're about to buy).
    Returns the total market value of what was sold.
    """
    freed = 0.0
    positions = get_stock_positions_by_pl()  # worst P&L first

    for pos in positions:
        if freed >= needed:
            break
        if pos["symbol"] == exclude_symbol:
            continue
        try:
            sell(pos["symbol"], pos["qty"])
            freed += pos["market_value"]
            pl = pos["unrealized_pl"]
            print(f"[main] Sold {pos['symbol']} (P&L ${pl:+.2f}) to fund new trade")
            discord.send(f"REBALANCE: sold {pos['symbol']} (P&L ${pl:+.2f}) to free cash")
        except Exception as e:
            print(f"[main] Could not sell {pos['symbol']} during rebalance: {e}")

    return freed


def _process_stock(symbol: str, market_open: bool) -> None:
    """Analyse one stock and act. Runs inside a thread."""
    try:
        price = get_price(symbol)
        decision = ask_llama(symbol, price, news=get_headlines(symbol))

        action = decision["action"]
        confidence = decision["confidence"]
        reason = decision["reason"]

        print(f"[stock][{symbol}] ${price:.2f} → {action} (conf={confidence:.2f}) — {reason}")

        if not market_open:
            if action in ("BUY", "SELL") and confidence >= config.CONFIDENCE_THRESHOLD:
                append_pending_signal(symbol, action, confidence, reason, price)
                print(f"[stock][{symbol}] Market closed — signal saved.")
            return

        if action == "BUY" and confidence >= config.CONFIDENCE_THRESHOLD:
            with _buy_lock:
                held = get_position(symbol)
                if held >= config.MAX_POSITION_SHARES:
                    print(f"[stock][{symbol}] Max position reached ({held} shares), skipping BUY.")
                else:
                    cost = price * config.QTY_PER_TRADE
                    cash = get_account_cash()
                    if cash < cost:
                        print(f"[stock][{symbol}] Low cash (${cash:.2f}), selling worst positions to fund ${cost:.2f} trade.")
                        freed = free_up_cash(needed=cost, exclude_symbol=symbol)
                        if freed + cash < cost:
                            print(f"[stock][{symbol}] Still not enough cash after rebalance, skipping.")
                            return
                    order = buy(symbol, config.QTY_PER_TRADE)
                    msg = f"BUY {config.QTY_PER_TRADE}x {symbol} @ ${price:.2f} (held {held:.0f}) | {reason}"
                    discord.send(msg)
                    print(f"[stock][{symbol}] Order placed: {order}")

        elif action == "SELL" and confidence >= config.CONFIDENCE_THRESHOLD:
            held = get_position(symbol)
            if held > 0:
                qty = min(config.QTY_PER_TRADE, held)
                order = sell(symbol, qty)
                msg = f"SELL {qty}x {symbol} @ ${price:.2f} | {reason}"
                discord.send(msg)
                print(f"[stock][{symbol}] Order placed: {order}")
            else:
                print(f"[stock][{symbol}] SELL signal but no position, skipping.")

    except ConnectionError as e:
        msg = f"[stock][{symbol}] Ollama error: {e}"
        print(msg)
        discord.send(f"ERROR: {msg}")
    except Exception as e:
        msg = f"[stock][{symbol}] Error: {e}"
        print(msg)
        discord.send(f"ERROR: {msg}")


def _process_crypto(symbol: str) -> None:
    """Analyse one crypto pair and act. Runs inside a thread."""
    try:
        price = get_crypto_price(symbol)
        decision = ask_llama(symbol, price, news=get_headlines(symbol))

        action = decision["action"]
        confidence = decision["confidence"]
        reason = decision["reason"]

        print(f"[crypto][{symbol}] ${price:.2f} → {action} (conf={confidence:.2f}) — {reason}")

        if action == "BUY" and confidence >= config.CONFIDENCE_THRESHOLD:
            held = get_position(symbol)
            if held >= config.MAX_POSITION_SHARES:
                print(f"[crypto][{symbol}] Max position reached, skipping BUY.")
            else:
                order = buy(symbol, config.QTY_PER_TRADE)
                msg = f"BUY {config.QTY_PER_TRADE}x {symbol} @ ${price:.2f} | {reason}"
                discord.send(msg)
                print(f"[crypto][{symbol}] Order placed: {order}")

        elif action == "SELL" and confidence >= config.CONFIDENCE_THRESHOLD:
            held = get_position(symbol)
            if held > 0:
                qty = min(config.QTY_PER_TRADE, held)
                order = sell(symbol, qty)
                msg = f"SELL {qty}x {symbol} @ ${price:.2f} | {reason}"
                discord.send(msg)
                print(f"[crypto][{symbol}] Order placed: {order}")
            else:
                print(f"[crypto][{symbol}] SELL signal but no position, skipping.")

    except ConnectionError as e:
        msg = f"[crypto][{symbol}] Ollama error: {e}"
        print(msg)
        discord.send(f"ERROR: {msg}")
    except Exception as e:
        msg = f"[crypto][{symbol}] Error: {e}"
        print(msg)
        discord.send(f"ERROR: {msg}")


def stock_cycle(symbols: list[str], market_open: bool) -> None:
    with ThreadPoolExecutor(max_workers=config.THREAD_WORKERS) as pool:
        futures = {pool.submit(_process_stock, s, market_open): s for s in symbols}
        for f in as_completed(futures):
            f.result()  # surfaces any unhandled exceptions


def crypto_cycle(symbols: list[str]) -> None:
    with ThreadPoolExecutor(max_workers=config.THREAD_WORKERS) as pool:
        futures = {pool.submit(_process_crypto, s): s for s in symbols}
        for f in as_completed(futures):
            f.result()


def eod_liquidate(today: str) -> None:
    """Sell all stock positions near market close. Runs once per day."""
    global _eod_liquidated_on
    if _eod_liquidated_on == today:
        return
    _eod_liquidated_on = today
    print("[main] EOD liquidation — closing all stock positions.")
    discord.send("EOD liquidation: selling all stock positions before market close.")
    closed = close_all_stock_positions()
    if closed:
        discord.send(f"EOD closed: {', '.join(closed)}")
        print(f"[main] EOD closed: {closed}")
    else:
        print("[main] EOD: no open stock positions to close.")


def main() -> None:
    discord.send("Trader bot started — aggressive day trading mode. Paper only.")
    print("[main] Bot started. Press Ctrl+C to stop.")

    while True:
        stocks = read_watchlist()
        crypto = read_crypto_watchlist()
        market_open = is_market_open()

        today = time.strftime("%Y-%m-%d")

        if market_open and is_near_close(config.EOD_LIQUIDATE_MINUTES_BEFORE_CLOSE):
            eod_liquidate(today)
        else:
            status = "OPEN" if market_open else "CLOSED (signals saved, crypto trading)"
            print(f"\n[main] Market: {status} | {len(stocks)} stocks | {len(crypto)} crypto")
            stock_cycle(stocks, market_open)
            crypto_cycle(crypto)

        print(f"[main] Sleeping {config.LOOP_INTERVAL}s...")
        time.sleep(config.LOOP_INTERVAL)


if __name__ == "__main__":
    main()
