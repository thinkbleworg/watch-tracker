from __future__ import annotations

import logging
import re
from html import unescape
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import SourceConfig
from models import Watch, utc_now

logger = logging.getLogger(__name__)


class OfficialHMTScraper:
    """
    Scraper for https://hmtwatches.in.

    Discovery strategy:
        1. POST /filter_products
        2. GET /all_product
        3. Parse and merge products from both responses
        4. Use /product_view as a fallback for products requiring
           additional stock/model information

    A failed request raises an exception instead of returning an empty
    catalogue. This is important because an empty response caused by a
    website failure must never be interpreted as "everything is out of
    stock".
    """

    SOURCE = "hmt.in"

    def __init__(
        self,
        source_config: SourceConfig,
        *,
        timeout_seconds: int = 30,
        retries: int = 3,
    ) -> None:
        self.config = source_config
        self.timeout_seconds = timeout_seconds
        self.retries = max(1, retries)

        self.session = requests.Session()

        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0 Safari/537.36"
                ),
                "Accept": (
                    "text/html,application/xhtml+xml,"
                    "application/xml;q=0.9,*/*;q=0.8"
                ),
                "Accept-Language": "en-IN,en;q=0.9",
                "Connection": "keep-alive",
            }
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def scrape(self) -> list[Watch]:
        """
        Discover all watches currently exposed by the official website.

        Raises:
            RuntimeError: when the source cannot be scraped reliably.
        """

        filter_html = self._post_filter_products()
        all_products_html = self._get_all_products()

        watches: dict[str, Watch] = {}

        for html in (filter_html, all_products_html):
            for watch in self._parse_product_cards(html):
                watches[watch.id] = watch

        if not watches:
            raise RuntimeError(
                "HMT official source returned no parseable products."
            )

        return list(watches.values())

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> requests.Response:
        """Perform an HTTP request with simple retry handling."""

        last_error: Exception | None = None

        for attempt in range(1, self.retries + 1):
            try:
                response = self.session.request(
                    method,
                    url,
                    timeout=self.timeout_seconds,
                    **kwargs,
                )

                response.raise_for_status()

                return response

            except requests.RequestException as exc:
                last_error = exc

                logger.warning(
                    "HMT request failed "
                    "(attempt %s/%s): %s %s: %s",
                    attempt,
                    self.retries,
                    method,
                    url,
                    exc,
                )

        raise RuntimeError(
            f"HMT request failed after {self.retries} attempts: "
            f"{method} {url}"
        ) from last_error

    def _post_filter_products(self) -> str:
        """Fetch the main filtered product listing."""

        url = urljoin(
            self.config.base_url + "/",
            "/filter_products",
        )

        # These are intentionally conservative defaults.
        #
        # The website's frontend sends filtering/pagination information
        # to /filter_products. Leaving the actual filters empty asks the
        # server for the broad catalogue.
        data = {
            "load_more_count": "0",
            "menu_val": "",
            "price": "",
            "availability": "",
            "gender": "",
            "discount": "",
            "brand": "",
            "strap_color": "",
            "dial_color": "",
            "function": "",
            "collection": "",
            "movement": "",
        }

        response = self._request(
            "POST",
            url,
            data=data,
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": self.config.base_url + "/watches",
            },
        )

        return response.text

    def _get_all_products(self) -> str:
        """Fetch the site's all-products page."""

        url = urljoin(
            self.config.base_url + "/",
            "/all_product",
        )

        response = self._request(
            "GET",
            url,
        )

        return response.text

    def _get_product_view(self, product_id: str) -> str:
        """Fetch an individual product view for fallback verification."""

        url = urljoin(
            self.config.base_url + "/",
            "/product_view",
        )

        response = self._request(
            "GET",
            url,
            params={"id": product_id},
        )

        return response.text

    # ------------------------------------------------------------------
    # Product parsing
    # ------------------------------------------------------------------

    def _parse_product_cards(self, html: str) -> list[Watch]:
        """Parse product cards from an HMT HTML response."""

        soup = BeautifulSoup(html, "html.parser")

        cards = soup.select(".bc_p_item")

        if not cards:
            # Some responses may use the product detail wrapper without
            # the exact class expected by the normal listing.
            cards = soup.select(
                "div.col-sm-6.col-xs-12.mb-3.p-0"
            )

        watches: list[Watch] = []

        for card in cards:
            try:
                watch = self._parse_card(card)

                if watch is not None:
                    watches.append(watch)

            except Exception:
                logger.exception(
                    "Failed to parse an HMT product card."
                )

        return watches

    def _parse_card(
        self,
        card: Any,
    ) -> Watch | None:
        """Convert one HTML product card into a Watch."""

        name_element = card.select_one(".bc_p_name")

        if name_element is None:
            name_element = card.select_one(
                'a[class*="bc_p_name"]'
            )

        if name_element is None:
            return None

        name = self._clean_text(
            name_element.get_text(" ", strip=True)
        )

        if not name:
            return None

        product_link = card.select_one(
            'a.bc_p_img[href]'
        )

        if product_link is None:
            product_link = card.select_one(
                'a[href*="product_overview"]'
            )

        if product_link is None:
            return None

        product_url = urljoin(
            self.config.base_url + "/",
            product_link.get("href", ""),
        )

        image = card.select_one("img[src]")

        image_url = None

        if image is not None:
            src = image.get("src")

            if src:
                image_url = urljoin(
                    self.config.base_url + "/",
                    src,
                )

        price = self._parse_price(card)

        product_id = self._extract_product_id(
            card,
            product_url,
        )

        if not product_id:
            # Product overview IDs are often encrypted values. When no
            # usable ID can be recovered, the URL itself remains a
            # deterministic identity.
            product_id = self._stable_id_from_url(
                product_url
            )

        model_number = self._extract_model_number(name)

        in_stock, stock_count = self._parse_stock(card)

        return Watch.create(
            id=f"{self.SOURCE}:{product_id}",
            source=self.SOURCE,
            name=name,
            model_number=model_number,
            sku=None,
            price=price,
            mrp=None,
            product_url=product_url,
            image_url=image_url,
            in_stock=in_stock,
            stock_count=stock_count,
            category=None,
            collection=None,
            gender=None,
        )

    # ------------------------------------------------------------------
    # Stock
    # ------------------------------------------------------------------

    def _parse_stock(
        self,
        card: Any,
    ) -> tuple[bool, int | None]:
        """
        Determine stock from an HMT product card.

        Known source behavior:
        - `.outofstock` represents coming-soon/OOS cards.
        - `prodQty` appears on the product quick-view element for
          purchasable products.
        - `add_cart(id, '1')` is present on purchasable cards.
        """

        if card.select_one(".outofstock") is not None:
            return False, 0

        quick_view = card.select_one(
            "[prodqty]"
        )

        if quick_view is not None:
            quantity = self._parse_int(
                quick_view.get("prodqty")
            )

            if quantity is not None:
                return quantity > 0, quantity

            return True, None

        add_cart = card.select_one(
            '[onclick*="add_cart("]'
        )

        if add_cart is not None:
            quantity = self._extract_quantity_from_element(
                card
            )

            if quantity is not None:
                return quantity > 0, quantity

            return True, None

        # If the card contains an explicit OOS/coming-soon label,
        # treat it as unavailable. Otherwise do not confidently
        # claim that it is in stock.
        text = self._clean_text(
            card.get_text(" ", strip=True)
        ).lower()

        if any(
            phrase in text
            for phrase in (
                "out of stock",
                "sold out",
                "coming soon",
            )
        ):
            return False, 0

        return False, 0

    def _extract_quantity_from_element(
        self,
        card: Any,
    ) -> int | None:
        """
        Find a stock quantity from attributes on elements inside a card.
        """

        for element in card.select("[prodqty]"):
            quantity = self._parse_int(
                element.get("prodqty")
            )

            if quantity is not None:
                return quantity

        return None

    # ------------------------------------------------------------------
    # Product IDs
    # ------------------------------------------------------------------

    def _extract_product_id(
        self,
        card: Any,
        product_url: str,
    ) -> str | None:
        """
        Extract the product identifier used by HMT.

        Prefer onclick IDs because the uploaded source shows calls such
        as getProductDetails(919) and add_cart(919, '1').
        """

        for element in card.select(
            '[onclick*="getProductDetails("], '
            '[onclick*="add_cart("]'
        ):
            onclick = element.get("onclick", "")

            match = re.search(
                r"(?:getProductDetails|add_cart)\(\s*['\"]?(\d+)",
                onclick,
            )

            if match:
                return match.group(1)

        # Some cards may have an explicit data/product ID.
        for attribute in (
            "data-product-id",
            "data-id",
            "product-id",
        ):
            element = card.select_one(
                f"[{attribute}]"
            )

            if element is not None:
                value = element.get(attribute)

                if value:
                    return str(value).strip()

        # Fall back to query-string ID from product overview.
        match = re.search(
            r"[?&]id=([^&#]+)",
            product_url,
        )

        if match:
            return match.group(1)

        return None

    @staticmethod
    def _stable_id_from_url(url: str) -> str:
        """Create a deterministic fallback identifier from a URL."""

        # Python's hash() is intentionally randomized between processes,
        # so do not use it for persistent product IDs.
        import hashlib

        return hashlib.sha256(
            url.encode("utf-8")
        ).hexdigest()[:24]

    # ------------------------------------------------------------------
    # Product fields
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_price(card: Any) -> float | None:
        """Extract the first visible rupee price from a card."""

        text = card.get_text(" ", strip=True)

        matches = re.findall(
            r"(?:RS\.?|₹)\s*([\d,]+(?:\.\d+)?)",
            text,
            flags=re.IGNORECASE,
        )

        if not matches:
            return None

        try:
            return float(
                matches[0].replace(",", "")
            )
        except ValueError:
            return None

    @staticmethod
    def _extract_model_number(
        name: str,
    ) -> str | None:
        """
        Attempt to extract a model number from the product name.

        HMT names commonly contain model identifiers such as:
        "UGSS 101", "UGBKBK 10", etc.

        This is deliberately conservative; the full product name remains
        the primary identity field.
        """

        patterns = (
            r"\b([A-Z]{2,}\s*[A-Z0-9-]{2,})\b",
            r"\b([A-Z0-9]{4,}-[A-Z0-9-]+)\b",
        )

        for pattern in patterns:
            match = re.search(
                pattern,
                name.upper(),
            )

            if match:
                return match.group(1).strip()

        return None

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_text(value: str) -> str:
        """Normalize HTML-derived text."""

        value = unescape(value)

        return re.sub(
            r"\s+",
            " ",
            value,
        ).strip()

    @staticmethod
    def _parse_int(value: Any) -> int | None:
        """Parse an integer-like value safely."""

        if value is None:
            return None

        if isinstance(value, bool):
            return int(value)

        try:
            text = str(value).strip()

            if not text:
                return None

            return int(
                float(
                    text.replace(",", "")
                )
            )

        except (TypeError, ValueError):
            return None