from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from models import Watch
from scrapers.base import BaseScraper


class HMTStoreScraper(BaseScraper):
    """
    Scraper for https://hmtwatches.store

    The store is backed by Amazon SmartPOS rather than requiring
    browser automation.

    Stock priority:
        1. additionalAttributes.isOOS
        2. buyingOptions.singlePurchase.availability.isBuyable
        3. buyingOptions.singlePurchase.availability.inStock
        4. currentStock when available
    """

    SOURCE = "hmt.store"

    API_URL = (
        "https://smartpos.amazon.in/"
        "api-unauthenticated/resources/external/catalog/products"
    )

    def __init__(
        self,
        *,
        base_url: str,
        shop_id: int = 48236,
        page_size: int = 100,
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
        Fetch the complete store catalogue.

        The API is paginated using offset + limit.
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

                if watch.id in seen_ids:
                    continue

                seen_ids.add(watch.id)
                watches.append(watch)

            # A short page means we reached the end.
            if len(products) < self.page_size:
                break

            offset += self.page_size

        if not watches:
            raise RuntimeError(
                "HMT store returned no parseable products"
            )

        return watches

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def _fetch_page(
        self,
        *,
        offset: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """
        Fetch one SmartPOS catalogue page.
        """
        response = self.post(
            self.API_URL,
            json={
                "shopId": self.shop_id,
                "filter": {},
                "offset": offset,
                "limit": limit,
                "groupVariants": True,
            },
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )

        payload = response.json()

        return self._extract_products(payload)

    @classmethod
    def _extract_products(
        cls,
        payload: Any,
    ) -> list[dict[str, Any]]:
        """
        Handle the response shapes used by SmartPOS.

        Normally the API returns a list, but wrappers such as
        {products: [...]}, {results: [...]}, etc. are supported.
        """
        if isinstance(payload, list):
            return [
                item
                for item in payload
                if isinstance(item, dict)
            ]

        if not isinstance(payload, dict):
            return []

        for key in (
            "products",
            "results",
            "items",
            "data",
        ):
            value = payload.get(key)

            if isinstance(value, list):
                return [
                    item
                    for item in value
                    if isinstance(item, dict)
                ]

            if isinstance(value, dict):
                nested = cls._extract_products(value)

                if nested:
                    return nested

        # Some APIs wrap the result one level deeper.
        for value in payload.values():
            if isinstance(value, dict):
                nested = cls._extract_products(value)

                if nested:
                    return nested

            elif isinstance(value, list):
                items = [
                    item
                    for item in value
                    if isinstance(item, dict)
                ]

                if items:
                    return items

        return []

    # ------------------------------------------------------------------
    # Product parsing
    # ------------------------------------------------------------------

    def _parse_product(
        self,
        product: dict[str, Any],
    ) -> Watch | None:
        """
        Convert one SmartPOS product into our normalized Watch model.
        """
        if self._is_deactivated(product):
            return None

        name = self.clean_text(product.get("name"))

        if not name:
            return None

        identity = self._product_identity(product)

        if not identity:
            return None

        stock, stock_count = self._stock(product)

        description = self.clean_text(
            self._html_to_text(
                product.get("productDescription")
            )
        )

        model_number = self._extract_model_number(
            description,
            name,
        )

        collection = self._extract_labeled_value(
            description,
            "Collection",
        )

        gender = self._extract_labeled_value(
            description,
            "Gender",
        )

        category = self.clean_text(
            product.get("category")
        ) or None

        sku = self.clean_text(
            product.get("sku")
        ) or None

        price = self.parse_price(
            product.get("sellingPrice")
        )

        mrp = self.parse_price(
            product.get("mrp")
        )

        image_url = self._image_url(product)

        product_url = self._product_url(
            product,
            identity=identity,
            sku=sku,
        )

        return Watch.create(
            id=identity,
            source=self.SOURCE,
            name=name,
            model_number=model_number,
            sku=sku,
            price=price,
            mrp=mrp,
            product_url=product_url,
            image_url=image_url,
            in_stock=stock,
            stock_count=stock_count,
            category=category,
            collection=collection,
            gender=gender,
        )

    @staticmethod
    def _is_deactivated(
        product: dict[str, Any],
    ) -> bool:
        value = product.get("deactivated")

        if isinstance(value, bool):
            return value

        return str(value).strip().lower() in {
            "true",
            "1",
            "yes",
        }

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def _product_identity(
        self,
        product: dict[str, Any],
    ) -> str | None:
        """
        Prefer the stable SmartPOS primary product ID.

        SKU is the next-best identifier.
        """
        primary_id = self.clean_text(
            product.get("primaryProductId")
        )

        if primary_id:
            return primary_id

        sku = self.clean_text(product.get("sku"))

        if sku:
            return sku

        name = self.clean_text(product.get("name"))

        if name:
            return self.stable_id(
                source=self.SOURCE,
                value=name,
            )

        return None

    # ------------------------------------------------------------------
    # Stock
    # ------------------------------------------------------------------

    def _stock(
        self,
        product: dict[str, Any],
    ) -> tuple[bool, int | None]:
        """
        Determine whether the product is currently buyable.

        We deliberately avoid guessing stock when the API does not
        provide enough information.
        """
        additional = self._additional_attributes(product)

        # Explicit OOS flag takes priority.
        is_oos = self.as_bool(
            additional.get("isOOS")
        )

        if is_oos is True:
            return False, 0

        availability = self._availability(product)

        is_buyable = self.as_bool(
            availability.get("isBuyable")
        )

        current_stock = self.parse_int(
            product.get("currentStock")
        )

        if is_buyable is True:
            if current_stock is not None:
                if current_stock > 0:
                    return True, current_stock

                # A buyable product reporting zero stock is
                # inconsistent, so don't claim availability.
                return False, 0

            return True, None

        if is_buyable is False:
            if current_stock is not None:
                return False, max(current_stock, 0)

            return False, 0

        # Fall back to inStock when isBuyable isn't available.
        in_stock = self.as_bool(
            availability.get("inStock")
        )

        if in_stock is True:
            if current_stock is not None:
                if current_stock > 0:
                    return True, current_stock

                return False, 0

            return True, None

        if in_stock is False:
            return False, 0

        # Last fallback: currentStock by itself.
        if current_stock is not None:
            if current_stock > 0:
                return True, current_stock

            return False, 0

        return False, None

    @staticmethod
    def _availability(
        product: dict[str, Any],
    ) -> dict[str, Any]:
        buying_options = product.get("buyingOptions")

        if not isinstance(buying_options, dict):
            return {}

        single_purchase = buying_options.get(
            "singlePurchase"
        )

        if not isinstance(single_purchase, dict):
            return {}

        availability = single_purchase.get(
            "availability"
        )

        if not isinstance(availability, dict):
            return {}

        return availability

    @staticmethod
    def _additional_attributes(
        product: dict[str, Any],
    ) -> dict[str, Any]:
        value = product.get("additionalAttributes")

        if isinstance(value, dict):
            return value

        if isinstance(value, str):
            try:
                parsed = json.loads(value)

                if isinstance(parsed, dict):
                    return parsed

            except (json.JSONDecodeError, TypeError):
                pass

        return {}

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    @staticmethod
    def _html_to_text(
        html: Any,
    ) -> str:
        if not html:
            return ""

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(
            str(html),
            "lxml",
        )

        return soup.get_text(
            " ",
            strip=True,
        )

    @classmethod
    def _extract_labeled_value(
        cls,
        text: str,
        label: str,
    ) -> str | None:
        if not text:
            return None

        match = re.search(
            rf"{re.escape(label)}\s*[:\-]\s*"
            r"([^|;,]+?)(?=\s+[A-Z][A-Za-z ]{1,30}\s*[:\-]|$)",
            text,
            re.IGNORECASE,
        )

        if not match:
            return None

        value = cls.clean_text(match.group(1))

        return value or None

    @classmethod
    def _extract_model_number(
        cls,
        description: str,
        name: str,
    ) -> str | None:
        value = cls._extract_labeled_value(
            description,
            "Model No.",
        )

        if value:
            return value

        value = cls._extract_labeled_value(
            description,
            "Model No",
        )

        if value:
            return value

        # Some descriptions use "Model Number".
        value = cls._extract_labeled_value(
            description,
            "Model Number",
        )

        if value:
            return value

        # Conservative fallback: common HMT model-like tokens.
        match = re.search(
            r"\b[A-Z]{1,6}\d{1,4}[A-Z]?\b",
            name,
        )

        if match:
            return match.group(0)

        return None

    @staticmethod
    def _image_url(
        product: dict[str, Any],
    ) -> str | None:
        for key in (
            "productImageUrl",
            "secondaryImageUrl",
            "imageUrl",
            "imageURL",
        ):
            value = product.get(key)

            if isinstance(value, str) and value.strip():
                return value.strip()

        images = product.get("imageUrls")

        if isinstance(images, list):
            for image in images:
                if isinstance(image, str) and image.strip():
                    return image.strip()

        return None

    # ------------------------------------------------------------------
    # Product URL
    # ------------------------------------------------------------------

    def _product_url(
        self,
        product: dict[str, Any],
        *,
        identity: str,
        sku: str | None,
    ) -> str:
        """
        Prefer a URL supplied by the API.

        Otherwise construct the normal HMT store product path.
        """
        for key in (
            "productUrl",
            "productURL",
            "url",
            "productLink",
        ):
            value = product.get(key)

            if isinstance(value, str) and value.strip():
                return value.strip()

        slug_source = sku or identity

        return (
            f"{self.base_url}/products/"
            f"{quote(slug_source, safe='')}"
        )