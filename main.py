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


def run_scraper(name, scraper):
    """
    Run a single scraper in isolation. If it fails,
    print the error and return (False, {}) instead of
    taking down the whole run -- one broken source
    should never silently zero out (or crash past) the
    other.
    """

    try:
        results = scraper.scrape()
        print(f"[{name}] OK -- {len(results)} watches")
        return True, results

    except Exception as ex:
        print(f"[{name}] FAILED: {ex}")
        return False, {}


def backfill_failed_source(current, previous, source_name, ok):
    """
    If a scraper failed this run, carry its watches
    forward unchanged from the previous snapshot instead
    of leaving them absent from `current`. Without this,
    a single transient failure (site timeout, API change)
    would make the comparator think every watch from that
    source was "removed" and fire a flood of false
    sold-out alerts.
    """

    if ok:
        return

    carried = 0
    for pid, watch in previous.items():
        if watch.source == source_name and pid not in current:
            current[pid] = watch
            carried += 1

    if carried:
        print(
            f"[{source_name}] scrape failed -- "
            f"carried forward {carried} watches "
            f"from the previous snapshot unchanged."
        )


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

    store_ok, store_results = run_scraper(
        "HMT Store", HMTStoreScraper()
    )
    current.update(store_results)

    official_ok, official_results = run_scraper(
        "Official HMT", HMTOfficialScraper()
    )
    current.update(official_results)

    if not store_ok and not official_ok:
        print()
        print("Both scrapers failed. Aborting without "
              "touching the snapshot so we don't wipe "
              "out good data.")
        return

    backfill_failed_source(
        current, previous, "HMT Store", store_ok
    )
    backfill_failed_source(
        current, previous, "Official HMT", official_ok
    )

    ########################################################

    available = sum(
        1 for watch in current.values()
        if watch.stock == "Available"
    )
    out_of_stock = len(current) - available

    print()
    print(f"Current Watches : {len(current)}")
    print(f"  Store    : {len(store_results)}")
    print(f"  Official : {len(official_results)}")
    print(f"Available : {available}")
    print(f"Out Of Stock : {out_of_stock}")

    ########################################################
    # Compare
    ########################################################

    comparator = Comparator()
    result = comparator.compare(previous, current)

    ########################################################
    # Update History
    ########################################################

    current = snapshot.update_history(previous, result.updated)

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

        new_available = [
            w for w in result.new if w.stock == "Available"
        ]

        print()
        print(f"Sending notifications: "
              f"{len(new_available)} new, "
              f"{len(result.sold_out)} sold out, "
              f"{len(result.back_in_stock)} back in stock, "
              f"{len(result.price_changed)} price changes")

        for watch in new_available:
            notifier.new_watch(watch)

        for watch in result.sold_out:
            notifier.sold_out(watch)

        for watch in result.back_in_stock:
            notifier.back_in_stock(watch)

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
    print(f"New Watches : {len(result.new)}")
    print(f"Removed Watches : {len(result.removed)}")
    print(f"Back In Stock : {len(result.back_in_stock)}")
    print(f"Sold Out : {len(result.sold_out)}")
    print(f"Price Changes : {len(result.price_changed)}")
    print()
    print("Snapshot Updated.")
    print("=" * 60)


if __name__ == "__main__":
    main()
