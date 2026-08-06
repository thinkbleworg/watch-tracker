"""
HMT Store Scraper

Source:
https://www.hmtwatches.store

Uses SmartBiz Product API.
"""

import json
from typing import Dict

from models import Watch

from config import STORE_API

from .base import BaseScraper


class HMTStoreScraper(BaseScraper):

    def __init__(self):

        super().__init__()

    # -----------------------------------------------------

    def scrape(self) -> Dict[str, Watch]:

        print("Fetching HMT Store...")

        products = self.fetch_products()

        watches = {}

        for product in products:

            watch = self.parse_product(product)

            if watch:

                watches[watch.id] = watch

        print(f"Found {len(watches)} products.")

        return watches

    # -----------------------------------------------------

    def fetch_products(self):

        response = self.get(STORE_API)

        data = response.json()

        #
        # API sometimes returns list directly
        #

        if isinstance(data, list):

            return data

        #
        # Future proof
        #

        if isinstance(data, dict):

            if "products" in data:

                return data["products"]

            if "items" in data:

                return data["items"]

            if "data" in data:

                return data["data"]

        return []

    # -----------------------------------------------------

    def parse_product(self, item):

        try:

            #
            # Product ID
            #

            product_id = item.get(
                "primaryProductId"
            )

            if not product_id:

                return None

            #
            # Name
            #

            name = self.clean(

                item.get("name")

            )

            #
            # Image
            #

            image = item.get(

                "productImageUrl",

                ""

            )

            #
            # Price
            #

            price = self.build_price(

                item.get(

                    "sellingPrice"

                )

            )

            ##################################################

            # Product URL

            ##################################################

            product_url = (

                "https://www.hmtwatches.store/product/"

                f"{product_id}"

            )

            ##################################################

            # Stock

            ##################################################

            stock = "Available"

            attrs = item.get(

                "additionalAttributes"

            )

            if attrs:

                try:

                    attrs = json.loads(attrs)

                except Exception:

                    attrs = {}

                #
                # SmartBiz stores OOS here
                #

                if attrs.get("isOOS", False):

                    stock = "Out of Stock"

            ##################################################

            #
            # Backup checks
            #

            if item.get(

                "currentStock",

                0

            ) == 0:

                stock = "Out of Stock"

            ##################################################

            return Watch.create(

                id=product_id,

                name=name,

                price=price,

                product_url=product_url,

                image_url=image,

                stock=stock,

                source="HMT Store",

            )

        except Exception as ex:

            print(

                "Parse Error:",

                ex

            )

            return None