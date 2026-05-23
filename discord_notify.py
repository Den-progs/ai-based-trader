"""
discord_notify.py — send messages to Discord via webhook.
"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")


def send(message: str, username: str = "Trader Bot") -> None:
    """Send a plain text message to Discord. Logs to console on failure."""
    if not WEBHOOK_URL:
        print("[discord] WARNING: DISCORD_WEBHOOK_URL not set, skipping.")
        return

    try:
        response = requests.post(
            WEBHOOK_URL,
            json={"username": username, "content": message},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"[discord] Failed to send message: {e}")
