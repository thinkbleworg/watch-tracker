from notifier import Notifier
from models import Watch

watch = Watch.create(
    id="123",
    name="HMT Test Watch",
    price="₹9999",
    product_url="https://google.com",
    image_url="https://picsum.photos/500",
    stock="Available",
    source="Test"
)

Notifier().new_watch(watch)