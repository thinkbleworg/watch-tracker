"""
Configuration file for Watch Tracker
"""

import os

# ===========================================
# Telegram
# ===========================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# ===========================================
# Websites
# ===========================================

HMT_STORE = "https://www.hmtwatches.store/all-products"
HMT_OFFICIAL = "https://hmtwatches.in/mens"

URLS = [
    HMT_STORE,
    HMT_OFFICIAL
]

# ===========================================
# Snapshot Files
# ===========================================

SNAPSHOT_FILE = "snapshot.json"
NEW_SNAPSHOT_FILE = "snapshot_new.json"

# ===========================================
# Browser
# ===========================================

HEADLESS = True

PAGE_TIMEOUT = 60000

WAIT_AFTER_LOAD = 3000

# ===========================================
# Telegram
# ===========================================

ENABLE_PREVIEW = False

# ===========================================
# Retry
# ===========================================

MAX_RETRIES = 3

RETRY_DELAY = 5

# ===========================================
# Date Format
# ===========================================

DATE_FORMAT = "%d-%b-%Y %I:%M:%S %p"

# ===========================================
# User Agent
# ===========================================

USER_AGENT = (
    "Mozilla/5.0 "
    "(Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 "
    "(KHTML, like Gecko) "
    "Chrome/138.0 Safari/537.36"
)