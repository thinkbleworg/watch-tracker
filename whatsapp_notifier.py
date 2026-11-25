"""Independent, opt-in WAHA Channel outbox. No calls to personal chat IDs."""
from __future__ import annotations

import html
import json
import logging
import mimetypes
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests

from config import WhatsAppConfig
from database import Database
from models import Watch, utc_now
from notifier import TelegramNotifier

logger = logging.getLogger(__name__)


class DeliveryError(RuntimeError):
    def __init__(self, message: str, *, state: str = "failed", delay: int = 0):
        super().__init__(message)
        self.state = state
        self.delay = delay


class WhatsAppNotifier:
    def __init__(self, db: Database, settings: WhatsAppConfig):
        self.db = db
        self.settings = settings
        self._session = requests.Session()
        # Do not send the API key through an environment-configured proxy.
        self._session.trust_env = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._next_send = 0.0
        self._blocked_until = 0.0
        # Reuse the existing Telegram formatting logic without sending anything.
        self._formatter = TelegramNotifier(db)

    @property
    def enabled(self) -> bool:
        return self.settings.target is not None

    @property
    def _target(self) -> tuple[str, str]:
        return self.settings.session, self.settings.channel_id

    def start(self) -> None:
        if not self.enabled:
            if self.settings.enabled:
                logger.warning("WhatsApp enabled but configuration invalid; Telegram unaffected")
            return
        if self._thread and self._thread.is_alive():
            return
        # A previous process could have died after WAHA accepted a message.
        # Do not automatically send it again. Single app process is required.
        with self.db.connection() as conn:
            conn.execute("""UPDATE alerts SET whatsapp_status='uncertain',
                whatsapp_error='Interrupted during send; check Channel before retrying'
                WHERE whatsapp_status='sending' AND whatsapp_session=? AND whatsapp_channel_id=?""",
                self._target)
        self._stop.clear()
        self._thread = threading.Thread(target=self._worker, name="whatsapp-outbox", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.settings.timeout_seconds + 7)

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                self.deliver_due()
            except Exception:
                logger.exception("WhatsApp outbox iteration failed")
            self._stop.wait(1)

    def status_counts(self) -> dict[str, int]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT whatsapp_status, COUNT(*) AS n FROM alerts GROUP BY whatsapp_status").fetchall()
        return {row["whatsapp_status"]: row["n"] for row in rows}

    def _claim(self) -> dict | None:
        # Reserve the item before doing network I/O, in one SQLite transaction.
        with self.db.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cutoff = datetime.fromtimestamp(time.time() - self.settings.max_age_seconds, timezone.utc).isoformat()
            conn.execute("""UPDATE alerts SET whatsapp_status='expired',
                whatsapp_error='Alert too old to publish automatically'
                WHERE whatsapp_status IN ('pending','retrying') AND whatsapp_session=?
                AND whatsapp_channel_id=? AND created_at < ?""", (*self._target, cutoff))
            row = conn.execute("""SELECT * FROM alerts WHERE whatsapp_status IN ('pending','retrying')
                AND whatsapp_session=? AND whatsapp_channel_id=? AND whatsapp_next_attempt_at<=?
                ORDER BY CASE WHEN alert_type IN ('back_in_stock','new','tracked') THEN 0 ELSE 1 END,
                created_at, id LIMIT 1""", (*self._target, time.time())).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE alerts SET whatsapp_status='sending', whatsapp_attempts=whatsapp_attempts+1 WHERE id=?", (row['id'],))
            return dict(row)

    def deliver_due(self) -> int:
        if not self.enabled or time.monotonic() < max(self._next_send, self._blocked_until):
            return 0
        alert = self._claim()
        if alert is None:
            return 0
        attempts = int(alert['whatsapp_attempts']) + 1
        message_id = None
        error = None
        next_attempt = 0
        try:
            caption, image = self._format_alert(alert)
            message_id = self.send(caption, image)
            state = 'sent'
        except DeliveryError as exc:
            state = exc.state
            error = str(exc)
            if state == 'retrying':
                delay = max(exc.delay, min(900, 10 * 2 ** min(attempts - 1, 7)))
                if attempts >= self.settings.max_attempts:
                    state = 'failed'
                else:
                    next_attempt = time.time() + delay
                if exc.delay:
                    self._blocked_until = time.monotonic() + delay
        except Exception:
            # Unexpected local failure after claim: prefer manual review over duplication.
            state, error = 'uncertain', 'Unexpected delivery error; check Channel before retrying'
            logger.exception("WhatsApp delivery error for alert %s", alert['id'])
        finally:
            self._next_send = time.monotonic() + self.settings.min_interval_seconds
        with self.db.connection() as conn:
            conn.execute("""UPDATE alerts SET whatsapp_status=?, whatsapp_error=?, whatsapp_next_attempt_at=?,
                whatsapp_message_id=?, whatsapp_sent_at=? WHERE id=? AND whatsapp_status='sending'""",
                (state, error, next_attempt, message_id, utc_now() if state == 'sent' else None, alert['id']))
        logger.info("WhatsApp alert %s: %s", alert['id'], state)
        return int(state == 'sent')

    def _format_alert(self, alert: dict) -> tuple[str, str | None]:
        # Stock, price and detection timestamp always come from the immutable event.
        watch = Watch.from_dict(json.loads(alert['snapshot']))
        text = self._formatter._format_watch(watch, alert_type=alert['alert_type'])
        # Translate Telegram's HTML markup into WhatsApp's native bold markup.
        text = html.unescape(text.replace('<b>', '*').replace('</b>', '*'))
        if watch.product_url:
            text += '\n\n🔗 ' + watch.product_url
        image = watch.image_url
        if not image:
            current = self.db.get_watch(watch.id)
            image = current.image_url if current else None
        return text, image

    def send(self, caption: str, image_url: str | None = None) -> str:
        """Send once. A successful response is WAHA acceptance, not follower delivery."""
        if not self.settings.configured:
            raise DeliveryError("Invalid WAHA configuration or Channel ID")
        payload = {"session": self.settings.session, "chatId": self.settings.channel_id}
        if image_url:
            parsed = urlsplit(image_url)
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
                raise DeliveryError('Invalid watch image URL')
            mime = mimetypes.guess_type(parsed.path)[0] or 'image/jpeg'
            if not mime.startswith('image/'):
                raise DeliveryError('Watch URL is not a recognized image type')
            ext = mimetypes.guess_extension(mime) or '.jpg'
            payload.update(file={"mimetype": mime, "url": image_url, "filename": 'watch' + ext}, caption=caption)
            endpoint = '/api/sendImage'
        else:
            payload['text'] = caption
            endpoint = '/api/sendText'
        try:
            response = self._session.post(self.settings.api_url.rstrip('/') + endpoint,
                json=payload, headers={'X-Api-Key': self.settings.api_key, 'Accept': 'application/json'},
                timeout=(5, self.settings.timeout_seconds), allow_redirects=False)
        except requests.ConnectTimeout as exc:
            raise DeliveryError('WAHA connection timed out before send', state='retrying') from exc
        except requests.ConnectionError as exc:
            # Connection refused / DNS lookup errors are safe to retry, but a reset may be post-send.
            from urllib3.exceptions import NewConnectionError
            reason = getattr(exc.args[0], 'reason', None) if exc.args else None
            if isinstance(reason, NewConnectionError):
                raise DeliveryError('WAHA not reachable', state='retrying') from exc
            raise DeliveryError('WAHA connection interrupted; check Channel before retrying', state='uncertain') from exc
        except requests.RequestException as exc:
            raise DeliveryError('WAHA response unavailable; check Channel before retrying', state='uncertain') from exc
        code = response.status_code
        if code in {401, 403, 404, 422, 429}:
            delay = 60
            if code == 429:
                try:
                    delay = max(60, int(response.headers.get('Retry-After', 60)))
                except (ValueError, TypeError):
                    pass
            raise DeliveryError(f'WAHA HTTP {code}; check API key, session and Channel', state='retrying', delay=delay)
        if 400 <= code < 500:
            raise DeliveryError(f'WAHA rejected message (HTTP {code})')
        if not 200 <= code < 300:
            raise DeliveryError(f'WAHA HTTP {code}; check Channel before retrying', state='uncertain')
        try:
            result = response.json()
            message_id = result.get('id') if isinstance(result, dict) else None
            if isinstance(message_id, dict):
                message_id = message_id.get('_serialized') or message_id.get('id')
            if not isinstance(message_id, str) or not message_id.strip() or result.get('error') or result.get('success') is False:
                raise ValueError('No successful message ID')
        except (ValueError, TypeError):
            raise DeliveryError('WAHA returned no confirmed message ID; check Channel before retrying', state='uncertain') from None
        return message_id

    def retry(self, alert_id: int) -> bool:
        """Operator has checked the actual Channel and explicitly requests a retry."""
        if not self.settings.configured:
            raise ValueError('WhatsApp configuration is invalid')
        with self.db.connection() as conn:
            result = conn.execute("""UPDATE alerts SET whatsapp_status='pending', whatsapp_attempts=0,
                whatsapp_next_attempt_at=0, whatsapp_error=NULL
                WHERE id=? AND whatsapp_session=? AND whatsapp_channel_id=?
                AND whatsapp_status IN ('failed','uncertain')""", (alert_id, *self._target))
            return result.rowcount == 1
