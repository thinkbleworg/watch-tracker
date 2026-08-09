"""
Official HMT Website Scraper

Uses:
https://hmtwatches.in/filter_products
"""

import re
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

#
# Patterns for a real, stable, numeric product id
# hiding somewhere in the card's markup (data
# attributes on the card itself, or on an
# "add to cart" / wishlist button). Checked in
# order; first match wins.
#
STABLE_ID_ATTRS = [
    "data-id",
    "data-product-id",
    "data-pid",
    "data-item-id",
    "data-productid",
]

#
# Fallback: pull a numeric id out of an inline
# onclick handler, e.g. onclick="addcart(1234)"
#
ONCLICK_ID_RE = re.compile(r"\((\d{2,})[,)]")


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

        soup = BeautifulSoup(html, "lxml")

        watches = {}

        cards = soup.select(".bc_p_item")

        print(f"{len(cards)} watches found")

        for card in cards:
            watch = self.parse_card(card)
            if watch:
                watches[watch.id] = watch

        return watches

    ##########################################################

    def find_stable_id(self, card, link, name):
        """
        The product URL on this site is a Laravel
        encrypted payload that changes on every
        single request (random IV each time it's
        encrypted) -- it CANNOT be used as a stable
        identity key, or every watch looks "new" on
        every run.

        Try to find a real, stable id in the markup
        first. If none exists, fall back to a slug
        built from the product name, which is the
        most stable field this page actually gives us.
        """

        #
        # 1. Direct data-* attributes, anywhere
        #    inside the card.
        #
        for tag in card.find_all(True):
            for attr in STABLE_ID_ATTRS:
                value = tag.get(attr)
                if value and str(value).strip():
                    return f"official:{value.strip()}"

        #
        # 2. Numeric id inside an onclick handler
        #    (common pattern: addcart(123),
        #    addWishlist(123)).
        #
        for tag in card.find_all(onclick=True):
            match = ONCLICK_ID_RE.search(tag["onclick"])
            if match:
                return f"official:{match.group(1)}"

        #
        # 3. Fallback -- slugify the product name.
        #    Not perfect (two variants with an
        #    identical displayed name would collide),
        #    but it is STABLE, which is what actually
        #    matters for "new watch" detection. This
        #    fixes the every-watch-is-new bug even if
        #    steps 1/2 find nothing.
        #
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        return f"official:slug:{slug}"

    ##########################################################

    def parse_card(self, card):

        try:

            ##################################################
            # Product URL
            ##################################################

            link = card.select_one("a.bc_p_name")
            if not link:
                return None

            href = link.get("href")
            product_url = urljoin(BASE_URL, href)

            ##################################################
            # Name
            ##################################################

            span = link.select_one("span")
            if not span:
                return None

            name = self.clean(span.get_text())

            ##################################################
            # Product ID (stable -- see find_stable_id)
            ##################################################

            product_id = self.find_stable_id(card, link, name)

            ##################################################
            # Price
            ##################################################

            price_tag = card.select_one(".bc_p_detail p")

            price = ""
            if price_tag:
                price = self.clean(price_tag.get_text())

            ##################################################
            # Image
            ##################################################

            image = ""
            img = card.select_one("img")
            if img:
                image = urljoin(BASE_URL, img.get("src", ""))

            ##################################################
            # Stock
            ##################################################

            stock = "Available"

            # Coming Soon
            if card.select_one(".outofstock"):
                stock = "Out of Stock"

            # No Add To Cart button
            if not card.select_one(".fa-shopping-cart"):
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
            print("Parse Error:", ex)
            return None
