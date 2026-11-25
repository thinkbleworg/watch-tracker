from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import requests

from config import WhatsAppConfig
from database import Database
from models import Watch
from notifier import TelegramNotifier
from whatsapp_notifier import WhatsAppNotifier, DeliveryError


@pytest.fixture
def settings():
    return WhatsAppConfig(enabled=True, api_key='test-secret', channel_id='123456@newsletter')


def make_watch(image='https://example.com/watch.png'):
    return Watch.create(id='watch-1', source='hmt.store', name='HMT Kohinoor & Co',
                        product_url='https://example.com/watch', image_url=image,
                        in_stock=True, stock_count=5, price=2350, collection='Kohinoor')


def enqueue(db, watch=None, kind='new'):
    watch = watch or make_watch()
    db.save_watch(watch)
    return db.create_alert(watch=watch, alert_type=kind)


def mock_response(code=200, data=None, headers=None):
    resp = Mock(status_code=code, headers=headers or {})
    resp.json.return_value = {'id': 'true_123456@newsletter_TEST'} if data is None else data
    return resp


def row(db, aid):
    with db.connection() as conn:
        return dict(conn.execute('SELECT * FROM alerts WHERE id=?', (aid,)).fetchone())


def test_upgrade_does_not_backfill(tmp_path, settings):
    path = tmp_path / 'test.db'
    old = Database(path)
    old_id = enqueue(old)
    # Simulate an actual pre-upgrade schema (not merely disabled WhatsApp).
    with old.connection() as conn:
        conn.execute('DROP INDEX idx_alerts_whatsapp_due')
        for name in [r['name'] for r in conn.execute('PRAGMA table_info(alerts)') if r['name'].startswith('whatsapp_')]:
            conn.execute(f'ALTER TABLE alerts DROP COLUMN {name}')
    db = Database(path, whatsapp_target=settings.target)
    aid = enqueue(db)
    assert row(db, old_id)['whatsapp_status'] == 'skipped'
    assert row(db, old_id)['status'] == 'pending'
    assert row(db, aid)['whatsapp_status'] == 'pending'
    db = Database(path, whatsapp_target=settings.target)
    assert row(db, aid)['whatsapp_status'] == 'pending'


def test_photo_payload_and_independent_success(tmp_path, settings):
    db = Database(tmp_path / 'test.db', whatsapp_target=settings.target)
    aid = enqueue(db)
    # Event snapshot is kept even if the live catalogue is updated.
    watch = make_watch()
    watch.price = 9999
    db.save_watch(watch)
    notifier = WhatsAppNotifier(db, settings)
    notifier._session.post = Mock(return_value=mock_response())
    assert notifier.deliver_due() == 1
    args, kw = notifier._session.post.call_args
    assert args[0].endswith('/api/sendImage')
    assert kw['headers']['X-Api-Key'] == 'test-secret'
    assert kw['allow_redirects'] is False
    assert kw['json']['chatId'] == settings.channel_id
    assert kw['json']['file']['mimetype'] == 'image/png'
    caption = kw['json']['caption']
    assert '*HMT Kohinoor & Co*' in caption
    assert '2350' in caption and '9999' not in caption
    assert 'https://example.com/watch' in caption
    assert 'Stock: In stock' in caption
    assert row(db, aid)['whatsapp_status'] == 'sent'
    assert row(db, aid)['whatsapp_message_id']
    assert row(db, aid)['status'] == 'pending'
    assert db.get_alert_state(watch.id) is None
    notifier._next_send = 0
    assert notifier.deliver_due() == 0
    assert notifier._session.post.call_count == 1


def test_telegram_success_does_not_consume_whatsapp(tmp_path, settings):
    db = Database(tmp_path / 'test.db', whatsapp_target=settings.target)
    aid = enqueue(db)
    telegram = TelegramNotifier(db, bot_token='token', chat_id='123')
    telegram._send_stored = Mock(return_value={'ok': True})
    assert telegram.deliver_due() == 1
    assert row(db, aid)['status'] == 'sent'
    assert row(db, aid)['whatsapp_status'] == 'pending'
    whatsapp = WhatsAppNotifier(db, settings)
    whatsapp._session.post = Mock(return_value=mock_response())
    assert whatsapp.deliver_due() == 1
    assert row(db, aid)['status'] == 'sent'
    assert row(db, aid)['whatsapp_status'] == 'sent'


def test_missing_image_uses_text(tmp_path, settings):
    db = Database(tmp_path / 'test.db', whatsapp_target=settings.target)
    aid = enqueue(db, make_watch(None))
    notifier = WhatsAppNotifier(db, settings)
    notifier._session.post = Mock(return_value=mock_response())
    assert notifier.deliver_due() == 1
    args, kw = notifier._session.post.call_args
    assert args[0].endswith('/api/sendText')
    assert 'text' in kw['json'] and 'file' not in kw['json']
    assert row(db, aid)['whatsapp_status'] == 'sent'


def test_image_discovered_later(tmp_path, settings):
    db = Database(tmp_path / 'test.db', whatsapp_target=settings.target)
    enqueue(db, make_watch(None))
    db.save_watch(make_watch())
    notifier = WhatsAppNotifier(db, settings)
    notifier._session.post = Mock(return_value=mock_response())
    assert notifier.deliver_due() == 1
    assert notifier._session.post.call_args.args[0].endswith('/api/sendImage')


