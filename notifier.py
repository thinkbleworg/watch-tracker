"""
Notification Manager

Currently supports Telegram.

Future:
    - WhatsApp
    - Discord
    - Email
"""

import time
import requests

from config import (
    BOT_TOKEN,
    CHAT_ID,
    DRY_RUN,
    TELEGRAM_MIN_INTERVAL,
    TELEGRAM_MAX_RETRIES,
)
from timeutils import format_ist


class Notifier:

    def __init__(self):

        self.url = f"https://api.telegram.org/bot{BOT_TOKEN}"

        # Timestamp of the last message actually sent,
        # used to pace requests and avoid Telegram's
        # flood control (429) on bursts of sendPhoto calls.
        self._last_sent = 0.0

    ########################################################

    def _throttle(self):

        elapsed = time.monotonic() - self._last_sent

        if elapsed < TELEGRAM_MIN_INTERVAL:
            time.sleep(TELEGRAM_MIN_INTERVAL - elapsed)

    ########################################################

    def _send_photo(self, watch, title, extra=""):

        if DRY_RUN:
            print(
                f"[DRY RUN] Would send: {title} -- "
                f"{watch.name} ({watch.source}) "
                f"[{watch.stock}] {watch.price}"
                f"{(' ' + extra.strip()) if extra.strip() else ''}"
            )
            return True

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
{format_ist(watch.first_seen)}

🕒 <b>Last Seen</b>
{format_ist(watch.last_seen)}

🟢 <b>Last Available</b>
{format_ist(watch.last_available)}

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

        for attempt in range(TELEGRAM_MAX_RETRIES):

            self._throttle()

            try:
                response = requests.post(
                    endpoint,
                    data=payload,
                    timeout=30,
                )
            except requests.RequestException as ex:
                print(f"[Telegram] Network error: {ex}")
                time.sleep(2)
                continue
            finally:
                self._last_sent = time.monotonic()

            if response.status_code == 200:
                return True

            #
            # Rate limited -- Telegram tells us how
            # long to wait via retry_after.
            #
            if response.status_code == 429:
                retry_after = 3
                try:
                    retry_after = response.json() \
                        .get("parameters", {}) \
                        .get("retry_after", 3)
                except Exception:
                    pass

                print(
                    f"[Telegram] Rate limited. "
                    f"Waiting {retry_after}s "
                    f"(attempt {attempt + 1}/"
                    f"{TELEGRAM_MAX_RETRIES})"
                )
                time.sleep(retry_after + 0.5)
                continue

            #
            # Bad photo URL is common (dead image link) --
            # retry once as text-only rather than
            # dropping the alert entirely.
            #
            if response.status_code == 400 and attempt == 0:
                print(
                    "[Telegram] sendPhoto failed "
                    f"({response.text[:200]}), "
                    "retrying as text message."
                )
                self._send_text(caption)
                return True

            print(
                f"[Telegram] Failed "
                f"({response.status_code}): "
                f"{response.text[:300]}"
            )
            time.sleep(2)

        print(
            f"[Telegram] Giving up on notification "
            f"for: {watch.name}"
        )
        return False

    ########################################################

    def _send_text(self, text):

        endpoint = self.url + "/sendMessage"

        self._throttle()

        try:
            response = requests.post(
                endpoint,
                data={
                    "chat_id": CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                },
                timeout=30,
            )
            if response.status_code != 200:
                print(response.text)
        except requests.RequestException as ex:
            print(f"[Telegram] Network error: {ex}")
        finally:
            self._last_sent = time.monotonic()

    ########################################################

    def new_watch(self, watch):
        self._send_photo(watch, "🟢 NEW WATCH")

    ########################################################

    def removed_watch(self, watch):
        self._send_photo(watch, "❌ REMOVED")

    ########################################################

    def sold_out(self, watch):
        self._send_photo(watch, "🔴 SOLD OUT")

    ########################################################

    def back_in_stock(self, watch):
        self._send_photo(watch, "🟢 BACK IN STOCK")

    ########################################################

    def price_changed(self, watch, old_price, new_price):
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

    def send_result(self, result):

        for watch in result.new:
            self.new_watch(watch)

        for watch in result.removed:
            self.removed_watch(watch)

        for watch in result.sold_out:
            self.sold_out(watch)

        for watch in result.back_in_stock:
            self.back_in_stock(watch)

        for item in result.price_changed:
            self.price_changed(
                item["watch"],
                item["old_price"],
                item["new_price"]
            )
