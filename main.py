from config import URLS

from scraper import scrape_all
from snapshot import load_snapshot
from snapshot import save_snapshot
from comparator import compare
from telegram import send_message


def main():

    print("Loading snapshot...")

    old_products = load_snapshot()

    print("Scraping websites...")

    current_products = scrape_all(URLS)

    print(f"Current products: {len(current_products)}")

    new_watches, sold_watches = compare(
        old_products,
        current_products
    )

    if new_watches:

        message = "🟢 NEW WATCHES\n\n"

        for watch in new_watches.values():

            message += f"{watch['name']}\n"

            message += f"{watch['url']}\n\n"

        send_message(message)

        print("New watches alert sent")

    if sold_watches:

        message = "🔴 SOLD OUT\n\n"

        for watch in sold_watches.values():

            message += f"{watch['name']}\n"

            message += f"{watch['url']}\n\n"

        send_message(message)

        print("Sold out alert sent")

    save_snapshot(current_products)

    print("Snapshot updated")


if __name__ == "__main__":
    main()