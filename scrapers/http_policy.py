"""Per-host pacing and circuit breaker. Shared by all scraper instances."""
import os
import random
import threading
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
import requests

class HostPolicy:
    def __init__(self):
        self.lock = threading.Lock()
        self.next_request = 0.0
        self.blocked_until = 0.0
        self.failures = 0
        self.requests = 0
        self.last_status = None

_policies = {}
_registry_lock = threading.Lock()

def request(session, method, url, *, timeout, retries=3, **kwargs):
    host = urlsplit(url).netloc
    with _registry_lock:
        policy = _policies.setdefault(host, HostPolicy())
    with policy.lock:
        if time.monotonic() < policy.blocked_until:
            raise RuntimeError(f"{host}: source cooling down after an HTTP failure")
        for attempt in range(max(1, retries)):
            time.sleep(max(0, policy.next_request - time.monotonic()))
            try:
                policy.requests += 1
                response = session.request(method, url, timeout=timeout, **kwargs)
                policy.last_status = response.status_code
                policy.next_request = time.monotonic() + request_spacing() + random.uniform(0, 0.25)
                if response.status_code in {403, 429} or response.status_code >= 500:
                    policy.failures += 1
                    delay = min(1800, 60 * 2 ** min(policy.failures - 1, 5))
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            delay = max(delay, float(retry_after))
                        except ValueError:
                            try:
                                delay = max(delay, parsedate_to_datetime(retry_after).timestamp() - time.time())
                            except (ValueError, TypeError, OverflowError):
                                pass
                    policy.blocked_until = time.monotonic() + delay
                    response.raise_for_status()
                response.raise_for_status()
                policy.failures = 0
                return response
            except requests.HTTPError:
                # Retrying a denied request immediately only worsens the block.
                raise
            except (requests.Timeout, requests.ConnectionError):
                policy.failures += 1
                policy.next_request = time.monotonic() + min(30, 2 ** attempt)
                if attempt + 1 >= max(1, retries):
                    policy.blocked_until = time.monotonic() + 60
                    raise


def policy_status():
    with _registry_lock:
        return {host: {'cooldown_seconds': max(0, round(p.blocked_until-time.monotonic())),
                       'consecutive_failures': p.failures, 'requests': p.requests, 'last_http_status': p.last_status}
                for host, p in _policies.items()}


def request_spacing():
    try:
        return max(1.0, min(60.0, float(os.getenv('HMT_MIN_REQUEST_INTERVAL_SECONDS', '2'))))
    except ValueError:
        return 2.0
