"""
coach_io.py — reads/writes strategy.txt and watchlist.json
"""

import json
from pathlib import Path

BASE_DIR = Path(__file__).parent
STRATEGY_FILE = BASE_DIR / "strategy.txt"
WATCHLIST_FILE = BASE_DIR / "watchlist.json"

DEFAULT_STRATEGY = "Hold cash. Wait for a clear BUY signal with confidence >= 0.7 before entering."
DEFAULT_WATCHLIST = ["AAPL", "MSFT", "NVDA"]


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
