"""
Watch model
"""

from dataclasses import dataclass
from dataclasses import asdict

from datetime import datetime


@dataclass
class Watch:

    id: str

    name: str

    price: str

    product_url: str

    image_url: str

    stock: str

    source: str

    first_seen: str

    last_seen: str

    last_available: str

    def to_dict(self):

        return asdict(self)

    @classmethod
    def from_dict(cls, data):

        return cls(**data)

    @classmethod
    def create(

        cls,

        id,

        name,

        price,

        product_url,

        image_url,

        stock,

        source,

    ):

        now = datetime.now().isoformat()

        return cls(

            id=id,

            name=name,

            price=price,

            product_url=product_url,

            image_url=image_url,

            stock=stock,

            source=source,

            first_seen=now,

            last_seen=now,

            last_available=now
            if stock == "Available"
            else "",

        )