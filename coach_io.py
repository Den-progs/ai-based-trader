"""
coach_io.py — reads/writes strategy.txt, watchlist.json, crypto_watchlist.json,
and pending_signals.json (off-hours stock signals saved for daily review).
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent
STRATEGY_FILE = BASE_DIR / "strategy.txt"
WATCHLIST_FILE = BASE_DIR / "watchlist.json"
CRYPTO_WATCHLIST_FILE = BASE_DIR / "crypto_watchlist.json"
PENDING_SIGNALS_FILE = BASE_DIR / "pending_signals.json"

DEFAULT_STRATEGY = "Hold cash. Wait for a clear BUY signal with confidence >= 0.7 before entering."
DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA"]
DEFAULT_CRYPTO_WATCHLIST = [
    "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "DOGE/USD",
    "AVAX/USD", "LINK/USD", "ADA/USD", "DOT/USD", "LTC/USD",
    "BCH/USD", "UNI/USD", "AAVE/USD", "POL/USD", "ARB/USD",
]

MAX_PENDING_SIGNALS = 100  # cap so the file doesn't grow forever
_signals_lock = threading.Lock()  # prevents concurrent file writes from multiple threads


def read_strategy() -> str:
    if STRATEGY_FILE.exists():
        return STRATEGY_FILE.read_text(encoding="utf-8").strip()
    return DEFAULT_STRATEGY


def write_strategy(strategy: str) -> None:
    STRATEGY_FILE.write_text(strategy.strip(), encoding="utf-8")


def read_watchlist() -> list[str]:
    if WATCHLIST_FILE.exists():
        try:
            return json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[coach_io] Could not read watchlist.json: {e}")
    return DEFAULT_WATCHLIST


def write_watchlist(symbols: list[str]) -> None:
    WATCHLIST_FILE.write_text(json.dumps(symbols, indent=2), encoding="utf-8")


def read_crypto_watchlist() -> list[str]:
    if CRYPTO_WATCHLIST_FILE.exists():
        try:
            return json.loads(CRYPTO_WATCHLIST_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[coach_io] Could not read crypto_watchlist.json: {e}")
    return DEFAULT_CRYPTO_WATCHLIST


def write_crypto_watchlist(symbols: list[str]) -> None:
    CRYPTO_WATCHLIST_FILE.write_text(json.dumps(symbols, indent=2), encoding="utf-8")


def read_pending_signals() -> list[dict]:
    """Return off-hours stock signals saved since the last daily review."""
    if PENDING_SIGNALS_FILE.exists():
        try:
            return json.loads(PENDING_SIGNALS_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[coach_io] Could not read pending_signals.json: {e}")
    return []


def append_pending_signal(symbol: str, action: str, confidence: float, reason: str, price: float) -> None:
    """Save one off-hours signal. Thread-safe. Keeps only the last MAX_PENDING_SIGNALS entries."""
    with _signals_lock:
        signals = read_pending_signals()
        signals.append({
            "symbol": symbol,
            "action": action,
            "confidence": round(confidence, 3),
            "reason": reason,
            "price": round(price, 4),
            "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        if len(signals) > MAX_PENDING_SIGNALS:
            signals = signals[-MAX_PENDING_SIGNALS:]
        PENDING_SIGNALS_FILE.write_text(json.dumps(signals, indent=2), encoding="utf-8")


def clear_pending_signals() -> None:
    """Wipe pending signals after the daily coach has consumed them."""
    PENDING_SIGNALS_FILE.write_text("[]", encoding="utf-8")
