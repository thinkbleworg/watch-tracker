"""
HMT Store Scraper

Source:
https://www.hmtwatches.store

Uses SmartBiz Product API.
"""

from typing import Dict, List

from models import Watch

from config import (
    STORE_API,
    STORE_HEADERS,
)

from .base import BaseScraper


class HMTStoreScraper(BaseScraper):

    SHOP_ID = 48236

    PAGE_SIZE = 10

    def __init__(self):

        super().__init__()

    # -------------------------------------------------------------

    def scrape(self) -> Dict[str, Watch]:

        print("Fetching HMT Store...")

        products = self.fetch_products()

        watches = {}

        for item in products:

            try:

                watch = self.parse_product(item)

                if watch is None:
                    continue

                #
                # Deduplicate
                #

                watches[watch.id] = watch

            except Exception as ex:

                print(
                    "Parse Error:",
                    ex
                )

        print(
            f"Found {len(watches)} store products."
        )

        return watches

    # -------------------------------------------------------------

    def fetch_products(self) -> List[dict]:

        """
        Downloads every page
        from SmartBiz API.
        """

        all_products = []

        offset = 0

        while True:

            payload = {

                "shopId": self.SHOP_ID,

                "filter": {

                    "division": None,

                    "isBestSeller": None

                },

                "offset": offset,

                "limit": self.PAGE_SIZE

            }

            response = self.post(

                STORE_API,

                headers=STORE_HEADERS,

                json=payload

            )

            products = response.json()

            #
            # API returns []
            # when no more pages.
            #

            if not products:

                break

            print(

                f"Offset {offset}"

                f" -> "

                f"{len(products)} products"

            )

            all_products.extend(

                products

            )

            #
            # Last page
            #

            if len(products) < self.PAGE_SIZE:

                break

            offset += self.PAGE_SIZE

        print(

            f"Downloaded "

            f"{len(all_products)} "

            f"products"

        )

        return all_products

    # -------------------------------------------------------------

    def parse_product(

        self,

        item

    ) -> Watch | None:
    
        """
        Converts SmartBiz JSON
        into Watch model.
        """

        #
        # Product ID
        #

        product_id = (
            item.get("primaryProductId")
            or item.get("sku")
        )

        if not product_id:
            return None

        #
        # Name
        #

        name = self.clean(
            item.get("name", "")
        )

        #
        # Price
        #

        price = self.build_price(
            item.get("sellingPrice")
        )

        #
        # Image
        #

        image = item.get(
            "productImageUrl",
            ""
        )

        #
        # Product URL
        #

        product_url = (
            "https://www.hmtwatches.store/product/"
            f"{product_id}"
        )

        ####################################################
        # Stock
        ####################################################

        stock = "Out of Stock"

        try:

            availability = (
                item["buyingOptions"]
                    ["singlePurchase"]
                    ["availability"]
            )

            if availability.get(
                "isBuyable",
                False
            ):
                stock = "Available"

        except Exception:
            pass

        ####################################################
        # Variant Handling
        ####################################################

        variants = item.get(
            "variantsDimensions",
            []
        )

        #
        # If variant has image,
        # prefer variant image.
        #

        if variants:

            first = variants[0]

            if first.get("imageUrl"):

                image = first["imageUrl"]

        ####################################################

        return Watch.create(

            id=product_id,

            name=name,

            price=price,

            product_url=product_url,

            image_url=image,

            stock=stock,

            source="HMT Store",

        )