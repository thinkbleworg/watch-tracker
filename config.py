"""
Configuration
"""

import os

# ===============================
# Telegram
# ===============================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ===============================
# HMT Store API
# ===============================

STORE_API = (
    "https://smartpos.amazon.in/"
    "api-unauthenticated/"
    "resources/external/catalog/products"
)

STORE_HEADERS = {

    "accept": "application/json",

    "origin": "https://www.hmtwatches.store",

    "referer": "https://www.hmtwatches.store/",

    "user-agent":
        (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/138.0 Safari/537.36"
        )
}

# ===============================
# Official Website
# ===============================

OFFICIAL_URL = "https://hmtwatches.in/mens"

# ===============================
# Snapshot
# ===============================

SNAPSHOT_FILE = "snapshots/snapshot.json"

# ===============================
# Retry
# ===============================

MAX_RETRIES = 3

REQUEST_TIMEOUT = 60

# ===============================
# Browser
# ===============================

HEADLESS = True

PAGE_TIMEOUT = 60000