import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from bs4 import BeautifulSoup
from config import config, get_source
from database import Database
from models import Watch
from notifier import TelegramNotifier
from scheduler import TrackerScheduler
from scrapers import http_policy
from scrapers.hmt_official import OfficialHMTScraper
from scrapers.hmt_store import HMTStoreScraper
from tests.test_notifier import FakeSession
from tests.test_tracker import make_watch, make_matching_rule, process_existing_watch
from tracker import Tracker


def db_at(tmp_path):
    return Database(tmp_path / 'test.db')


def test_coming_soon_wins_over_buy_control_and_roundtrips(tmp_path):
    scraper = OfficialHMTScraper(get_source('hmt.in'))
    card = BeautifulSoup('''<div class="bc_p_item"><a class="bc_p_name">HMT Test</a>
      <a class="bc_p_img" href="product_overview?id=abc"></a><span>RS. 1000</span>
      <div class="outofstock">Coming Soon</div><button onclick="add_cart(123,1)" prodqty="4"></button></div>''', 'html.parser').div
    watch = scraper._parse_card(card)
    assert watch.availability == 'coming_soon'
    assert not watch.in_stock
    db = db_at(tmp_path)
    db.save_watch(watch)
    assert db.get_watch(watch.id).display_stock == 'Coming soon'
    watch.availability = 'available'; watch.in_stock = True
    db.save_watches([watch])
    assert db.get_watch(watch.id).availability == 'available'


def test_legacy_database_migration_keeps_watch_and_rule(tmp_path):
    db = db_at(tmp_path)
    db.save_watch(make_watch())
    db.save_tracking_rule(make_matching_rule())
    with db.connection() as conn:
        conn.execute('ALTER TABLE watches DROP COLUMN availability')
    db = db_at(tmp_path)
    assert db.get_watch('watch-1').availability == 'available'
    assert db.get_tracking_rules()[0].id == 'rule-1'


def test_coming_soon_transition_alert_and_then_back_in_stock(tmp_path):
    db = db_at(tmp_path)
    tracker = Tracker(db, tracker_config=replace(config, alert_back_in_stock=True))
    db.save_watch(make_watch(in_stock=False))
    coming = make_watch(in_stock=False); coming.availability = 'coming_soon'
    process_existing_watch(db, tracker, coming)
    process_existing_watch(db, tracker, coming)
    process_existing_watch(db, tracker, make_watch())
    assert [x['alert_type'] for x in reversed(db.get_alerts())] == ['coming_soon', 'back_in_stock']


def test_unknown_stock_does_not_generate_false_oos(tmp_path):
    db = db_at(tmp_path)
    tracker = Tracker(db, tracker_config=replace(config, alert_out_of_stock=True))
    db.save_watch(make_watch())
    unknown = make_watch(in_stock=False); unknown.availability = 'unknown'
    process_existing_watch(db, tracker, unknown)
    assert db.get_watch('watch-1').in_stock
    assert db.get_alerts() == []


@pytest.mark.parametrize('status', [403, 429, 503])
def test_http_block_stops_retries_and_survives_new_sessions(monkeypatch, status):
    http_policy._policies.clear()
    monkeypatch.setattr(http_policy.time, 'sleep', lambda _: None)
    response = requests.Response(); response.status_code = status
    response.headers['Retry-After'] = '600'
    session = Mock(); session.request.return_value = response
    with pytest.raises(requests.HTTPError):
        http_policy.request(session, 'GET', 'https://test.example/p', timeout=2, retries=3)
    with pytest.raises(RuntimeError, match='cooling down'):
        http_policy.request(Mock(), 'GET', 'https://test.example/q', timeout=2)
    assert session.request.call_count == 1
    http_policy._policies.clear()


def test_outbox_sends_snapshot_even_if_current_stock_changed(tmp_path):
    db = db_at(tmp_path)
    watch = make_watch(); db.save_watch(watch)
    db.create_alert(watch=watch, alert_type='back_in_stock')
    watch.in_stock = False; watch.availability = 'out_of_stock'; db.save_watch(watch)
    notifier = TelegramNotifier(db, bot_token='token', chat_id='chat')
    notifier._session = FakeSession()
    assert notifier.deliver_due() == 1
    text = notifier._session.calls[0]['data']['text']
    assert 'Back in Stock' in text and '5 available' in text
    assert db.get_alerts()[0]['status'] == 'sent'


def test_outbox_failure_is_deferred(tmp_path):
    db = db_at(tmp_path)
    watch = make_watch(); db.save_watch(watch)
    db.create_alert(watch=watch, alert_type='back_in_stock')
    notifier = TelegramNotifier(db, bot_token='token', chat_id='chat')
    notifier._session = Mock(); notifier._session.post.side_effect = requests.Timeout()
    assert notifier.deliver_due() == 0
    assert notifier.deliver_due() == 0
    assert notifier._session.post.call_count == 1
    assert db.get_alerts()[0]['attempts'] == 1


def test_telegram_retry_after_blocks_other_items(tmp_path):
    notifier = TelegramNotifier(db_at(tmp_path), bot_token='token', chat_id='chat')
    response = Mock(status_code=429)
    response.json.return_value = {'parameters': {'retry_after': 600}}
    with pytest.raises(RuntimeError, match='wait 600'):
        notifier._check_rate_limit(response)
    with pytest.raises(RuntimeError, match='cooldown'):
        notifier._pace()


@pytest.mark.parametrize(('duration', 'expected'), [(20, [0, 60, 120]), (80, [0, 120, 240])])
def test_scheduler_start_cadence_and_no_catchup(monkeypatch, duration, expected):
    import scheduler as module
    now = [0.0]; starts = []
    scheduler = TrackerScheduler(Mock(), interval_seconds=60)
    class Event:
        stopped = False
        def is_set(self): return self.stopped
        def wait(self, seconds): now[0] += seconds
    event = Event(); scheduler._stop_event = event
    monkeypatch.setattr(module.time, 'monotonic', lambda: now[0])
    def run(_):
        starts.append(now[0]); now[0] += duration
        if len(starts) == 3: event.stopped = True
    scheduler._run_safely = run
    scheduler._worker(True)
    assert starts == expected


def test_store_streams_before_next_page_and_guards_repeating_pages():
    scraper = HMTStoreScraper(base_url='https://example.com', page_size=1)
    seen = []
    def fetch(**kwargs):
        if kwargs['offset'] == 1:
            assert seen == ['watch-1']
            return []
        return [{}]
    scraper._fetch_page = fetch
    scraper._parse_product = lambda _: make_watch()
    assert len(scraper.scrape(on_watch=lambda w: seen.append(w.id))) == 1
    scraper._fetch_page = lambda **_: [{}]
    with pytest.raises(RuntimeError, match='no progress'):
        scraper.scrape()


def test_ambiguous_untracked_stock_does_not_request_details():
    scraper = HMTStoreScraper(base_url='https://example.com')
    scraper.should_verify = lambda *_: False
    scraper._fetch_product_detail = Mock()
    scraper._stock({'currentStock': 0, 'additionalAttributes': {'isOOS': False}}, product_id='123')
    assert scraper._stock_uncertain
    scraper._fetch_product_detail.assert_not_called()
