"""
HMT Watch Tracker
Main Entry Point

Scope (by design): only Available watches are tracked at
all. Out-of-stock listings are discarded before comparison
and never persisted to the snapshot. The only alert this
sends is "a watch is available now that wasn't in the
previous check" -- covers both a genuinely brand-new
product and a previously-tracked one coming back in stock.
Sold-out / price-change notifications are intentionally
not sent.
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
    source vanished, and next run's diff logic would treat
    a real restock as a false "new" alert.
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
    # Drop everything that isn't Available. Out-of-stock
    # watches are not tracked, not persisted, not compared.
    ########################################################

    scraped_total = len(current)

    current = {
        pid: watch
        for pid, watch in current.items()
        if watch.stock == "Available"
    }

    print()
    print(f"Scraped Total : {scraped_total}")
    print(f"  Store    : {len(store_results)}")
    print(f"  Official : {len(official_results)}")
    print(f"Available (tracked) : {len(current)}")
    print(f"Discarded (out of stock) : "
          f"{scraped_total - len(current)}")

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
    # Notifications -- new (available) watches only
    ########################################################

    if first_run:
        print()
        print("First run detected.")
        print("Snapshot created.")
        print("Notifications skipped.")
    else:
        notifier = Notifier()

        print()
        print(f"Sending notifications: "
              f"{len(result.new)} new watch(es)")

        for watch in result.new:
            notifier.new_watch(watch)

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
    print(f"New Watches Alerted : {len(result.new)}")
    print(f"No Longer Available/Listed : {len(result.removed)}")
    print()
    print("Snapshot Updated.")
    print("=" * 60)


if __name__ == "__main__":
    main()
