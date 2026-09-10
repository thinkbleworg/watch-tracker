"""
Watch model
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

def utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Watch:
    """
    Normalized representation of an HMT watch.

    Both HMT sources must convert their scraped product into this model.
    """

    # Stable identity
    id: str
    source: str

    # Product information
    name: str
    model_number: str | None
    sku: str | None

    # Pricing
    price: float | None
    mrp: float | None

    # Product links/media
    product_url: str
    image_url: str | None

    # Availability
    in_stock: bool
    stock_count: int | None

    # Optional classification
    category: str | None
    collection: str | None
    gender: str | None

    # Catalogue lifecycle
    first_seen: str
    last_seen: str

    # Last successful stock observation
    last_stock_check: str

    def to_dict(self) -> dict[str, Any]:
        """Convert the watch to a JSON/database-friendly dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Watch":
        """Create a Watch from a dictionary."""
        return cls(**data)

    @classmethod
    def create(
        cls,
        *,
        id: str,
        source: str,
        name: str,
        product_url: str,
        in_stock: bool,
        stock_count: int | None = None,
        model_number: str | None = None,
        sku: str | None = None,
        price: float | None = None,
        mrp: float | None = None,
        image_url: str | None = None,
        category: str | None = None,
        collection: str | None = None,
        gender: str | None = None,
    ) -> "Watch":
        """
        Create a new Watch with lifecycle timestamps initialized.
        """
        now = utc_now()

        return cls(
            id=id,
            source=source,
            name=name.strip(),
            model_number=model_number.strip() if model_number else None,
            sku=sku.strip() if sku else None,
            price=price,
            mrp=mrp,
            product_url=product_url,
            image_url=image_url,
            in_stock=in_stock,
            stock_count=stock_count,
            category=category,
            collection=collection,
            gender=gender,
            first_seen=now,
            last_seen=now,
            last_stock_check=now,
        )

    def update_from(self, latest: "Watch") -> None:
        """
        Update this catalogue record using the latest scrape.

        The permanent identity and first_seen timestamp are preserved.
        """

        self.name = latest.name

        if latest.model_number:
            self.model_number = latest.model_number

        if latest.sku:
            self.sku = latest.sku

        if latest.price is not None:
            self.price = latest.price

        if latest.mrp is not None:
            self.mrp = latest.mrp

        if latest.product_url:
            self.product_url = latest.product_url

        if latest.image_url:
            self.image_url = latest.image_url

        if latest.category:
            self.category = latest.category

        if latest.collection:
            self.collection = latest.collection

        if latest.gender:
            self.gender = latest.gender

        self.in_stock = latest.in_stock
        self.stock_count = latest.stock_count

        self.last_seen = utc_now()
        self.last_stock_check = self.last_seen

    @property
    def is_available(self) -> bool:
        """Human-friendly alias for the stock state."""
        return self.in_stock

    @property
    def display_stock(self) -> str:
        """
        Return a safe stock value for the UI/Telegram message.

        We never invent a quantity when the source doesn't provide one.
        """
        if not self.in_stock:
            return "Out of stock"

        if self.stock_count is not None:
            return f"{self.stock_count} available"

        return "In stock"


@dataclass
class TrackingRule:
    """
    Configurable rule describing which watches should be monitored.
    """

    id: str
    name: str
    enabled: bool = True

    # Optional source restriction.
    # None means both sources.
    source: str | None = None

    # Name/model matching.
    include_keywords: list[str] | None = None
    exclude_keywords: list[str] | None = None

    # Optional explicit product IDs.
    product_ids: list[str] | None = None

    # Minimum stock required before an alert is generated.
    minimum_stock: int = 1

    def matches(self, watch: Watch) -> bool:
        """
        Determine whether this rule applies to a watch.
        """

        if not self.enabled:
            return False

        if self.source and self.source != watch.source:
            return False

        # Explicit product IDs have priority when configured.
        if self.product_ids:
            if watch.id not in self.product_ids:
                return False

        searchable = " ".join(
            value.lower()
            for value in (
                watch.name,
                watch.model_number or "",
                watch.sku or "",
            )
        )

        # Include rules.
        if self.include_keywords:
            if not any(
                keyword.lower() in searchable
                for keyword in self.include_keywords
            ):
                return False

        # Exclude rules.
        if self.exclude_keywords:
            if any(
                keyword.lower() in searchable
                for keyword in self.exclude_keywords
            ):
                return False

        # Stock threshold.
        if watch.in_stock:
            if (
                watch.stock_count is not None
                and watch.stock_count < self.minimum_stock
            ):
                return False

        return True


@dataclass
class AlertState:
    """
    State used to prevent duplicate Telegram notifications.

    This is deliberately separate from the Watch catalogue.
    """

    watch_id: str

    first_alerted_at: str | None = None
    last_alerted_at: str | None = None

    alert_count: int = 0

    def record_alert(self) -> None:
        now = utc_now()

        if self.first_alerted_at is None:
            self.first_alerted_at = now

        self.last_alerted_at = now
        self.alert_count += 1

    @property
    def has_been_alerted(self) -> bool:
        return self.first_alerted_at is not None