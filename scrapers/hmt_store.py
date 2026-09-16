# scrapers/hmt_store.py

from __future__ import annotations

import json
import logging
from typing import Any

from models import Watch
from scrapers.base import BaseScraper


logger = logging.getLogger(__name__)


class HMTStoreScraper(BaseScraper):
    """
    Scraper for https://www.hmtwatches.store

    The store frontend uses the SmartPOS catalogue API:

        POST https://smartpos.amazon.in/api-unauthenticated/resources/external/catalog/products
            ?groupVariants=true

    Request body:

        {
            "filter": {
                "division": null,
                "isBestSeller": null,
                "isInStock": null
            },
            "shopId": 48236,
            "offset": 0,
            "limit": 10
        }
    """

    API_URL = (
        "https://smartpos.amazon.in/"
        "api-unauthenticated/resources/external/catalog/products"
    )

    def __init__(
        self,
        *,
        base_url: str,
        shop_id: int = 48236,
        page_size: int = 10,
        timeout: int = 30,
        retries: int = 3,
    ) -> None:
        super().__init__(
            base_url=base_url,
            timeout=timeout,
            retries=retries,
        )

        self.shop_id = shop_id
        self.page_size = page_size

    def scrape(self) -> list[Watch]:
        """
        Fetch the complete catalogue from the store API.

        Pagination continues until the API returns fewer products than
        requested, or an empty page.

        A request/API failure is allowed to propagate to the tracker so
        the tracker can correctly treat the source as failed rather than
        interpreting the failure as an empty catalogue.
        """
        watches: list[Watch] = []
        seen_ids: set[str] = set()

        offset = 0

        while True:
            products = self._fetch_page(
                offset=offset,
                limit=self.page_size,
            )

            if not products:
                break

            for product in products:
                watch = self._parse_product(product)

                if watch is None:
                    continue

                # The API can expose variant information. Keep the primary
                # product/sku as the stable identity for the catalogue.
                identity = (
                    watch.id
                    or watch.sku
                    or watch.product_url
                    or watch.name
                )

                identity = str(identity)

                if identity in seen_ids:
                    continue

                seen_ids.add(identity)
                watches.append(watch)

            logger.debug(
                "HMT store page: offset=%s returned=%s total=%s",
                offset,
                len(products),
                len(watches),
            )

            if len(products) < self.page_size:
                break

            offset += self.page_size

        logger.info(
            "HMT store returned %s products.",
            len(watches),
        )

        return watches

    def _fetch_page(
        self,
        *,
        offset: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """
        Fetch one page using the same request shape as the live store.
        """
        response = self.post(
            self.API_URL,
            params={
                "groupVariants": "true",
            },
            json={
                "filter": {
                    "division": None,
                    "isBestSeller": None,
                    "isInStock": None,
                },
                "shopId": self.shop_id,
                "offset": offset,
                "limit": limit,
            },
            headers={
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
                "Origin": self.base_url,
                "Referer": f"{self.base_url}/",
            },
        )

        payload = response.json()

        products = self._extract_products(payload)

        if not isinstance(products, list):
            raise ValueError(
                "Unexpected HMT store catalogue response: "
                f"expected a list, got {type(products).__name__}"
            )

        return [
            product
            for product in products
            if isinstance(product, dict)
        ]

    @staticmethod
    def _extract_products(payload: Any) -> list[Any]:
        """
        Handle the current API response as well as common wrapper formats.

        The current HMT API returns the product list directly.
        """
        if isinstance(payload, list):
            return payload

        if not isinstance(payload, dict):
            return []

        for key in (
            "products",
            "items",
            "content",
            "data",
            "results",
        ):
            value = payload.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                nested = HMTStoreScraper._extract_products(value)

                if nested:
                    return nested

        return []

    def _parse_product(self, product: dict[str, Any]) -> Watch | None:
        """
        Convert one SmartPOS product into our common Watch model.
        """
        if self._is_deactivated(product):
            return None
        
        product_id = (
            product.get("primaryProductId")
            or product.get("sku")
            or product.get("customId")
        )

        name = self._clean_string(product.get("name"))

        if not product_id or not name:
            logger.warning(
                "Skipping HMT store product without stable ID/name: %r",
                product,
            )
            return None

        sku = self._clean_string(product.get("sku"))

        mrp = self._number_or_none(product.get("mrp"))
        selling_price = self._number_or_none(
            product.get("sellingPrice")
        )

        if selling_price is None:
            selling_price = mrp

        in_stock, stock = self._stock(product)

        image_url = self._clean_string(
            product.get("productImageUrl")
        )

        # The store is a dynamic frontend, so the API does not expose
        # a normal product URL in the catalogue response. Build the
        # product URL using the product ID only when appropriate.
        product_url = self._build_product_url(
            product_id=str(product_id),
        )

        return Watch.create(
            id=str(product_id),
            source="hmt.store",
            name=name,
            product_url=product_url,
            in_stock=in_stock,
            stock_count=stock,
            sku=sku,
            price=selling_price,
            mrp=mrp,
            image_url=image_url,
        )

    def _extract_stock(
        self,
        product: dict[str, Any],
    ) -> tuple[int | None, bool]:
        """
        Extract stock count and in-stock status from the SmartPOS response.

        Priority:
        1. Explicit additionalAttributes.isOOS=true overrides everything.
        2. Numeric currentStock is the strongest stock signal.
        3. Availability flags are used when currentStock is unavailable.
        """

        additional_attributes = product.get("additionalAttributes")

        if isinstance(additional_attributes, str):
            try:
                additional_attributes = json.loads(additional_attributes)
            except (TypeError, ValueError):
                additional_attributes = {}
        elif not isinstance(additional_attributes, dict):
            additional_attributes = {}

        # Explicit OOS flag always wins.
        if additional_attributes.get("isOOS") is True:
            return 0, False

        stock_value = product.get("currentStock")

        if stock_value is not None:
            try:
                stock_count = int(stock_value)

                if stock_count > 0:
                    return stock_count, True

                if stock_count == 0:
                    return 0, False

            except (TypeError, ValueError):
                pass

        buying_options = product.get("buyingOptions") or {}
        single_purchase = buying_options.get("singlePurchase") or {}
        availability = single_purchase.get("availability") or {}

        if availability.get("isBuyable") is True:
            return None, True

        if availability.get("inStock") is True:
            return None, True

        if availability.get("isBuyable") is False:
            return None, False

        if availability.get("inStock") is False:
            return None, False

        return None, False

    @staticmethod
    def _parse_json_object(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value

        if not isinstance(value, str) or not value.strip():
            return {}

        try:
            parsed = json.loads(value)

            if isinstance(parsed, dict):
                return parsed

        except (TypeError, ValueError, json.JSONDecodeError):
            pass

        return {}

    def _build_product_url(self, *, product_id: str) -> str:
        """
        Return a useful store URL.

        The catalogue API response does not provide a canonical product
        URL, so keep the store homepage as the safe fallback.
        """
        return f"{self.base_url.rstrip('/')}/"

    @staticmethod
    def _clean_string(value: Any) -> str | None:
        if value is None:
            return None

        value = str(value).strip()

        return value or None

    @staticmethod
    def _number_or_none(value: Any) -> int | float | None:
        if value is None or value == "":
            return None

        try:
            number = float(value)

        except (TypeError, ValueError):
            return None

        if number.is_integer():
            return int(number)

        return number

    def _stock(
        self,
        product: dict[str, Any],
    ) -> tuple[bool, int | None]:
        """
        Return (in_stock, stock_count).

        Keep this helper as part of the scraper's existing interface because
        the test suite and parser use it directly.
        """
        stock_count, in_stock = self._extract_stock(product)
        return in_stock, stock_count

    @staticmethod
    def _is_deactivated(product: dict[str, Any]) -> bool:
        """
        Return True when the store explicitly marks a product as deactivated.
        """
        return product.get("deactivated") is True