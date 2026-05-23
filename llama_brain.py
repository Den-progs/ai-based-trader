"""
llama_brain.py — ask local Llama 3.2 whether to buy, sell, or hold a stock.
Uses Ollama's HTTP API (must be running locally on port 11434).
"""

import json
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.2:3b"

PROMPT_TEMPLATE = """You are a stock trading assistant. Based on the information below, decide whether to BUY, SELL, or HOLD the stock.

Stock: {symbol}
Current price: ${price}
Recent news headlines:
{news}

Respond ONLY with a JSON object in this exact format (no extra text):
{{
  "action": "BUY" | "SELL" | "HOLD",
  "confidence": 0.0 to 1.0,
  "reason": "one short sentence"
}}"""


def ask_llama(symbol: str, price: float, news: list[str]) -> dict:
    """
    Ask Llama to decide BUY / SELL / HOLD for a symbol.
    Returns a dict with keys: action, confidence, reason.
    Raises ValueError if the response can't be parsed.
    """
    news_text = "\n".join(f"- {h}" for h in news) if news else "- No recent news"

    prompt = PROMPT_TEMPLATE.format(
        symbol=symbol,
        price=f"{price:.2f}",
        news=news_text,
    )

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=30)
        response.raise_for_status()
    except requests.RequestException as e:
        raise ConnectionError(f"Ollama request failed: {e}") from e

    raw_text = response.json().get("response", "")

    # Extract JSON from the response (Llama sometimes adds extra text)
    start = raw_text.find("{")
    end = raw_text.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON found in Llama response: {raw_text!r}")

    try:
        result = json.loads(raw_text[start:end])
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from Llama: {raw_text!r}") from e

    # Validate required fields
    action = result.get("action", "").upper()
    if action not in ("BUY", "SELL", "HOLD"):
        raise ValueError(f"Unexpected action value: {action!r}")

    result["action"] = action
    result.setdefault("confidence", 0.5)
    result.setdefault("reason", "no reason given")

    return result


# Quick manual test
if __name__ == "__main__":
    test_news = [
        "Apple beats earnings expectations for Q1",
        "iPhone sales up 12% year over year",
    ]
    decision = ask_llama("AAPL", 189.50, test_news)
    print("Decision:", json.dumps(decision, indent=2))
