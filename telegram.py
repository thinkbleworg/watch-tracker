"""
Telegram Notification Module
"""

import requests

from config import (
    BOT_TOKEN,
    CHAT_ID,
    ENABLE_PREVIEW,
)


class Telegram:

    def __init__(self):

        self.url = (
            f"https://api.telegram.org/"
            f"bot{BOT_TOKEN}/sendPhoto"
        )

    def send_watch(
        self,
        emoji,
        watch,
        extra=""
    ):

        caption = f"""
{emoji} <b>{watch.name}</b>

💰 <b>Price</b>
{watch.price}

📦 <b>Status</b>
{watch.stock}

🌐 <b>Source</b>
{watch.source}

🕒 <b>Detected</b>
{watch.detected_at}

🔗 <a href="{watch.product_url}">
Open Product
</a>

{extra}
"""

        payload = {

            "chat_id": CHAT_ID,

            "photo": watch.image_url,

            "caption": caption,

            "parse_mode": "HTML",

            "disable_web_page_preview": ENABLE_PREVIEW

        }

        r = requests.post(
            self.url,
            data=payload,
            timeout=30
        )

        if r.status_code != 200:

            print(r.text)

    def new_watch(self, watch):

        self.send_watch(
            "🟢 NEW WATCH",
            watch
        )

    def sold_out(self, watch):

        self.send_watch(
            "🔴 SOLD OUT",
            watch
        )

    def price_changed(
        self,
        watch,
        old_price,
        new_price,
    ):

        self.send_watch(

            "💰 PRICE CHANGED",

            watch,

            f"""
<b>Old Price</b>

{old_price}

<b>New Price</b>

{new_price}
"""
        )

    def stock_changed(
        self,
        watch,
        old_stock,
        new_stock,
    ):

        self.send_watch(

            "📦 STOCK UPDATED",

            watch,

            f"""
<b>Old</b>

{old_stock}

<b>New</b>

{new_stock}
"""
        )