def test_retry_429_does_not_affect_telegram(tmp_path, settings):
    db = Database(tmp_path / 'test.db', whatsapp_target=settings.target)
    aid = enqueue(db)
    notifier = WhatsAppNotifier(db, settings)
    notifier._session.post = Mock(return_value=mock_response(429, headers={'Retry-After':'120'}))
    assert notifier.deliver_due() == 0
    first = row(db, aid)
    assert first['whatsapp_status'] == 'retrying'
    assert first['whatsapp_attempts'] == 1
    assert first['whatsapp_next_attempt_at'] > 0
    assert first['status'] == 'pending'
    assert notifier.deliver_due() == 0
    assert notifier._session.post.call_count == 1
    with db.connection() as conn:
        conn.execute('UPDATE alerts SET whatsapp_next_attempt_at=0')
    notifier._next_send = notifier._blocked_until = 0
    notifier._session.post.return_value = mock_response()
    assert notifier.deliver_due() == 1
    assert row(db, aid)['whatsapp_attempts'] == 2


@pytest.mark.parametrize('response', [mock_response(500), mock_response(200, {}), mock_response(200, {'success':False,'id':'test'})])
def test_ambiguous_responses_require_manual_review(tmp_path, settings, response):
    db = Database(tmp_path / 'test.db', whatsapp_target=settings.target)
    aid = enqueue(db)
    notifier = WhatsAppNotifier(db, settings)
    notifier._session.post = Mock(return_value=response)
    assert notifier.deliver_due() == 0
    assert row(db, aid)['whatsapp_status'] == 'uncertain'
    notifier._next_send = 0
    assert notifier.deliver_due() == 0
    assert notifier._session.post.call_count == 1
    assert notifier.retry(aid)
    assert row(db, aid)['whatsapp_status'] == 'pending'


def test_read_timeout_is_uncertain(tmp_path, settings):
    db = Database(tmp_path / 'test.db', whatsapp_target=settings.target)
    aid = enqueue(db)
    notifier = WhatsAppNotifier(db, settings)
    notifier._session.post = Mock(side_effect=requests.ReadTimeout())
    notifier.deliver_due()
    assert row(db, aid)['whatsapp_status'] == 'uncertain'


def test_retry_limit(tmp_path, settings):
    settings = replace(settings, max_attempts=1)
    db = Database(tmp_path / 'test.db', whatsapp_target=settings.target)
    aid = enqueue(db)
    notifier = WhatsAppNotifier(db, settings)
    notifier._session.post = Mock(side_effect=requests.ConnectTimeout())
    notifier.deliver_due()
    assert row(db, aid)['whatsapp_status'] == 'failed'


def test_disabled_and_target_changes_are_safe(tmp_path, settings):
    db = Database(tmp_path / 'test.db', whatsapp_target=settings.target)
    aid = enqueue(db)
    for changed in [replace(settings, enabled=False), replace(settings, channel_id='654321@newsletter'), replace(settings, session='other')]:
        notifier = WhatsAppNotifier(db, changed)
        notifier._session.post = Mock()
        assert notifier.deliver_due() == 0
        notifier._session.post.assert_not_called()
    assert row(db, aid)['whatsapp_status'] == 'pending'


def test_private_chat_id_rejected(tmp_path, settings):
    settings = replace(settings, channel_id='123@c.us')
    db = Database(tmp_path / 'test.db', whatsapp_target=settings.target)
    aid = enqueue(db)
    notifier = WhatsAppNotifier(db, settings)
    notifier._session.post = Mock()
    with pytest.raises(DeliveryError):
        notifier.send('test')
    notifier._session.post.assert_not_called()
    assert row(db, aid)['whatsapp_status'] == 'skipped'


def test_old_stock_alert_expires(tmp_path, settings):
    db = Database(tmp_path / 'test.db', whatsapp_target=settings.target)
    aid = enqueue(db)
    with db.connection() as conn:
        conn.execute('UPDATE alerts SET created_at=?', ((datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),))
    notifier = WhatsAppNotifier(db, settings)
    notifier._session.post = Mock()
    assert notifier.deliver_due() == 0
    assert row(db, aid)['whatsapp_status'] == 'expired'
    assert row(db, aid)['status'] == 'pending'
    notifier._session.post.assert_not_called()


def test_restart_does_not_resend_interrupted_post(tmp_path, settings):
    db = Database(tmp_path / 'test.db', whatsapp_target=settings.target)
    aid = enqueue(db)
    notifier = WhatsAppNotifier(db, settings)
    assert notifier._claim()['id'] == aid
    assert row(db, aid)['whatsapp_status'] == 'sending'
    notifier._session.post = Mock()
    notifier.start()
    notifier.stop()
    assert row(db, aid)['whatsapp_status'] == 'uncertain'
    notifier._session.post.assert_not_called()


def test_deleted_alert_removed_from_whatsapp_queue(tmp_path, settings):
    db = Database(tmp_path / 'test.db', whatsapp_target=settings.target)
    aid = enqueue(db)
    assert db.delete_alert(aid)
    notifier = WhatsAppNotifier(db, settings)
    notifier._session.post = Mock()
    assert notifier.deliver_due() == 0
    notifier._session.post.assert_not_called()
