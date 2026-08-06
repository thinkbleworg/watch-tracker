"""
Compares two snapshots.

Detects:
1. New Watches
2. Sold Out Watches
3. Price Changes
4. Stock Changes
"""

from typing import Dict

from models import Watch


def compare(
    previous: Dict[str, Watch],
    current: Dict[str, Watch]
):

    previous_urls = set(previous.keys())
    current_urls = set(current.keys())

    new_urls = current_urls - previous_urls
    sold_urls = previous_urls - current_urls
    common_urls = previous_urls.intersection(current_urls)

    new_watches = {}
    sold_watches = {}

    price_changes = []
    stock_changes = []

    for url in new_urls:
        new_watches[url] = current[url]

    for url in sold_urls:
        sold_watches[url] = previous[url]

    for url in common_urls:

        old_watch = previous[url]
        new_watch = current[url]

        if old_watch.price != new_watch.price:

            price_changes.append(
                {
                    "watch": new_watch,
                    "old_price": old_watch.price,
                    "new_price": new_watch.price,
                }
            )

        if old_watch.stock != new_watch.stock:

            stock_changes.append(
                {
                    "watch": new_watch,
                    "old_stock": old_watch.stock,
                    "new_stock": new_watch.stock,
                }
            )

    return (
        new_watches,
        sold_watches,
        price_changes,
        stock_changes,
    )