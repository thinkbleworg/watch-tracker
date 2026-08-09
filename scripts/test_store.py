"""
Standalone test for the HMT Store scraper.
Doesn't touch Telegram or the real snapshot.

Usage:
    DRY_RUN=true python scripts/test_store.py
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scrapers import HMTStoreScraper

scraper = HMTStoreScraper()
watches = scraper.scrape()

print(f"\n{len(watches)} watches total\n")

for watch in list(watches.values())[:5]:
    print("-" * 40)
    print("id      :", watch.id)
    print("name    :", watch.name)
    print("price   :", watch.price)
    print("stock   :", watch.stock)
    print("url     :", watch.product_url)
