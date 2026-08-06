"""
HMT Watch Tracker

Main Entry Point
"""

from compare import Comparator
from notifier import Notifier

from scrapers import (
    HMTStoreScraper,
    HMTOfficialScraper,
)

from storage import SnapshotManager


def main():

    print("=" * 60)
    print("HMT WATCH TRACKER")
    print("=" * 60)

    ########################################################
    # Load Previous Snapshot
    ########################################################

    snapshot = SnapshotManager()

    previous = snapshot.load()

    first_run = len(previous) == 0

    print(f"Previous Snapshot : {len(previous)} watches")

    ########################################################
    # Scrape Websites
    ########################################################

    current = {}

    #
    # HMT Store
    #

    store = HMTStoreScraper()

    current.update(store.scrape())

    #
    # Official Website
    #

    official = HMTOfficialScraper()

    current.update(official.scrape())

    ########################################################

    available = sum(
        1
        for watch in current.values()
        if watch.stock == "Available"
    )

    out_of_stock = len(current) - available

    print()

    print(f"Current Watches : {len(current)}")
    print(f"Available       : {available}")
    print(f"Out Of Stock    : {out_of_stock}")

    ########################################################
    # Compare
    ########################################################

    comparator = Comparator()

    result = comparator.compare(
        previous,
        current
    )

    ########################################################
    # Update History
    ########################################################

    current = snapshot.update_history(
        previous,
        result.updated
    )

    ########################################################
    # Notifications
    ########################################################

    if first_run:

        print()
        print("First run detected.")
        print("Snapshot created.")
        print("Notifications skipped.")

    else:

        notifier = Notifier()

        #
        # NEW WATCHES
        #

        for watch in result.new:

            if watch.stock == "Available":

                notifier.new_watch(watch)

        #
        # SOLD OUT
        #

        for watch in result.sold_out:

            notifier.sold_out(watch)

        #
        # BACK IN STOCK
        #

        for watch in result.back_in_stock:

            notifier.back_in_stock(watch)

        #
        # PRICE CHANGE
        #

        for item in result.price_changed:

            notifier.price_changed(

                item["watch"],

                item["old_price"],

                item["new_price"]

            )

    ########################################################
    # Save Snapshot
    ########################################################

    snapshot.save(current)

    ########################################################
    # Summary
    ########################################################

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    print(f"New Watches      : {len(result.new)}")
    print(f"Removed Watches  : {len(result.removed)}")
    print(f"Back In Stock    : {len(result.back_in_stock)}")
    print(f"Sold Out         : {len(result.sold_out)}")
    print(f"Price Changes    : {len(result.price_changed)}")

    print()

    print("Snapshot Updated.")

    print("=" * 60)


if __name__ == "__main__":
    main()