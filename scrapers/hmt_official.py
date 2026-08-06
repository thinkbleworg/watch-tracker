"""
Official HMT Website Scraper

Uses:
https://hmtwatches.in/filter_products
"""

from bs4 import BeautifulSoup
from urllib.parse import urljoin
from typing import Dict

from models import Watch
from .base import BaseScraper


FILTER_URL = "https://hmtwatches.in/filter_products"

BASE_URL = "https://hmtwatches.in"

HEADERS = {

    "Origin": BASE_URL,

    "Referer": BASE_URL + "/mens",

    "X-Requested-With": "XMLHttpRequest"

}


FORM_DATA = {

    "availability_filter": "0",

    "gender_filter[]": "1",

    "brand_filter": "",

    "load_more_count": "2",

    "menu_val": ""

}


class HMTOfficialScraper(BaseScraper):

    def __init__(self):

        super().__init__()

    ##########################################################

    def scrape(self) -> Dict[str, Watch]:

        print("Fetching Official HMT...")

        response = self.post(

            FILTER_URL,

            data=FORM_DATA,

            headers=HEADERS

        )

        data = response.json()

        if not data.get("status"):

            return {}

        html = data["html"]

        soup = BeautifulSoup(

            html,

            "lxml"

        )

        watches = {}

        cards = soup.select(

            ".bc_p_item"

        )

        print(

            f"{len(cards)} watches found"

        )

        for card in cards:

            watch = self.parse_card(card)

            if watch:

                watches[watch.id] = watch

        return watches

    ##########################################################

    def parse_card(self, card):

        try:

            ##################################################

            #
            # Product URL
            #

            link = card.select_one(

                "a.bc_p_name"

            )

            if not link:

                return None

            href = link.get(

                "href"

            )

            product_url = urljoin(

                BASE_URL,

                href

            )

            ##################################################

            #
            # Product ID
            #

            product_id = href

            ##################################################

            #
            # Name
            #

            span = link.select_one(

                "span"

            )

            if not span:

                return None

            name = self.clean(

                span.get_text()

            )

            ##################################################

            #
            # Price
            #

            price_tag = card.select_one(

                ".bc_p_detail p"

            )

            price = ""

            if price_tag:

                price = self.clean(

                    price_tag.get_text()

                )

            ##################################################

            #
            # Image
            #

            image = ""

            img = card.select_one(

                "img"

            )

            if img:

                image = urljoin(

                    BASE_URL,

                    img.get(

                        "src",

                        ""

                    )

                )

            ##################################################

            #
            # Stock
            #

            stock = "Available"

            #
            # Coming Soon
            #

            if card.select_one(

                ".outofstock"

            ):

                stock = "Out of Stock"

            #
            # No Add To Cart button
            #

            if not card.select_one(

                ".fa-shopping-cart"

            ):

                stock = "Out of Stock"

            ##################################################

            return Watch.create(

                id=product_id,

                name=name,

                price=price,

                product_url=product_url,

                image_url=image,

                stock=stock,

                source="Official HMT"

            )

        except Exception as ex:

            print(

                "Parse Error:",

                ex

            )

            return None