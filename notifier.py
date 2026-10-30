from __future__ import annotations

import html
import logging
import threading
import time
import json
from types import SimpleNamespace
from typing import Any

import requests

from config import config
from database import Database
from models import AlertState, Watch
from tracker import AlertCandidate


logger = logging.getLogger(__name__)


class TelegramNotifier:
    """
    Sends HMT stock alerts through the Telegram Bot API.

    Normal flow:
        Tracker -> send_candidate() -> Telegram -> mark alert sent

    The notifier only records an AlertState after Telegram confirms
    successful delivery. This prevents failed deliveries from being
    treated as successfully alerted watches.
    """

    def __init__(
        self,
        db: Database,
        *,
        bot_token: str | None = None,
        chat_id: str | None = None,
        timeout: int | None = None,
    ) -> None:
        self.db = db
        self.bot_token = bot_token or config.telegram.bot_token
        self.chat_id = chat_id or config.telegram.chat_id
        self.timeout = timeout or config.request_timeout_seconds

        self._session = requests.Session()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._next_send = 0.0
        self._telegram_blocked_until = 0.0

    def enqueue_candidate(self, candidate: AlertCandidate) -> None:
        # Tracker already committed the alert to SQLite: wake the outbox worker.
        self._wake.set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, name="telegram-outbox", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=self.timeout + 2)

    def _worker(self) -> None:
        while not self._stop.is_set():
            if self.enabled:
                try:
                    self.deliver_due()
                except Exception:
                    logger.exception("Telegram outbox iteration failed")
            self._wake.wait(1)
            self._wake.clear()

    def deliver_due(self) -> int:
        """One durable outbox item at a time; stock alerts take priority."""
        with self._lock:
            if time.monotonic() < self._telegram_blocked_until:
                return 0
            with self.db.connection() as connection:
                row = connection.execute("""
                    SELECT * FROM alerts
                    WHERE status IN ('pending', 'failed') AND next_attempt_at <= ?
                    ORDER BY CASE WHEN alert_type IN ('back_in_stock','new','tracked') THEN 0 ELSE 1 END,
                             created_at, id LIMIT 1
                """, (time.time(),)).fetchone()
            if row is None:
                return 0
            alert = dict(row)
            try:
                self._send_stored(alert)
                self.db.mark_alert_sent(int(alert["id"]))
                self._record_alert_state(str(alert["watch_id"]))
                return 1
            except Exception as exc:
                self.db.mark_alert_failed(int(alert["id"]), str(exc))
                delay = min(1800, 5 * 2 ** min(int(alert["attempts"]), 9))
                with self.db.connection() as connection:
                    connection.execute("UPDATE alerts SET attempts=attempts+1, next_attempt_at=? WHERE id=?",
                                       (time.time() + delay, alert["id"]))
                logger.warning("Telegram delivery failed for alert %s; retry deferred", alert["id"])
                return 0

    def _send_stored(self, alert: dict[str, Any]) -> dict[str, Any]:
        # Never turn an old availability event into a message about current stock.
        if alert.get("snapshot"):
            watch = Watch.from_dict(json.loads(alert["snapshot"]))
            return self._send_watch_message(watch, alert_type=str(alert["alert_type"]))
        return self._send_message(self._format_stored_alert(alert))

    @property
    def enabled(self) -> bool:
        """Return True when Telegram credentials are configured."""
        return bool(self.bot_token and self.chat_id)

    @property
    def api_url(self) -> str:
        if not self.bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")

        return f"https://api.telegram.org/bot{self.bot_token}"

    def send_candidate(self, candidate: AlertCandidate) -> dict[str, Any]:
        """
        Send an alert created by Tracker.

        AlertCandidate currently contains the watch rather than the
        database alert ID, so we locate the newest pending alert for
        this watch/type before delivery.
        """
        alert = self._find_pending_alert(candidate)

        if alert is None:
            raise RuntimeError(
                f"No pending alert found for watch {candidate.watch.id}"
            )

        alert_id = int(alert["id"])

        with self._lock:
            try:
                result = self._send_watch_message(
                    candidate.watch,
                    alert_type=candidate.alert_type,
                )

                self.db.mark_alert_sent(alert_id)

                self._record_alert_state(candidate.watch.id)

                logger.info(
                    "Telegram alert sent: alert_id=%s watch=%s",
                    alert_id,
                    candidate.watch.id,
                )

                return result

            except Exception as exc:
                self.db.mark_alert_failed(
                    alert_id,
                    error=str(exc),
                )

                logger.exception(
                    "Failed to send Telegram alert: alert_id=%s watch=%s",
                    alert_id,
                    candidate.watch.id,
                )

                raise

    def retry_failed_alerts(self, limit: int = 50) -> dict[str, int]:
        """
        Retry failed Telegram alerts.

        Returns:
            {
                "attempted": ...,
                "sent": ...,
                "failed": ...
            }
        """
        return self._retry_alerts(status="failed", limit=limit)

    def retry_pending_alerts(self, limit: int = 50) -> dict[str, int]:
        """
        Retry alerts left pending because the application stopped
        before delivery completed.
        """
        return self._retry_alerts(status="pending", limit=limit)

    def test_send(self, message: str | None = None) -> dict[str, Any]:
        """
        Send a test Telegram message without creating or modifying
        an alert record.
        """
        text = message or (
            "⌚ <b>HMT Watch Tracker</b>\n\n"
            "Telegram notifications are working."
        )

        with self._lock:
            return self._send_message(text)

    def _retry_alerts(
        self,
        *,
        status: str,
        limit: int,
    ) -> dict[str, int]:
        if not self.enabled:
            raise RuntimeError(
                "Telegram is not configured. "
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
            )

        alerts = self.db.get_alerts(status=status, limit=limit)

        attempted = 0
        sent = 0
        failed = 0

        with self._lock:
            for alert in alerts:
                attempted += 1
                alert_id = int(alert["id"])

                try:
                    self._send_stored(alert)

                    self.db.mark_alert_sent(alert_id)

                    watch_id = str(alert["watch_id"])
                    self._record_alert_state(watch_id)

                    sent += 1

                    logger.info(
                        "Retried Telegram alert successfully: alert_id=%s",
                        alert_id,
                    )

                except Exception as exc:
                    failed += 1

                    self.db.mark_alert_failed(
                        alert_id,
                        error=str(exc),
                    )

                    logger.exception(
                        "Telegram alert retry failed: alert_id=%s",
                        alert_id,
                    )

        return {
            "attempted": attempted,
            "sent": sent,
            "failed": failed,
        }

    def _find_pending_alert(
        self,
        candidate: AlertCandidate,
    ) -> dict[str, Any] | None:
        """
        Find the alert created immediately before send_candidate().

        Tracker creates the alert before invoking the notifier callback,
        so the newest pending alert for this watch/type is the intended
        record.
        """
        alerts = self.db.get_alerts(status="pending", limit=1000)

        matches = [
            alert
            for alert in alerts
            if str(alert["watch_id"]) == candidate.watch.id
            and str(alert["alert_type"]) == candidate.alert_type
        ]

        if not matches:
            return None

        return max(
            matches,
            key=lambda alert: int(alert["id"]),
        )

    def _send_watch_message(
        self,
        watch: Any,
        *,
        alert_type: str,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError(
                "Telegram is not configured. "
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
            )

        message = self._format_watch(watch, alert_type=alert_type)

        image_url = getattr(watch, "image_url", None)

        if image_url and alert_type not in {"back_in_stock", "new", "tracked"}:
            try:
                return self._send_photo(
                    image_url,
                    caption=message,
                )
            except Exception as exc:
                if time.monotonic() < self._telegram_blocked_until:
                    raise
                # If the image URL is no longer reachable or Telegram
                # rejects it, fall back to the text alert rather than
                # losing the notification entirely.
                logger.warning(
                    "Telegram photo delivery failed for watch %s; "
                    "falling back to text alert: %s",
                    getattr(watch, "id", "unknown"),
                    exc,
                )

        return self._send_message(message)

    def _pace(self) -> None:
        if time.monotonic() < self._telegram_blocked_until:
            raise RuntimeError("Telegram flood-control cooldown active")
        time.sleep(max(0, self._next_send - time.monotonic()))
        self._next_send = time.monotonic() + (3.1 if str(self.chat_id).startswith("-") else 1.1)

    def _check_rate_limit(self, response) -> None:
        if getattr(response, "status_code", None) != 429:
            return
        try:
            delay = max(1, int(response.json().get("parameters", {}).get("retry_after", 60)))
        except (ValueError, TypeError):
            delay = 60
        self._telegram_blocked_until = time.monotonic() + delay
        raise RuntimeError(f"Telegram flood control: wait {delay} seconds")

    def _send_photo(
        self,
        image_url: str,
        *,
        caption: str,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError(
                "Telegram is not configured. "
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
            )

        self._pace()
        response = self._session.post(
            f"{self.api_url}/sendPhoto",
            data={
                "chat_id": self.chat_id,
                "photo": str(image_url),
                "caption": caption,
                "parse_mode": "HTML",
            },
            timeout=self.timeout,
        )

        self._check_rate_limit(response)
        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "Telegram returned a non-JSON response"
            ) from exc

        if not payload.get("ok"):
            description = payload.get(
                "description",
                "Telegram API returned an unsuccessful response",
            )
            raise RuntimeError(description)

        return payload

    def _send_message(self, text: str) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError(
                "Telegram is not configured. "
                "Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."
            )

        self._pace()
        response = self._session.post(
            f"{self.api_url}/sendMessage",
            data={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": False,
            },
            timeout=self.timeout,
        )

        self._check_rate_limit(response)
        response.raise_for_status()

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "Telegram returned a non-JSON response"
            ) from exc

        if not payload.get("ok"):
            description = payload.get(
                "description",
                "Telegram API returned an unsuccessful response",
            )
            raise RuntimeError(description)

        return payload

    def _format_watch(
        self,
        watch: Any,
        *,
        alert_type: str,
    ) -> str:
        name = html.escape(str(watch.name or "Unknown watch"))
        source = html.escape(self._source_label(watch.source))

        headings = {
            "tracked": "⌚ <b>HMT Tracker Alert</b>",
            "back_in_stock": "🟢 <b>Back in Stock</b>",
            "price_changed": "💰 <b>Price Changed</b>",
            "out_of_stock": "🔴 <b>Out of Stock</b>",
            "coming_soon": "🟠 <b>Coming Soon</b>",
            "repeat": "🔔 <b>HMT Tracker Alert</b>",
            "new": "🆕 <b>New HMT Watch Found</b>",
        }
        heading = headings.get(
            alert_type,
            "⌚ <b>HMT Watch Alert</b>",
        )

        lines = [
            heading,
            "",
            f"<b>{name}</b>",
            f"Source: {source}",
            "Checked: " + html.escape(str(getattr(watch, "last_stock_check", ""))),
        ]

        if alert_type == "out_of_stock":
            lines.append("Stock: <b>Out of stock</b>")

        if getattr(watch, "model_number", None):
            model = html.escape(str(watch.model_number))
            lines.append(f"Model: {model}")

        if getattr(watch, "sku", None):
            sku = html.escape(str(watch.sku))
            lines.append(f"SKU: {sku}")

        price = self._format_price(getattr(watch, "price", None))
        if price:
            lines.append(f"Price: {price}")

        stock = self._format_stock(watch)

        if stock and alert_type != "out_of_stock":
            lines.append(f"Stock: <b>{html.escape(stock)}</b>")

        if getattr(watch, "product_url", None):
            url = html.escape(str(watch.product_url), quote=True)
            lines.extend(
                [
                    "",
                    f'🛒 <a href="{url}">View watch</a>',
                ]
            )

        return "\n".join(lines)

    def _format_stored_alert(self, alert: dict[str, Any]) -> str:
        """
        Format an alert using only fields persisted in SQLite.

        Retry records intentionally do not depend on the live catalogue,
        because the catalogue may have changed since the original alert.
        """
        name = html.escape(
            str(alert.get("name") or alert.get("watch_name") or "Unknown watch")
        )

        source = html.escape(
            self._source_label(str(alert.get("source") or "unknown"))
        )

        lines = [
            "⌚ <b>HMT Watch Alert</b>",
            "",
            f"<b>{name}</b>",
            f"Source: {source}",
        ]

        event_type = str(alert.get("alert_type") or "")
        lines[0] = {
            "back_in_stock": "🟢 <b>Back in Stock — recorded event</b>",
            "out_of_stock": "🔴 <b>Out of Stock — recorded event</b>",
            "coming_soon": "🟠 <b>Coming Soon — recorded event</b>",
        }.get(event_type, "⌚ <b>HMT Watch Alert — recorded event</b>")
        if alert.get("created_at"):
            lines.append("Detected: " + html.escape(str(alert["created_at"])))
        stock_count = alert.get("stock_count")

        if event_type == "coming_soon":
            stock_text = "Coming soon"
        elif event_type == "out_of_stock":
            stock_text = "Out of stock"
        elif stock_count is not None:
            try:
                stock_text = f"{int(stock_count)} available"
            except (TypeError, ValueError):
                stock_text = str(stock_count)
        else:
            stock_text = "Quantity not supplied at detection"

        lines.append(f"Stock: <b>{html.escape(stock_text)}</b>")

        price = self._format_price(alert.get("price"))
        if price:
            lines.append(f"Price: {price}")

        product_url = alert.get("product_url")

        if product_url:
            url = html.escape(str(product_url), quote=True)
            lines.extend(
                [
                    "",
                    f'🛒 <a href="{url}">View watch</a>',
                ]
            )

        return "\n".join(lines)

    @staticmethod
    def _format_stock(watch: Any) -> str:
        if getattr(watch, "availability", None) == "coming_soon":
            return "Coming soon"
        if not getattr(watch, "in_stock", False):
            return "Out of stock"

        stock_count = getattr(watch, "stock_count", None)

        if stock_count is not None:
            try:
                return f"{int(stock_count)} available"
            except (TypeError, ValueError):
                pass

        return "In stock"

    @staticmethod
    def _format_price(price: Any) -> str | None:
        if price is None:
            return None

        try:
            value = float(price)
        except (TypeError, ValueError):
            return str(price)

        if value.is_integer():
            return f"₹{int(value):,}"

        return f"₹{value:,.2f}"

    @staticmethod
    def _source_label(source: str) -> str:
        labels = {
            "hmt.in": "HMT Watches",
            "hmt.store": "HMT Watches Store",
        }

        return labels.get(source, source)

    def _record_alert_state(self, watch_id: str) -> None:
        """
        Record an alert only after Telegram confirms success.
        """
        state = self.db.get_alert_state(watch_id)

        if state is None:
            state = AlertState(watch_id=watch_id)

        state.record_alert()
        self.db.save_alert_state(state)