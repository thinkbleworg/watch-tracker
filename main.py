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

    print(f"Previous Snapshot : {len(previous)} watches")

    ########################################################
    # Scrape Websites
    ########################################################

    current = {}

    #
    # HMT Store
    #

    store = HMTStoreScraper()

    current.update(
        store.scrape()
    )

    #
    # Official Website
    #

    official = HMTOfficialScraper()

    current.update(
        official.scrape()
    )

    print(f"Current Watches : {len(current)}")

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
    # Send Notifications
    ########################################################

    notifier = Notifier()

    notifier.send_result(
        result
    )

    ########################################################
    # Save Snapshot
    ########################################################

    snapshot.save(
        current
    )

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