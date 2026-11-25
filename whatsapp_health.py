"""Low-overhead, read-only WAHA session checks and optional Telegram notices."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

import requests

from config import WhatsAppConfig
from database import Database
from notifier import TelegramNotifier

logger = logging.getLogger(__name__)

# Never include WAHA response bodies, exception strings, keys or account data in notices.
SESSION_STATES = {"STARTING", "SCAN_QR_CODE", "STOPPED", "FAILED", "WORKING"}


def bounded_int(name: str, default: int, low: int, high: int) -> int:
    try:
        return max(low, min(high, int(os.getenv(name, str(default)))))
    except ValueError:
        logger.warning("Invalid %s; using default", name)
        return default


class WhatsAppHealth:
    def __init__(self, db: Database, settings: WhatsAppConfig, telegram: TelegramNotifier,
                 *, interval: int = 60, failures: int = 3, cooldown: int = 3600,
                 read_key: str = "", notify: bool = False, active: bool = True):
        self.db, self.settings, self.telegram = db, settings, telegram
        self.interval, self.failures, self.cooldown = interval, failures, cooldown
        self.read_key = read_key or settings.api_key
        self.active = active and settings.target is not None
        self.notify = self.active and notify and telegram.enabled
        self._http = requests.Session()
        self._http.trust_env = False
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        # Persist only incident state, scoped to destination and session. No credentials.
        scope = json.dumps([settings.api_url, settings.session, settings.channel_id,
                            telegram.chat_id])
        self._key = 'whatsapp_health_v1_' + hashlib.sha256(scope.encode()).hexdigest()[:24]
        self._state = {"incident": False, "announced": False, "last_attempt": 0.0}
        try:
            old = json.loads(db.get_setting(self._key, '{}') or '{}')
            if isinstance(old, dict):
                self._state.update(incident=old.get('incident') is True,
                                   announced=old.get('announced') is True,
                                   last_attempt=float(old.get('last_attempt', 0)))
        except (ValueError, TypeError, OverflowError):
            pass
        self._snapshot = {"status": "checking" if self.active else "disabled",
                          "checked_at": None, "consecutive_failures": 0}

    @classmethod
    def from_env(cls, db, settings, telegram):
        chat_id = os.getenv('TELEGRAM_HEALTH_CHAT_ID', '').strip()
        # The existing stock-alert chat is never selected implicitly.
        operator = telegram if chat_id and chat_id == telegram.chat_id else TelegramNotifier(
            db, bot_token=telegram.bot_token, chat_id=chat_id or 'not-configured', timeout=10)
        return cls(db, settings, operator,
                   interval=bounded_int('WHATSAPP_HEALTH_INTERVAL_SECONDS', 60, 30, 3600),
                   failures=bounded_int('WHATSAPP_HEALTH_FAILURE_THRESHOLD', 3, 2, 10),
                   cooldown=bounded_int('WHATSAPP_HEALTH_COOLDOWN_SECONDS', 3600, 300, 86400),
                   read_key=os.getenv('WHATSAPP_HEALTH_API_KEY', '').strip(),
                   notify=bool(chat_id),
                   active=os.getenv('WHATSAPP_HEALTH_ENABLED', 'true').lower().strip() in {'true','1','yes','on'})

    def start(self):
        if not self.active or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='whatsapp-health', daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.check_once()
            except Exception:
                # Avoid logging exceptions that could include private URLs or secrets.
                logger.warning('WhatsApp health iteration failed')
            self._stop.wait(self.interval)

    def _probe(self):
        try:
            r = self._http.get(f'{self.settings.api_url.rstrip("/")}/api/sessions/{self.settings.session}',
                               headers={'X-Api-Key': self.read_key}, timeout=(3, 7),
                               allow_redirects=False)
            if r.status_code in (401, 403):
                return 'auth_required'
            if r.status_code == 404:
                return 'session_not_found'
            if r.status_code != 200:
                return 'api_error'
            body = r.json()
            if not isinstance(body, dict) or body.get('name') != self.settings.session:
                return 'invalid_response'
            status = body.get('status')
            return status.lower() if isinstance(status, str) and status in SESSION_STATES else 'unknown_session_status'
        except (ValueError, TypeError):
            return 'invalid_response'
        except requests.RequestException:
            return 'unreachable'

    def _persist(self):
        self.db.set_setting(self._key, json.dumps(self._state))

    def check_once(self):
        if not self.active:
            return self.status()
        status = self._probe()
        with self._lock:
            n = 0 if status == 'working' else self._snapshot['consecutive_failures'] + 1
            self._snapshot = {'status': status, 'consecutive_failures': n,
                              'checked_at': datetime.now(timezone.utc).isoformat()}
        if self._stop.is_set():
            return self.status()
        if status == 'working':
            if self._state['incident']:
                announced = self._state['announced']
                self._state.update(incident=False, announced=False, last_attempt=0.0)
                self._persist()
                if announced and self.notify:
                    self._notice('✅ <b>HMT Tracker — WhatsApp health recovered</b>\nWAHA reports the session is WORKING. Verify Channel delivery if needed.')
        elif n >= self.failures:
            if not self._state['incident']:
                self._state.update(incident=True, announced=False, last_attempt=0.0)
                self._persist()
                logger.warning('WhatsApp health issue: %s', status)
            now = time.time()
            if self.notify and not self._state['announced'] and now - self._state['last_attempt'] >= self.cooldown:
                # Save before network call; ambiguous failures are cooldown limited.
                self._state['last_attempt'] = now
                self._persist()
                if self._notice('⚠️ <b>HMT Tracker — WhatsApp health warning</b>\n'
                                f'Check: {status} ({n} consecutive unsuccessful checks).\n'
                                'Inspect WAHA and its session. Stock alerts on Telegram remain independent.'):
                    self._state['announced'] = True
                    self._persist()
        return self.status()

    def _notice(self, message):
        try:
            self.telegram.test_send(message)
            return True
        except Exception:
            logger.warning('Telegram health notice failed; no credentials logged')
            return False

    def status(self):
        with self._lock:
            return {**self._snapshot, 'monitoring': self.active,
                    'telegram_notices': self.notify, 'interval_seconds': self.interval,
                    'failure_threshold': self.failures}
