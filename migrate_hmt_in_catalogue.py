from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from config import load_config
from database import Database
from scrapers.hmt_official import OfficialHMTScraper


DB_PATH = Path("data/hmt_tracker.db")
BACKUP_PATH = Path("data/hmt_tracker.before_hmt_in_migration.db")
SOURCE = "hmt.in"

EXPECTED_IDS = {
    "hmt.in:1192",
    "hmt.in:1186",
    "hmt.in:1033",
    "hmt.in:1026",
    "hmt.in:1022",
    "hmt.in:751",
    "hmt.in:750",
    "hmt.in:749",
    "hmt.in:615",
    "hmt.in:612",
    "hmt.in:266",
}


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    print("=== HMT .in catalogue migration ===")
    print(f"Database: {DB_PATH}")

    # Create a one-time backup before changing anything.
    shutil.copy2(DB_PATH, BACKUP_PATH)
    print(f"Backup:   {BACKUP_PATH}")

    config = load_config()
    source_config = next(
        source for source in config.sources if source.name == SOURCE
    )

    scraper = OfficialHMTScraper(
        source_config,
        timeout_seconds=config.request_timeout_seconds,
        retries=config.request_retries,
    )

    print("\nScraping current HMT .in catalogue...")
    watches = scraper.scrape()

    actual_ids = {watch.id for watch in watches}

    print(f"Current scraper products: {len(watches)}")
    for watch in watches:
        print(f"  {watch.id} | {watch.name}")

    if actual_ids != EXPECTED_IDS:
        missing = sorted(EXPECTED_IDS - actual_ids)
        unexpected = sorted(actual_ids - EXPECTED_IDS)
        raise SystemExit(
            "\nABORTED: scraper identity set is not exactly what we expect.\n"
            f"Missing:    {missing}\n"
            f"Unexpected: {unexpected}\n"
            "No database changes were made. The backup is still available."
        )

    db = Database(DB_PATH)

    with db.connection() as connection:
        old_count = connection.execute(
            "SELECT COUNT(*) FROM watches WHERE source = ?",
            (SOURCE,),
        ).fetchone()[0]

        store_count = connection.execute(
            "SELECT COUNT(*) FROM watches WHERE source = 'hmt.store'"
        ).fetchone()[0]

        alert_state_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM alert_states
            WHERE watch_id IN (
                SELECT id FROM watches WHERE source = ?
            )
            """,
            (SOURCE,),
        ).fetchone()[0]

        alert_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM alerts
            WHERE watch_id IN (
                SELECT id FROM watches WHERE source = ?
            )
            """,
            (SOURCE,),
        ).fetchone()[0]

        print("\nBefore migration:")
        print(f"  HMT .in watches:     {old_count}")
        print(f"  HMT .store watches:  {store_count}")
        print(f"  HMT .in alert state: {alert_state_count}")
        print(f"  HMT .in alerts:      {alert_count}")

        if old_count != 140:
            raise SystemExit(
                f"\nABORTED: expected 140 legacy hmt.in rows, found {old_count}."
            )

        if store_count != 271:
            raise SystemExit(
                f"\nABORTED: expected 271 hmt.store rows, found {store_count}."
            )

        if alert_state_count or alert_count:
            raise SystemExit(
                "\nABORTED: legacy hmt.in rows have dependent alert records.\n"
                f"alert_states={alert_state_count}, alerts={alert_count}\n"
                "No database changes were made."
            )

        # Delete only the legacy HMT .in catalogue.
        connection.execute(
            "DELETE FROM watches WHERE source = ?",
            (SOURCE,),
        )

        # Insert the currently scraped stable-ID catalogue.
        for watch in watches:
            connection.execute(
                """
                INSERT INTO watches (
                    id,
                    source,
                    name,
                    model_number,
                    sku,
                    price,
                    mrp,
                    product_url,
                    image_url,
                    in_stock,
                    stock_count,
                    category,
                    collection,
                    gender,
                    first_seen,
                    last_seen,
                    last_stock_check
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?
                )
                """,
                db._watch_values(watch),
            )

        new_in_count = connection.execute(
            "SELECT COUNT(*) FROM watches WHERE source = ?",
            (SOURCE,),
        ).fetchone()[0]

        new_store_count = connection.execute(
            "SELECT COUNT(*) FROM watches WHERE source = 'hmt.store'"
        ).fetchone()[0]

        total_count = connection.execute(
            "SELECT COUNT(*) FROM watches"
        ).fetchone()[0]

        if new_in_count != 11:
            raise RuntimeError(
                f"Migration verification failed: hmt.in count is {new_in_count}, expected 11."
            )

        if new_store_count != 271:
            raise RuntimeError(
                f"Migration verification failed: hmt.store count is {new_store_count}, expected 271."
            )

        if total_count != 282:
            raise RuntimeError(
                f"Migration verification failed: total count is {total_count}, expected 282."
            )

    print("\nMigration completed successfully.")
    print("After migration:")
    print("  HMT .in watches:     11")
    print("  HMT .store watches:  271")
    print("  TOTAL watches:       282")
    print(f"\nBackup retained at: {BACKUP_PATH}")
    print("\nDo NOT run the tracker yet if you want to review this result first.")


if __name__ == "__main__":
    main()
