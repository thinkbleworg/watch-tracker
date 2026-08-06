"""
Main Entry Point
"""

import os
import shutil

from config import (
    SNAPSHOT_FILE,
    NEW_SNAPSHOT_FILE,
)

from scraper import Scraper

from snapshot import (
    load_snapshot,
    save_snapshot,
)

from comparator import compare

from telegram import Telegram


def main():

    telegram = Telegram()

    scraper = Scraper()

    scraper.start()

    try:

        print("=" * 60)
        print("WATCH TRACKER")
        print("=" * 60)

        if os.path.exists(SNAPSHOT_FILE):

            previous = load_snapshot(
                SNAPSHOT_FILE
            )

            print(
                f"Loaded {len(previous)} previous watches"
            )

        else:

            previous = {}

            print(
                "No previous snapshot found."
            )

        current = scraper.scrape()

        print(
            f"Scraped {len(current)} watches"
        )

        save_snapshot(
            NEW_SNAPSHOT_FILE,
            current
        )

        if len(current) == 0:

            print("Scraping failed.")

            return

        if len(previous) == 0:

            print(
                "First run. Creating baseline snapshot."
            )

            shutil.copy(
                NEW_SNAPSHOT_FILE,
                SNAPSHOT_FILE
            )

            return

        (
            new_watches,
            sold_watches,
            price_changes,
            stock_changes,
        ) = compare(
            previous,
            current,
        )

        print(
            f"New : {len(new_watches)}"
        )

        print(
            f"Sold : {len(sold_watches)}"
        )

        print(
            f"Price Changed : {len(price_changes)}"
        )

        print(
            f"Stock Changed : {len(stock_changes)}"
        )

        ##################################

        for watch in new_watches.values():

            telegram.new_watch(
                watch
            )

        ##################################

        for watch in sold_watches.values():

            telegram.sold_out(
                watch
            )

        ##################################

        for item in price_changes:

            telegram.price_changed(

                item["watch"],

                item["old_price"],

                item["new_price"]

            )

        ##################################

        for item in stock_changes:

            telegram.stock_changed(

                item["watch"],

                item["old_stock"],

                item["new_stock"]

            )

        ##################################

        shutil.copy(

            NEW_SNAPSHOT_FILE,

            SNAPSHOT_FILE

        )

        print("Snapshot Updated.")

    finally:

        scraper.stop()


if __name__ == "__main__":

    main()