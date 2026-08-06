import json
import os

FILE_NAME = "snapshot.json"


def load_snapshot():
    if not os.path.exists(FILE_NAME):
        return {}

    with open(FILE_NAME, "r", encoding="utf-8") as f:
        return json.load(f)


def save_snapshot(products):
    with open(FILE_NAME, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=4)