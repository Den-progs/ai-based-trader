"""
news.py — fetch recent news headlines for a stock symbol via Alpaca.
"""

import os
from datetime import datetime, timedelta, timezone

from alpaca.data.historical import NewsClient
from alpaca.data.requests import NewsRequest
from dotenv import load_dotenv

load_dotenv()

_client = NewsClient(
    os.environ["ALPACA_API_KEY"],
    os.environ["ALPACA_SECRET_KEY"],
)


def get_headlines(symbol: str, max_headlines: int = 5) -> list[str]:
    """
    Return up to max_headlines recent news headlines for a symbol.
    Returns an empty list if the request fails or no news is found.
    """
    since = datetime.now(timezone.utc) - timedelta(days=2)
    try:
        response = _client.get_news(
            NewsRequest(
                symbols=symbol,
                start=since,
                limit=max_headlines,
            )
        )
        articles = response.data.get("news", []) if response.data else []
        return [a.headline for a in articles if a.headline]
    except Exception as e:
        print(f"[news] Could not fetch news for {symbol}: {e}")
        return []
