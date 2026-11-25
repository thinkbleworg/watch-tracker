from dataclasses import replace
from unittest.mock import Mock
import json

import pytest
import requests

from config import WhatsAppConfig
from database import Database
from whatsapp_health import WhatsAppHealth


@pytest.fixture
def setup(tmp_path):
    db = Database(tmp_path / 'health.db')
    config = WhatsAppConfig(enabled=True, api_key='SEND_SECRET', channel_id='123@newsletter')
    telegram = Mock(enabled=True, chat_id='456')
    health = WhatsAppHealth(db, config, telegram, read_key='READ_SECRET', notify=True)
    health._http.get = Mock()
    return db, config, telegram, health


def response(code=200, status='WORKING', name='default'):
    r = Mock(status_code=code)
    r.json.return_value = {'name': name, 'status': status, 'me': {'id': 'PRIVATE'}}
    return r


def test_working_no_private_data(setup):
    _, _, tg, h = setup
    h._http.get.return_value = response()
    assert h.check_once()['status'] == 'working'
    args, kw = h._http.get.call_args
    assert args[0].endswith('/api/sessions/default')
    assert kw['headers'] == {'X-Api-Key': 'READ_SECRET'}
    assert kw['allow_redirects'] is False and h._http.trust_env is False
    assert 'PRIVATE' not in json.dumps(h.status()) and 'SECRET' not in json.dumps(h.status())
    tg.test_send.assert_not_called()


@pytest.mark.parametrize('code,status,expected', [(401,'FAILED','auth_required'),(403,'FAILED','auth_required'),(404,'FAILED','session_not_found'),(500,'FAILED','api_error'),(200,'FAILED','failed'),(200,'SCAN_QR_CODE','scan_qr_code')])
def test_health_categories(setup, code, status, expected):
    _, _, _, h = setup
    h._http.get.return_value = response(code, status)
    assert h.check_once()['status'] == expected


def test_threshold_notice_recovery(setup):
    _, _, tg, h = setup
    h._http.get.return_value = response(status='STOPPED')
    for _ in range(2): h.check_once()
    tg.test_send.assert_not_called()
    for _ in range(6): h.check_once()
    assert tg.test_send.call_count == 1
    h._http.get.return_value = response()
    h.check_once()
    assert tg.test_send.call_count == 2
    assert 'recovered' in tg.test_send.call_args.args[0]
    assert h.status()['consecutive_failures'] == 0
    h.check_once()
    assert tg.test_send.call_count == 2


def test_restart_does_not_repeat_incident(setup):
    db, settings, tg, h = setup
    h._http.get.return_value = response(status='FAILED')
    for _ in range(3): h.check_once()
    next_h = WhatsAppHealth(db, settings, tg, notify=True)
    next_h._http.get = Mock(return_value=response(status='FAILED'))
    for _ in range(4): next_h.check_once()
    assert tg.test_send.call_count == 1
    next_h._http.get.return_value = response()
    next_h.check_once()
    assert tg.test_send.call_count == 2


def test_telegram_failure_cooldown(setup):
    _, _, tg, h = setup
    tg.test_send.side_effect = RuntimeError('PRIVATE SECRET')
    h._http.get.side_effect = requests.Timeout('PRIVATE SECRET')
    for _ in range(6): h.check_once()
    assert tg.test_send.call_count == 1
    assert h.status()['status'] == 'unreachable'
    assert 'SECRET' not in json.dumps(h.status())


def test_disabled_and_no_notice(setup):
    db, settings, tg, _ = setup
    h = WhatsAppHealth(db, replace(settings, enabled=False), tg, notify=True)
    h._http.get = Mock()
    assert h.check_once()['status'] == 'disabled'
    h._http.get.assert_not_called()
    h = WhatsAppHealth(db, settings, tg, notify=False)
    h._http.get = Mock(return_value=response(status='FAILED'))
    for _ in range(4): h.check_once()
    tg.test_send.assert_not_called()


def test_wrong_session_and_invalid_json(setup):
    _, _, _, h = setup
    h._http.get.return_value = response(name='other')
    assert h.check_once()['status'] == 'invalid_response'
    h._http.get.return_value.json.side_effect = ValueError('SECRET')
    assert h.check_once()['status'] == 'invalid_response'


def test_no_implicit_stock_channel_notices(setup, monkeypatch):
    db, settings, tg, _ = setup
    monkeypatch.delenv('TELEGRAM_HEALTH_CHAT_ID', raising=False)
    tg.bot_token = 'fake'
    h = WhatsAppHealth.from_env(db, settings, tg)
    assert h.status()['telegram_notices'] is False
