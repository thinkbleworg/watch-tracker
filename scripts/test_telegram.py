"""
Sends ONE real test message to confirm your bot token
and chat id actually work. Requires real credentials
(this one deliberately ignores DRY_RUN).

Usage:
    BOT_TOKEN=xxx CHAT_ID=yyy python scripts/test_telegram.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from config import BOT_TOKEN, CHAT_ID

if not BOT_TOKEN or not CHAT_ID:
    raise SystemExit(
        "Set real BOT_TOKEN and CHAT_ID env vars first "
        "(this script always sends for real)."
    )

response = requests.post(
    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
    data={
        "chat_id": CHAT_ID,
        "text": "✅ watch-tracker test message -- if you see this, "
                "BOT_TOKEN and CHAT_ID are correct.",
    },
    timeout=30,
)

print(response.status_code)
print(response.text)
