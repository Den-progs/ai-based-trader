"""
main.py - aggressive day trading loop.
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
import bot.discord_notify as discord
from bot.trader import (
    get_price, get_crypto_price, get_position, get_position_value,
    get_position_pl, get_position_pl_pct,
    buy, sell, is_market_open, is_near_close, close_all_stock_positions,
    get_account_cash, get_stock_positions_by_pl, get_all_positions,
)
from bot.llama_brain import ask_llama
from bot.news import get_headlines
from bot.coach_io import read_watchlist, read_crypto_watchlist, append_pending_signal, read_last_buy, save_last_buy

# Tracks whether we've already liquidated today so we don't spam sell orders
_eod_liquidated_on: str = ""

# Prevents two threads from simultaneously deciding to free up cash and
# selling the same position twice
_buy_lock = threading.Lock()
_last_buy: dict[str, float] = read_last_buy()  # persisted so cooldowns survive restarts


def free_up_cash(needed: float, exclude_symbol: str) -> bool:
    """
    Sell worst-performing stock positions (by unrealized P&L) until we've freed
    at least `needed` dollars, then WAIT for the orders to actually fill before
    returning. Skips `exclude_symbol`.

    Why we wait: Alpaca submit_order is async. Without waiting, the caller would
    immediately try to BUY before the SELL has settled into available cash, and
    the BUY would fail with "insufficient buying power" - silently locking in
    losses without ever opening the intended position.

    Returns True if cash reached the target within CASH_FILL_WAIT_SECONDS,
    False otherwise (caller should skip the BUY).
    """
    starting_cash = get_account_cash()
    target_cash = starting_cash + needed

    positions = get_stock_positions_by_pl()
    estimated_freed = 0.0
    any_sold = False

    for pos in positions:
        if estimated_freed >= needed:
            break
        if pos["symbol"] == exclude_symbol:
            continue
        try:
            sell(pos["symbol"], pos["qty"])
            any_sold = True
            estimated_freed += pos["market_value"]
            pl = pos["unrealized_pl"]
            print(f"[main] Sold {pos['symbol']} (P&L ${pl:+.2f}) to fund new trade")
            discord.send(f"REBALANCE: sold {pos['symbol']} (P&L ${pl:+.2f}) to free cash")
        except Exception as e:
            print(f"[main] Could not sell {pos['symbol']} during rebalance: {e}")

    if not any_sold:
        return False

    # Poll cash up to CASH_FILL_WAIT_SECONDS. Accept 95% of target - fees and
    # tiny price drift mean we rarely get the full estimated_freed back.
    for _ in range(config.CASH_FILL_WAIT_SECONDS):
        time.sleep(1)
        if get_account_cash() >= target_cash * 0.95:
            return True

    final_cash = get_account_cash()
    if final_cash >= target_cash * 0.95:
        return True
    print(f"[main] Cash freed only ${final_cash - starting_cash:.2f} of ${needed:.2f} needed within {config.CASH_FILL_WAIT_SECONDS}s.")
    return False


def _process_stock(symbol: str, market_open: bool) -> None:
    """Analyse one stock and act. Runs inside a thread."""
    try:
        # Risk checks first - bypass Llama entirely when triggered.
        # Percent-based so they scale across position sizes.
        if market_open:
            pl_pct = get_position_pl_pct(symbol)

            # Take-profit: sell winners at +TAKE_PROFIT_PCT
            if config.TAKE_PROFIT_PCT > 0 and pl_pct >= config.TAKE_PROFIT_PCT:
                held = get_position(symbol)
                if held > 0:
                    pl_dollars = get_position_pl(symbol)
                    sell(symbol, held)
                    msg = f"TAKE PROFIT {symbol} - {pl_pct:+.2%} (${pl_dollars:+.2f}), sold {held} shares"
                    discord.send(msg)
                    print(f"[stock][{symbol}] {msg}")
                    return

            # Stop-loss: cut losers at -STOP_LOSS_PCT. Critical risk control.
            if config.STOP_LOSS_PCT > 0 and pl_pct <= -config.STOP_LOSS_PCT:
                held = get_position(symbol)
                if held > 0:
                    pl_dollars = get_position_pl(symbol)
                    sell(symbol, held)
                    msg = f"STOP LOSS {symbol} - {pl_pct:+.2%} (${pl_dollars:+.2f}), sold {held} shares"
                    discord.send(msg)
                    print(f"[stock][{symbol}] {msg}")
                    return

        price = get_price(symbol)
        decision = ask_llama(symbol, price, news=get_headlines(symbol))

        action = decision["action"]
        confidence = decision["confidence"]
        reason = decision["reason"]

        print(f"[stock][{symbol}] ${price:.2f} -> {action} (conf={confidence:.2f}) - {reason}")

        if not market_open:
            if action in ("BUY", "SELL") and confidence >= config.CONFIDENCE_THRESHOLD:
                append_pending_signal(symbol, action, confidence, reason, price)
                print(f"[stock][{symbol}] Market closed - signal saved.")
            return

        if action == "BUY" and confidence >= config.CONFIDENCE_THRESHOLD:
            with _buy_lock:
                since_last = time.time() - _last_buy.get(symbol, 0)
                if since_last < config.BUY_COOLDOWN_SECONDS:
                    wait = int(config.BUY_COOLDOWN_SECONDS - since_last)
                    print(f"[stock][{symbol}] Cooldown - {wait}s left before next BUY.")
                else:
                    held = get_position(symbol)
                    if held >= config.MAX_POSITION_SHARES:
                        print(f"[stock][{symbol}] Max position reached ({held} shares), skipping BUY.")
                    else:
                        cost = price * config.QTY_PER_TRADE
                        cash = get_account_cash()
                        if cash < cost:
                            print(f"[stock][{symbol}] Low cash (${cash:.2f}), selling worst positions to fund ${cost:.2f} trade.")
                            if not free_up_cash(needed=cost, exclude_symbol=symbol):
                                print(f"[stock][{symbol}] Still not enough cash after rebalance, skipping.")
                                return
                        order = buy(symbol, config.QTY_PER_TRADE)
                        _last_buy[symbol] = time.time()
                        save_last_buy(_last_buy)
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
        # Risk checks first - bypass Llama entirely when triggered.
        # Crypto trades 24/7 so stop-loss is the ONLY auto-exit (no EOD liquidation).
        pl_pct = get_position_pl_pct(symbol)

        # Take-profit: sell winners at +TAKE_PROFIT_PCT
        if config.TAKE_PROFIT_PCT > 0 and pl_pct >= config.TAKE_PROFIT_PCT:
            held = get_position(symbol)
            if held > 0:
                pl_dollars = get_position_pl(symbol)
                sell(symbol, held)
                msg = f"TAKE PROFIT {symbol} - {pl_pct:+.2%} (${pl_dollars:+.2f}), sold {held} coins"
                discord.send(msg)
                print(f"[crypto][{symbol}] {msg}")
                return

        # Stop-loss: cut losers at -STOP_LOSS_PCT
        if config.STOP_LOSS_PCT > 0 and pl_pct <= -config.STOP_LOSS_PCT:
            held = get_position(symbol)
            if held > 0:
                pl_dollars = get_position_pl(symbol)
                sell(symbol, held)
                msg = f"STOP LOSS {symbol} - {pl_pct:+.2%} (${pl_dollars:+.2f}), sold {held} coins"
                discord.send(msg)
                print(f"[crypto][{symbol}] {msg}")
                return

        price = get_crypto_price(symbol)
        decision = ask_llama(symbol, price, news=get_headlines(symbol))

        action = decision["action"]
        confidence = decision["confidence"]
        reason = decision["reason"]

        print(f"[crypto][{symbol}] ${price:.2f} -> {action} (conf={confidence:.2f}) - {reason}")

        if action == "BUY" and confidence >= config.CONFIDENCE_THRESHOLD:
            since_last = time.time() - _last_buy.get(symbol, 0)
            if since_last < config.BUY_COOLDOWN_SECONDS:
                wait = int(config.BUY_COOLDOWN_SECONDS - since_last)
                print(f"[crypto][{symbol}] Cooldown - {wait}s left before next BUY.")
            else:
                pos_value = get_position_value(symbol)
                if pos_value >= config.MAX_CRYPTO_POSITION_VALUE:
                    print(f"[crypto][{symbol}] Max position value reached (${pos_value:.2f}), skipping BUY.")
                else:
                    qty = round(config.CRYPTO_TRADE_DOLLARS / price, 6)
                    order = buy(symbol, qty)
                    _last_buy[symbol] = time.time()
                    save_last_buy(_last_buy)
                    msg = f"BUY ${config.CRYPTO_TRADE_DOLLARS} of {symbol} ({qty} coins @ ${price:.2f}) | {reason}"
                    discord.send(msg)
                    print(f"[crypto][{symbol}] Order placed: {order}")

        elif action == "SELL" and confidence >= config.CONFIDENCE_THRESHOLD:
            held = get_position(symbol)
            if held > 0:
                sell_qty = round(config.CRYPTO_TRADE_DOLLARS / price, 6)
                qty = min(sell_qty, held)
                order = sell(symbol, qty)
                msg = f"SELL {qty} {symbol} @ ${price:.2f} | {reason}"
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
            f.result()


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
    print("[main] EOD liquidation - closing all stock positions.")
    discord.send("EOD liquidation: selling all stock positions before market close.")
    closed = close_all_stock_positions()
    if closed:
        discord.send(f"EOD closed: {', '.join(closed)}")
        print(f"[main] EOD closed: {closed}")
    else:
        print("[main] EOD: no open stock positions to close.")


def startup_profit_check() -> None:
    """On startup, immediately close positions past take-profit OR stop-loss
    thresholds. Catches positions that breached while bot was down."""
    if config.TAKE_PROFIT_PCT <= 0 and config.STOP_LOSS_PCT <= 0:
        return
    positions = get_all_positions()
    if not positions:
        print("[startup] No open positions.")
        return
    print(f"[startup] Checking {len(positions)} open positions for take-profit / stop-loss...")
    for pos in positions:
        symbol = pos["symbol"]
        qty = pos["qty"]
        pl_dollars = pos["unrealized_pl"]
        pl_pct = pos["unrealized_plpc"]
        print(f"[startup] {symbol}: qty={qty}, P&L={pl_pct:+.2%} (${pl_dollars:+.2f})")

        action = None
        if config.TAKE_PROFIT_PCT > 0 and pl_pct >= config.TAKE_PROFIT_PCT:
            action = "TAKE PROFIT"
        elif config.STOP_LOSS_PCT > 0 and pl_pct <= -config.STOP_LOSS_PCT:
            action = "STOP LOSS"

        if action:
            try:
                sell(symbol, qty)
                msg = f"STARTUP {action} {symbol} - {pl_pct:+.2%} (${pl_dollars:+.2f}), sold {qty}"
                discord.send(msg)
                print(f"[startup] {msg}")
            except Exception as e:
                print(f"[startup] Could not sell {symbol}: {e}")


def main() -> None:
    discord.send("Trader bot started - aggressive day trading mode. Paper only.")
    print("[main] Bot started. Press Ctrl+C to stop.")
    startup_profit_check()

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
