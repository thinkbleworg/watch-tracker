"""
Snapshot handling.

Responsible for reading and writing product snapshots.
"""

import json
import os

from models import Watch


def load_snapshot(filename):

    if not os.path.exists(filename):
        return {}

    if os.path.getsize(filename) == 0:
        return {}

    with open(filename, "r", encoding="utf-8") as f:

        raw = json.load(f)

    watches = {}

    for url, item in raw.items():

        watches[url] = Watch.from_dict(item)

    return watches


def save_snapshot(filename, watches):

    data = {}

    for url, watch in watches.items():

        data[url] = watch.to_dict()

    with open(filename, "w", encoding="utf-8") as f:

        json.dump(
            data,
            f,
            indent=4,
            ensure_ascii=False,
        )


def snapshot_exists(filename):

    return os.path.exists(filename)


def backup_snapshot(old_file, new_file):

    if os.path.exists(old_file):

        os.replace(old_file, new_file)