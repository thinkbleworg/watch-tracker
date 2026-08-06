"""
Models used throughout the application.
"""

from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class Watch:

    name: str
    price: str
    product_url: str
    image_url: str
    stock: str
    source: str
    detected_at: str

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)

    @classmethod
    def create(
        cls,
        name,
        price,
        product_url,
        image_url,
        stock,
        source,
    ):

        return cls(
            name=name.strip(),
            price=price.strip(),
            product_url=product_url.strip(),
            image_url=image_url.strip(),
            stock=stock.strip(),
            source=source.strip(),
            detected_at=datetime.now().isoformat(timespec="seconds"),
        )