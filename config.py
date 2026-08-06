"""
Configuration
"""

import os

# =====================================================
# Telegram
# =====================================================

BOT_TOKEN = "8964670457:AAGKE0Y30aljqAtcSWcJb7L4_f9tvYWjtdg"
CHAT_ID = "1124775866"

#BOT_TOKEN = os.getenv("BOT_TOKEN")
#CHAT_ID = os.getenv("CHAT_ID")

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

SNAPSHOT_FILE = "snapshots/snapshot.json"

# =====================================================
# Retry
# =====================================================

MAX_RETRIES = 3

REQUEST_TIMEOUT = 60