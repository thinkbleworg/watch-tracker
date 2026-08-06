"""
Notification Manager

Currently supports Telegram.

Future:
    - WhatsApp
    - Discord
    - Email
"""

import requests

from config import (
    BOT_TOKEN,
    CHAT_ID,
)


class Notifier:

    def __init__(self):

        self.url = (
            f"https://api.telegram.org/"
            f"bot{BOT_TOKEN}"
        )

    ########################################################

    def _send_photo(

        self,

        watch,

        title,

        extra=""

    ):

        endpoint = self.url + "/sendPhoto"

        caption = f"""
<b>{title}</b>

⌚ <b>{watch.name}</b>

💰 <b>Price</b>
{watch.price}

📦 <b>Status</b>
{watch.stock}

🌐 <b>Source</b>
{watch.source}

🕒 <b>First Seen</b>
{watch.first_seen}

🕒 <b>Last Seen</b>
{watch.last_seen}

🟢 <b>Last Available</b>
{watch.last_available}

🔗
{watch.product_url}

{extra}
"""

        payload = {

            "chat_id": CHAT_ID,

            "photo": watch.image_url,

            "caption": caption,

            "parse_mode": "HTML",

        }

        response = requests.post(

            endpoint,

            data=payload,

            timeout=30,

        )

        if response.status_code != 200:

            print(

                response.text

            )

    ########################################################

    def new_watch(

        self,

        watch

    ):

        self._send_photo(

            watch,

            "🟢 NEW WATCH"

        )

    ########################################################

    def removed_watch(

        self,

        watch

    ):

        self._send_photo(

            watch,

            "❌ REMOVED"

        )

    ########################################################

    def sold_out(

        self,

        watch

    ):

        self._send_photo(

            watch,

            "🔴 SOLD OUT"

        )

    ########################################################

    def back_in_stock(

        self,

        watch

    ):

        self._send_photo(

            watch,

            "🟢 BACK IN STOCK"

        )

    ########################################################

    def price_changed(

        self,

        watch,

        old_price,

        new_price,

    ):

        self._send_photo(

            watch,

            "💰 PRICE CHANGED",

            f"""

Old Price

{old_price}

New Price

{new_price}

"""

        )

    ########################################################

    def send_result(

        self,

        result

    ):

        #
        # New
        #

        for watch in result.new:

            self.new_watch(

                watch

            )

        #
        # Removed
        #

        for watch in result.removed:

            self.removed_watch(

                watch

            )

        #
        # Sold Out
        #

        for watch in result.sold_out:

            self.sold_out(

                watch

            )

        #
        # Back In Stock
        #

        for watch in result.back_in_stock:

            self.back_in_stock(

                watch

            )

        #
        # Price Changed
        #

        for item in result.price_changed:

            self.price_changed(

                item["watch"],

                item["old_price"],

                item["new_price"]

            )