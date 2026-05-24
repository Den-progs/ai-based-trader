"""
news.py — fetch headlines from two sources in parallel:
  1. Alpaca News API
  2. Google News RSS  (no API key, built-in XML parser)
"""

import os
import time
import threading
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen

from alpaca.data.historical import NewsClient
from alpaca.data.requests import NewsRequest
from dotenv import load_dotenv

load_dotenv()

_alpaca_client = NewsClient(
    os.environ["ALPACA_API_KEY"],
    os.environ["ALPACA_SECRET_KEY"],
)

# Cache headlines per symbol for 5 minutes
_cache: dict[str, tuple[float, list[str]]] = {}
_cache_lock = threading.Lock()
CACHE_TTL = 300  # seconds


def _alpaca(symbol: str, n: int) -> list[str]:
    since = datetime.now(timezone.utc) - timedelta(days=2)
    try:
        resp = _alpaca_client.get_news(NewsRequest(symbols=symbol, start=since, limit=n))
        articles = resp.data.get("news", []) if resp.data else []
        return [a.headline for a in articles if a.headline]
    except Exception as e:
        print(f"[news][alpaca] {symbol}: {e}")
        return []


def _google(symbol: str, n: int) -> list[str]:
    # Build a readable query: "BTC/USD" → "BTC crypto", "AAPL" → "AAPL stock"
    if "/" in symbol:
        query = symbol.split("/")[0] + " crypto"
    else:
        query = symbol + " stock"
    url = f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=8) as resp:
            root = ET.fromstring(resp.read())
        titles = []
        for item in root.iter("item"):
            title = item.findtext("title")
            if title:
                # Google News appends " - Source Name", strip it
                titles.append(title.rsplit(" - ", 1)[0])
            if len(titles) >= n:
                break
        return titles
    except Exception as e:
        print(f"[news][google] {symbol}: {e}")
        return []


def get_headlines(symbol: str, max_headlines: int = 5) -> list[str]:
    """
    Return headlines from Alpaca + Google News, fetched in parallel.
    Cached per symbol for CACHE_TTL seconds.
    """
    now = time.time()
    with _cache_lock:
        if symbol in _cache:
            ts, cached = _cache[symbol]
            if now - ts < CACHE_TTL:
                return cached

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_alpaca = pool.submit(_alpaca, symbol, max_headlines)
        f_google = pool.submit(_google, symbol, max_headlines)

    results = []
    for f in (f_alpaca, f_google):
        try:
            results.extend(f.result())
        except Exception:
            pass

    with _cache_lock:
        _cache[symbol] = (now, results)

    return results
