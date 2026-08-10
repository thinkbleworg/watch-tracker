"""
Snapshot Manager

Responsible for:
- Loading snapshot
- Saving snapshot
- Preserving watch history
"""

import json
from pathlib import Path

from config import SNAPSHOT_FILE
from models import Watch
from timeutils import now_ist_iso


class SnapshotManager:

    def __init__(self):
        self.snapshot = {}

    # --------------------------------------------------------
    # Load Snapshot
    # --------------------------------------------------------

    def load(self):

        path = Path(SNAPSHOT_FILE)

        if not path.exists():
            self.snapshot = {}
            return self.snapshot

        if path.stat().st_size == 0:
            self.snapshot = {}
            return self.snapshot

        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        self.snapshot = {}

        for product_id, item in raw.items():
            self.snapshot[product_id] = Watch.from_dict(item)

        return self.snapshot

    # --------------------------------------------------------
    # Save Snapshot
    # --------------------------------------------------------

    def save(self, watches):

        data = {}

        for product_id, watch in watches.items():
            data[product_id] = watch.to_dict()

        with open(
            SNAPSHOT_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                data,
                f,
                indent=4,
                ensure_ascii=False,
            )

    # --------------------------------------------------------
    # Update History
    # --------------------------------------------------------

    def update_history(
        self,
        previous,
        current,
    ):
        """
        Preserve historical information.

        Keeps:
            - first_seen
            - last_seen
            - last_available
        """

        now = now_ist_iso()

        for product_id, watch in current.items():

            if product_id not in previous:
                continue

            old = previous[product_id]

            # Preserve first appearance
            watch.first_seen = old.first_seen

            # Always update last seen
            watch.last_seen = now

            # Update last available only if currently available
            if watch.stock == "Available":
                watch.last_available = now
            else:
                watch.last_available = old.last_available

        return current

    # --------------------------------------------------------
    # Exists?
    # --------------------------------------------------------

    def exists(self):

        return Path(SNAPSHOT_FILE).exists()

    # --------------------------------------------------------
    # Delete Snapshot
    # --------------------------------------------------------

    def delete(self):

        path = Path(SNAPSHOT_FILE)

        if path.exists():
            path.unlink()

    # --------------------------------------------------------
    # Count Watches
    # --------------------------------------------------------

    def count(self):

        return len(self.snapshot)