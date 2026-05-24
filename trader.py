"""
trader.py — Alpaca paper-trading wrappers (buy, sell, get position, get price).
Always paper mode unless two env vars confirm live trading.
"""

import os
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest, CryptoLatestQuoteRequest

load_dotenv()

API_KEY = os.environ["ALPACA_API_KEY"]
API_SECRET = os.environ["ALPACA_SECRET_KEY"]

# Paper mode is the default. Live requires BOTH env vars set correctly.
_live = (
    os.environ.get("LIVE_TRADING") == "true"
    and os.environ.get("CONFIRM_LIVE") == "YES_I_MEAN_IT"
)
PAPER = not _live

if not PAPER:
    print("[trader] WARNING: LIVE TRADING ENABLED — real money at risk!")
else:
    print("[trader] Paper trading mode active.")

trading_client = TradingClient(API_KEY, API_SECRET, paper=PAPER)
data_client = StockHistoricalDataClient(API_KEY, API_SECRET)
crypto_data_client = CryptoHistoricalDataClient(API_KEY, API_SECRET)


def is_market_open() -> bool:
    """Return True if the NYSE is currently open for trading."""
    try:
        clock = trading_client.get_clock()
        return clock.is_open
    except Exception as e:
        print(f"[trader] Could not check market clock: {e}")
        return False


def is_near_close(minutes: int = 10) -> bool:
    """Return True if the market closes within `minutes` minutes. Handles early closes."""
    try:
        clock = trading_client.get_clock()
        if not clock.is_open:
            return False
        seconds_left = (clock.next_close - datetime.now(timezone.utc)).total_seconds()
        return seconds_left <= minutes * 60
    except Exception as e:
        print(f"[trader] Could not check market close time: {e}")
        return False


def close_all_stock_positions() -> list[str]:
    """Sell every open stock position at market. Returns list of symbols closed."""
    try:
        positions = trading_client.get_all_positions()
    except Exception as e:
        print(f"[trader] Could not fetch positions for EOD close: {e}")
        return []

    closed = []
    for p in positions:
        if "/" in p.symbol:  # skip crypto — it trades 24/7
            continue
        try:
            sell(p.symbol, float(p.qty))
            closed.append(p.symbol)
        except Exception as e:
            print(f"[trader] EOD close failed for {p.symbol}: {e}")
    return closed


def get_account_cash() -> float:
    """Return available buying power in the account."""
    try:
        account = trading_client.get_account()
        return float(account.cash)
    except Exception as e:
        print(f"[trader] Could not fetch account cash: {e}")
        return 0.0


def get_stock_positions_by_pl() -> list[dict]:
    """Return open stock positions sorted by unrealized P&L ascending (worst performers first)."""
    try:
        positions = trading_client.get_all_positions()
        stock_positions = [
            {
                "symbol": p.symbol,
                "qty": float(p.qty),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
            }
            for p in positions
            if "/" not in p.symbol  # exclude crypto
        ]
        return sorted(stock_positions, key=lambda x: x["unrealized_pl"])
    except Exception as e:
        print(f"[trader] Could not fetch positions: {e}")
        return []


def get_price(symbol: str) -> float:
    """Return the latest ask price for a stock symbol. Retries twice on connection errors."""
    for attempt in range(3):
        try:
            request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quote = data_client.get_stock_latest_quote(request)
            return float(quote[symbol].ask_price)
        except Exception as e:
            if attempt == 2:
                raise
            print(f"[trader] get_price({symbol}) failed (attempt {attempt + 1}), retrying: {e}")
            time.sleep(2)


def get_crypto_price(symbol: str) -> float:
    """Return the latest ask price for a crypto pair. Retries twice on connection errors."""
    for attempt in range(3):
        try:
            request = CryptoLatestQuoteRequest(symbol_or_symbols=symbol)
            quote = crypto_data_client.get_crypto_latest_quote(request)
            return float(quote[symbol].ask_price)
        except Exception as e:
            if attempt == 2:
                raise
            print(f"[trader] get_crypto_price({symbol}) failed (attempt {attempt + 1}), retrying: {e}")
            time.sleep(2)


def get_position(symbol: str) -> float:
    """Return how many shares/coins we hold. Returns 0.0 if no position."""
    try:
        position = trading_client.get_open_position(symbol)
        return float(position.qty)
    except Exception:
        return 0.0


def get_position_value(symbol: str) -> float:
    """Return current market value in dollars of our position. 0.0 if no position."""
    try:
        position = trading_client.get_open_position(symbol)
        return float(position.market_value)
    except Exception:
        return 0.0


def buy(symbol: str, qty: float) -> dict:
    """Submit a market buy order. Uses GTC for crypto (24/7), DAY for stocks."""
    tif = TimeInForce.GTC if "/" in symbol else TimeInForce.DAY
    order_request = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=tif,
    )
    order = trading_client.submit_order(order_request)
    return {"id": str(order.id), "symbol": symbol, "qty": qty, "side": "BUY"}


def sell(symbol: str, qty: float) -> dict:
    """Submit a market sell order. Uses GTC for crypto (24/7), DAY for stocks."""
    tif = TimeInForce.GTC if "/" in symbol else TimeInForce.DAY
    order_request = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.SELL,
        time_in_force=tif,
    )
    order = trading_client.submit_order(order_request)
    return {"id": str(order.id), "symbol": symbol, "qty": qty, "side": "SELL"}
