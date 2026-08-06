"""
Scraper Module

Scrapes

1. https://www.hmtwatches.store/all-products

2. https://hmtwatches.in/mens
"""

import time

from playwright.sync_api import (
    sync_playwright,
    TimeoutError,
)

from urllib.parse import urljoin

from config import (
    HEADLESS,
    PAGE_TIMEOUT,
    WAIT_AFTER_LOAD,
    USER_AGENT,
    MAX_RETRIES,
    RETRY_DELAY,
)

from models import Watch


class Scraper:

    def __init__(self):

        self.browser = None

        self.page = None

    def start(self):

        self.playwright = sync_playwright().start()

        self.browser = self.playwright.chromium.launch(
            headless=HEADLESS
        )

        self.page = self.browser.new_page(
            user_agent=USER_AGENT
        )

        self.page.set_default_timeout(
            PAGE_TIMEOUT
        )

    def stop(self):

        if self.browser:

            self.browser.close()

        self.playwright.stop()

    def open(self, url):

        self.page.goto(
            url,
            wait_until="networkidle"
        )

        self.page.wait_for_timeout(
            WAIT_AFTER_LOAD
        )

    ############################################################

    def scrape_store(self):

        """
        hmtwatches.store
        """

        watches = {}

        cards = self.page.locator(
            "div.css-1n7hyxf"
        )

        print(
            f"Store : {cards.count()} cards found"
        )

        for i in range(cards.count()):

            try:

                card = cards.nth(i)

                title = card.locator(
                    '[data-testid="standardlayout-product-title-text"]'
                )

                price = card.locator(
                    '[data-testid="standardlayout-selling-price-text"]'
                )

                image = card.locator("img")

                if title.count() == 0:
                    continue

                if price.count() == 0:
                    continue

                if image.count() == 0:
                    continue

                name = title.inner_text().strip()

                selling_price = (
                    price.inner_text().strip()
                )

                image_url = image.get_attribute(
                    "src"
                )

                # Product page not exposed in HTML.
                # Image URL is used as unique key for now.

                product_url = image_url

                watch = Watch.create(

                    name=name,

                    price=selling_price,

                    product_url=product_url,

                    image_url=image_url,

                    stock="Available",

                    source="HMT Store"

                )

                watches[product_url] = watch

            except Exception as e:

                print(e)

        return watches

    ############################################################

    def scrape_official(self):

        """
        hmtwatches.in
        """

        watches = {}

        cards = self.page.locator(
            ".bc_p_item"
        )

        print(
            f"Official : {cards.count()} cards found"
        )

        for i in range(cards.count()):

            try:

                card = cards.nth(i)

                name = card.locator(
                    ".bc_p_name span"
                ).inner_text().strip()

                price = card.locator(
                    ".bc_p_detail p"
                ).inner_text().strip()

                product_link = card.locator(
                    "a.bc_p_name"
                )

                href = product_link.get_attribute(
                    "href"
                )

                href = urljoin(
                    "https://hmtwatches.in",
                    href
                )

                image = card.locator("img")

                image_url = image.get_attribute(
                    "src"
                )

                image_url = urljoin(
                    "https://hmtwatches.in",
                    image_url
                )

                stock = "Available"

                if card.locator(
                    ".fa-shopping-cart"
                ).count() == 0:

                    stock = "Out of Stock"

                watch = Watch.create(

                    name=name,

                    price=price,

                    product_url=href,

                    image_url=image_url,

                    stock=stock,

                    source="Official"

                )

                watches[href] = watch

            except Exception as e:

                print(e)

        return watches

    ############################################################

    def scrape(self):

        all_watches = {}

        websites = [

            (
                "https://www.hmtwatches.store/all-products",
                self.scrape_store,
            ),

            (
                "https://hmtwatches.in/mens",
                self.scrape_official,
            )

        ]

        for url, func in websites:

            success = False

            for retry in range(MAX_RETRIES):

                try:

                    print(
                        f"Opening {url}"
                    )

                    self.open(url)

                    watches = func()

                    all_watches.update(
                        watches
                    )

                    success = True

                    break

                except TimeoutError:

                    print(
                        f"Timeout : {retry+1}"
                    )

                    time.sleep(
                        RETRY_DELAY
                    )

                except Exception as e:

                    print(e)

                    time.sleep(
                        RETRY_DELAY
                    )

            if not success:

                print(
                    f"Failed : {url}"
                )

        return all_watches