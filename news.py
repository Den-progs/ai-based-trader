"""
news.py — fetch headlines from three sources in parallel:
  1. Alpaca News API
  2. Google News RSS  (no API key, built-in XML parser)
  3. Reddit           (public JSON API, no key needed)
"""

import os
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen

import requests
from alpaca.data.historical import NewsClient
from alpaca.data.requests import NewsRequest
from dotenv import load_dotenv

load_dotenv()

_alpaca_client = NewsClient(
    os.environ["ALPACA_API_KEY"],
    os.environ["ALPACA_SECRET_KEY"],
)

_REDDIT_HEADERS = {"User-Agent": "ai-trader-bot/1.0"}


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


def _reddit(symbol: str, n: int) -> list[str]:
    if "/" in symbol:
        query = symbol.split("/")[0]  # BTC/USD → BTC
        subreddits = ["CryptoCurrency", "CryptoMarkets"]
    else:
        query = symbol
        subreddits = ["wallstreetbets", "stocks"]

    headlines = []
    for sub in subreddits:
        try:
            url = (
                f"https://www.reddit.com/r/{sub}/search.json"
                f"?q={query}&sort=hot&limit={n}&t=day&restrict_sr=1"
            )
            resp = requests.get(url, headers=_REDDIT_HEADERS, timeout=8)
            resp.raise_for_status()
            posts = resp.json().get("data", {}).get("children", [])
            for post in posts:
                title = post.get("data", {}).get("title", "")
                if title:
                    headlines.append(f"[r/{sub}] {title}")
        except Exception as e:
            print(f"[news][reddit] r/{sub} {symbol}: {e}")
        if len(headlines) >= n:
            break

    return headlines[:n]


def get_headlines(symbol: str, max_headlines: int = 5) -> list[str]:
    """
    Return headlines from Alpaca + Google News + Reddit, fetched in parallel.
    Each source contributes up to max_headlines. Returns [] if everything fails.
    """
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_alpaca = pool.submit(_alpaca, symbol, max_headlines)
        f_google = pool.submit(_google, symbol, max_headlines)
        f_reddit = pool.submit(_reddit, symbol, max_headlines)

    results = []
    for f in (f_alpaca, f_google, f_reddit):
        try:
            results.extend(f.result())
        except Exception:
            pass
    return results
