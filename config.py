"""
Configuration
"""

import os

# =====================================================
# Dry Run
# =====================================================
#
# DRY_RUN=true lets you run the full pipeline (scrape +
# compare + snapshot) and see exactly what notifications
# WOULD be sent, without needing a bot token/chat id and
# without hitting Telegram at all. See notifier.py.
#

DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"

# =====================================================
# Telegram
# =====================================================
#
# NEVER hardcode these. The workflow already injects
# them as env vars from GitHub Secrets (see
# .github/workflows/monitor.yml). Rotate your old token
# with @BotFather -- it was committed to a public repo.
#

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

if not DRY_RUN and (not BOT_TOKEN or not CHAT_ID):
    raise RuntimeError(
        "BOT_TOKEN / CHAT_ID are not set. "
        "Set them as environment variables "
        "(GitHub Secrets in CI, or a local .env "
        "loaded before running), or set DRY_RUN=true "
        "to test without Telegram."
    )

# =====================================================
# User Agent
# =====================================================

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)

# =====================================================
# HMT Store API
# =====================================================

STORE_API = (
    "https://smartpos.amazon.in/"
    "api-unauthenticated/"
    "resources/external/catalog/products"
)

STORE_HEADERS = {
    "Accept": "application/json",
    "Origin": "https://www.hmtwatches.store",
    "Referer": "https://www.hmtwatches.store/all-products",
    "User-Agent": USER_AGENT,
}

# =====================================================
# Official Website
# =====================================================

OFFICIAL_URL = "https://hmtwatches.in"

FILTER_URL = "https://hmtwatches.in/filter_products"

OFFICIAL_HEADERS = {
    "Origin": "https://hmtwatches.in",
    "Referer": "https://hmtwatches.in/mens",
    "X-Requested-With": "XMLHttpRequest",
    "User-Agent": USER_AGENT,
}

FILTER_FORM = {
    "availability_filter": "0",
    "gender_filter[]": "1",
    "brand_filter": "",
    "load_more_count": "2",
    "menu_val": ""
}

# =====================================================
# Snapshot
# =====================================================
#
# Override with SNAPSHOT_FILE=/tmp/test_snapshot.json
# when testing locally so you don't touch the real
# committed snapshot.
#

SNAPSHOT_FILE = os.getenv("SNAPSHOT_FILE", "snapshots/snapshot.json")

# =====================================================
# Retry
# =====================================================

MAX_RETRIES = 3

REQUEST_TIMEOUT = 60

# =====================================================
# Telegram Rate Limiting
# =====================================================
#
# Telegram throttles rapid consecutive sendPhoto calls
# to the same chat. Space messages out and retry on 429.
#

TELEGRAM_MIN_INTERVAL = 1.2      # seconds between messages
TELEGRAM_MAX_RETRIES = 3
