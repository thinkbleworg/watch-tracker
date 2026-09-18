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

    Discovery:
        POST SmartPOS catalogue API and paginate through the complete
        catalogue.

    Stock:
        The bulk catalogue is used first.

        When the bulk response is internally ambiguous, the SmartBiz
        product-detail API is queried for authoritative product-level
        availability.

    Product detail endpoint:
        GET https://api.smartbiz.in/stores/{shop_id}/v2/catalog/{product_id}

    Important:
        We deliberately do NOT request the detail endpoint for every
        product on every scrape. The store currently exposes hundreds
        of products and the tracker runs every minute in production.
    """

    API_URL = (
        "https://smartpos.amazon.in/"
        "api-unauthenticated/resources/external/catalog/products"
    )

    DETAIL_API_URL = (
        "https://api.smartbiz.in/stores/{shop_id}/v2/catalog/{product_id}"
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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

        if not watches:
            raise RuntimeError(
                "HMT store source returned no parseable products."
            )

        logger.info(
            "HMT store returned %s products.",
            len(watches),
        )

        return watches

    # ------------------------------------------------------------------
    # Catalogue API
    # ------------------------------------------------------------------

    def _fetch_page(
        self,
        *,
        offset: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """
        Fetch one page from the SmartPOS catalogue API.
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

    # ------------------------------------------------------------------
    # Product parsing
    # ------------------------------------------------------------------

    def _parse_product(
        self,
        product: dict[str, Any],
    ) -> Watch | None:
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

        name = self._clean_string(
            product.get("name")
        )

        if not product_id or not name:
            logger.warning(
                "Skipping HMT store product without stable ID/name: %r",
                product,
            )
            return None

        product_id = str(product_id)

        sku = self._clean_string(
            product.get("sku")
        )

        mrp = self._number_or_none(
            product.get("mrp")
        )

        selling_price = self._number_or_none(
            product.get("sellingPrice")
        )

        if selling_price is None:
            selling_price = mrp

        in_stock, stock = self._stock(
            product,
            product_id=product_id,
        )

        image_url = self._clean_string(
            product.get("productImageUrl")
        )

        product_url = self._build_product_url(
            product_id=product_id,
        )

        return Watch.create(
            id=product_id,
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

    # ------------------------------------------------------------------
    # Stock handling
    # ------------------------------------------------------------------

    def _extract_stock(
        self,
        product: dict[str, Any],
    ) -> tuple[int | None, bool]:
        """
        Extract stock count/status from the bulk SmartPOS response.

        Rules:

        1. Explicit isOOS=True means out of stock.
        2. A positive currentStock means in stock.
        3. A positive/true availability signal means in stock.
        4. Explicit false availability means out of stock.
        5. Otherwise the state is ambiguous and returns (None, False).
           _stock() may then verify it through the product-detail API.
        """
        additional_attributes = product.get(
            "additionalAttributes"
        )

        additional_attributes = self._parse_json_object(
            additional_attributes
        )

        if additional_attributes.get("isOOS") is True:
            return 0, False

        stock_value = product.get("currentStock")

        if stock_value is not None:
            try:
                stock_number = float(stock_value)

                if stock_number > 0:
                    stock_count = int(stock_number)

                    return stock_count, True

                if stock_number == 0:
                    return 0, False

            except (TypeError, ValueError):
                pass

        buying_options = (
            product.get("buyingOptions")
            or {}
        )

        single_purchase = (
            buying_options.get("singlePurchase")
            or {}
        )

        availability = (
            single_purchase.get("availability")
            or {}
        )

        is_buyable = availability.get("isBuyable")
        in_stock = availability.get("inStock")

        if is_buyable is True and in_stock is True:
            return None, True

        if is_buyable is True:
            return None, True

        if in_stock is True:
            return None, True

        if is_buyable is False:
            return None, False

        if in_stock is False:
            return None, False

        return None, False

    def _stock(
        self,
        product: dict[str, Any],
        *,
        product_id: str | None = None,
    ) -> tuple[bool, int | None]:
        """
        Return (in_stock, stock_count).

        For ambiguous bulk responses, verify the product against the
        SmartBiz product-detail endpoint.

        A detail API failure does NOT turn the product into an
        in-stock product. The safe fallback is the bulk result.
        """
        stock_count, in_stock = self._extract_stock(
            product
        )

        if not self._needs_detail_check(product):
            return in_stock, stock_count

        if not product_id:
            return in_stock, stock_count

        try:
            detail = self._fetch_product_detail(
                product_id
            )

            detail_stock_count, detail_in_stock = (
                self._extract_detail_stock(detail)
            )

            logger.debug(
                "HMT store detail stock: id=%s in_stock=%s "
                "stock_count=%s",
                product_id,
                detail_in_stock,
                detail_stock_count,
            )

            return (
                detail_in_stock,
                detail_stock_count,
            )

        except Exception:
            logger.warning(
                "Unable to verify HMT store stock detail for %s; "
                "using bulk catalogue state.",
                product_id,
                exc_info=True,
            )

            return in_stock, stock_count

    @staticmethod
    def _needs_detail_check(
        product: dict[str, Any],
    ) -> bool:
        """
        Decide whether the bulk stock response needs verification.

        We only use the detail API for ambiguous cases.

        In particular, a product with:
            isOOS=False
            currentStock=0

        is suspicious because the store can expose contradictory
        availability metadata. Such products are verified individually.
        """
        additional_attributes = (
            product.get("additionalAttributes")
        )

        additional_attributes = (
            HMTStoreScraper._parse_json_object(
                additional_attributes
            )
        )

        if additional_attributes.get("isOOS") is True:
            return False

        stock_value = product.get("currentStock")

        if stock_value is not None:
            try:
                stock_number = float(stock_value)

                if stock_number > 0:
                    return False

                if stock_number == 0:
                    return (
                        additional_attributes.get("isOOS")
                        is not True
                    )

            except (TypeError, ValueError):
                pass

        buying_options = (
            product.get("buyingOptions")
            or {}
        )

        single_purchase = (
            buying_options.get("singlePurchase")
            or {}
        )

        availability = (
            single_purchase.get("availability")
            or {}
        )

        is_buyable = availability.get("isBuyable")
        in_stock = availability.get("inStock")

        # Explicitly positive and internally consistent.
        if is_buyable is True and in_stock is True:
            return False

        # Explicit OOS signals do not need another request.
        if is_buyable is False and in_stock is False:
            return False

        # Everything else is ambiguous.
        return True

    # ------------------------------------------------------------------
    # SmartBiz product-detail API
    # ------------------------------------------------------------------

    def _fetch_product_detail(
        self,
        product_id: str,
    ) -> dict[str, Any]:
        """
        Fetch one product from the SmartBiz catalogue API.
        """
        url = self.DETAIL_API_URL.format(
            shop_id=self.shop_id,
            product_id=product_id,
        )

        response = self.get(
            url,
            headers={
                "Accept": "application/json",
                "Referer": self.base_url,
            },
        )

        payload = response.json()

        if not isinstance(payload, dict):
            raise ValueError(
                "Unexpected HMT store detail response: "
                f"expected object, got {type(payload).__name__}"
            )

        return payload

    @classmethod
    def _extract_detail_stock(
        cls,
        payload: dict[str, Any],
    ) -> tuple[int | None, bool]:
        """
        Extract stock from the SmartBiz product-detail response.

        For the observed API response:

            variantsInfo[0].attributes.oos
            variantsInfo[0].attributes.quantity
            variantsInfo[0].attributes.buyingOptions.singlePurchase.availability

        Availability precedence:

            positive quantity
                -> in stock

            otherwise:
                inStock=True
                -> in stock

            otherwise:
                -> out of stock

        SmartBiz has been observed returning contradictory metadata where
        oos=True while inStock=True, so an explicit positive inStock signal
        is allowed to override the stale oos flag.

        We only report a numeric stock count when the API provides a
        usable quantity.
        """
        variants = payload.get("variantsInfo")

        if not isinstance(variants, list) or not variants:
            return 0, False

        total_stock = 0
        have_numeric_quantity = False

        any_buyable = False
        any_in_stock = False

        for variant in variants:
            if not isinstance(variant, dict):
                continue

            attributes = variant.get("attributes")

            if not isinstance(attributes, dict):
                continue

            if attributes.get("deactivated") is True:
                continue

            quantity = cls._number_or_none(
                attributes.get("quantity")
            )

            buying_options = (
                attributes.get("buyingOptions")
                or {}
            )

            single_purchase = (
                buying_options.get("singlePurchase")
                or {}
            )

            availability = (
                single_purchase.get("availability")
                or {}
            )

            variant_in_stock = (
                availability.get("inStock")
            )

            variant_buyable = (
                availability.get("isBuyable")
            )

            # SmartBiz can expose contradictory metadata. In particular,
            # an observed live product state had oos=True while inStock=True.
            # Treat the explicit availability signal as stronger when it
            # positively says the variant is in stock.
            if (
                attributes.get("oos") is True
                and variant_in_stock is not True
            ):
                continue

            if quantity is not None:
                try:
                    numeric_quantity = float(quantity)

                    if numeric_quantity > 0:
                        total_stock += int(
                            numeric_quantity
                        )

                        have_numeric_quantity = True

                except (TypeError, ValueError):
                    pass

            if variant_in_stock is True:
                any_in_stock = True

            if variant_buyable is True:
                any_buyable = True

        # A numeric positive quantity is the strongest signal.
        if have_numeric_quantity and total_stock > 0:
            return total_stock, True

        # The storefront's explicit availability flag is the next strongest
        # signal. This intentionally handles the observed state where
        # inStock=True but isBuyable=False.
        if any_in_stock:
            return None, True

        # isBuyable without inStock is not enough to claim inventory.
        if any_buyable:
            return None, False

        return 0, False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_json_object(
        value: Any,
    ) -> dict[str, Any]:
        if isinstance(value, dict):
            return value

        if not isinstance(value, str):
            return {}

        if not value.strip():
            return {}

        try:
            parsed = json.loads(value)

        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

        if isinstance(parsed, dict):
            return parsed

        return {}

    def _build_product_url(
        self,
        *,
        product_id: str,
    ) -> str:
        """
        Return the canonical HMT store product URL.

        Example:
            /product/6fc9b813-4333-4bae-8cc9-bb2461a2c7d2
        """
        return (
            f"{self.base_url.rstrip('/')}"
            f"/product/{product_id}"
        )

    @staticmethod
    def _clean_string(
        value: Any,
    ) -> str | None:
        if value is None:
            return None

        value = str(value).strip()

        return value or None

    @staticmethod
    def _number_or_none(
        value: Any,
    ) -> int | float | None:
        if value is None or value == "":
            return None

        try:
            number = float(value)

        except (TypeError, ValueError):
            return None

        if number.is_integer():
            return int(number)

        return number

    @staticmethod
    def _is_deactivated(
        product: dict[str, Any],
    ) -> bool:
        """
        Return True when the store explicitly marks a product as
        deactivated.
        """
        if product.get("deactivated") is True:
            return True

        additional_attributes = (
            HMTStoreScraper._parse_json_object(
                product.get("additionalAttributes")
            )
        )

        return (
            additional_attributes.get("deactivated")
            is True
        )