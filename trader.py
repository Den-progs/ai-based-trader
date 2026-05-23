"""
trader.py — Alpaca paper-trading wrappers (buy, sell, get position, get price).
Always paper mode unless two env vars confirm live trading.
"""

import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

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


def is_market_open() -> bool:
    """Return True if the NYSE is currently open for trading."""
    try:
        clock = trading_client.get_clock()
        return clock.is_open
    except Exception as e:
        print(f"[trader] Could not check market clock: {e}")
        return False


def get_price(symbol: str) -> float:
    """Return the latest ask price for a symbol."""
    request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
    quote = data_client.get_stock_latest_quote(request)
    return float(quote[symbol].ask_price)


def get_position(symbol: str) -> float:
    """Return how many shares we hold. Returns 0.0 if no position."""
    try:
        position = trading_client.get_open_position(symbol)
        return float(position.qty)
    except Exception:
        return 0.0


def buy(symbol: str, qty: float) -> dict:
    """Submit a market buy order. Returns the order as a dict."""
    order_request = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.BUY,
        time_in_force=TimeInForce.DAY,
    )
    order = trading_client.submit_order(order_request)
    return {"id": str(order.id), "symbol": symbol, "qty": qty, "side": "BUY"}


def sell(symbol: str, qty: float) -> dict:
    """Submit a market sell order. Returns the order as a dict."""
    order_request = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    order = trading_client.submit_order(order_request)
    return {"id": str(order.id), "symbol": symbol, "qty": qty, "side": "SELL"}
