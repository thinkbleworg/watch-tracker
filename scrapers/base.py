"""
scraper.py
Part 1

API based scraper for

1. https://www.hmtwatches.store
2. https://hmtwatches.in

"""

import json
import requests

from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

from models import Watch

from config import USER_AGENT


STORE_API = (
    "https://smartpos.amazon.in/"
    "api-unauthenticated/"
    "resources/external/catalog/products"
)


STORE_HEADERS = {

    "User-Agent": USER_AGENT,

    "Accept": "application/json",

    "Origin": "https://www.hmtwatches.store",

    "Referer": "https://www.hmtwatches.store/all-products"

}


class Scraper:

    def __init__(self):

        self.products = {}

    ##########################################################

    def scrape_store(self):

        """
        Scrape SmartBiz API

        No HTML parsing required.
        """

        print(
            "Loading Store Products..."
        )

        response = requests.get(

            STORE_API,

            headers=STORE_HEADERS,

            timeout=60

        )

        response.raise_for_status()

        items = response.json()

        print(

            f"{len(items)} products received"

        )

        for item in items:

            try:

                watch = self.make_store_watch(
                    item
                )

                self.products[
                    watch.product_url
                ] = watch

            except Exception as e:

                print(e)

    ##########################################################

    def make_store_watch(

        self,

        item

    ):

        attrs = {}

        try:

            attrs = json.loads(

                item.get(
                    "additionalAttributes",
                    "{}"
                )

            )

        except:

            pass

        is_oos = attrs.get(
            "isOOS",
            False
        )

        stock = (
            "Out of Stock"
            if is_oos
            else "Available"
        )

        product_id = (

            item.get(
                "primaryProductId"
            )

            or

            item.get("sku")

        )

        product_url = (

            "https://www.hmtwatches.store/product/"

            + product_id

        )

        return Watch.create(

            name=item["name"],

            price=f"₹{item['sellingPrice']}",

            product_url=product_url,

            image_url=item[
                "productImageUrl"
            ],

            stock=stock,

            source="HMT Store"

        )

    ##########################################################

    def start_browser(self):

        self.playwright = sync_playwright().start()

        self.browser = self.playwright.chromium.launch(

            headless=True

        )

        self.page = self.browser.new_page(

            user_agent=USER_AGENT

        )

    ##########################################################

    def close_browser(self):

        self.browser.close()

        self.playwright.stop()

##########################################################

    def scrape_official(self):

        """
        Scrape

        https://hmtwatches.in/mens

        using Playwright.
        """

        print(
            "Loading Official HMT..."
        )

        self.start_browser()

        self.page.goto(

            "https://hmtwatches.in/mens",

            wait_until="networkidle"

        )

        self.page.wait_for_selector(

            ".bc_p_item",

            timeout=30000

        )

        cards = self.page.locator(

            ".bc_p_item"

        )

        print(

            f"{cards.count()} watches found"

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

                href = card.locator(

                    "a.bc_p_name"

                ).get_attribute("href")

                href = urljoin(

                    "https://hmtwatches.in",

                    href

                )

                image = card.locator(

                    "img"

                ).get_attribute("src")

                image = urljoin(

                    "https://hmtwatches.in",

                    image

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

                    image_url=image,

                    stock=stock,

                    source="Official"

                )

                self.products[href] = watch

            except Exception as e:

                print(e)

        self.close_browser()

##########################################################

    def scrape(self):

        self.products = {}

        self.scrape_store()

        self.scrape_official()

        print(

            f"Total Products : {len(self.products)}"

        )

        return self.products