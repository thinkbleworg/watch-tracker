import sqlite3
import time

import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from auth import AuthStore, COOKIE, MAX_FAILURES, WINDOW, install_auth, token_hash

ORIGIN = 'https://34.10.110.32'
PASSWORD = 'correct horse battery staple'


@pytest.fixture
def store(tmp_path):
    a = AuthStore(tmp_path / 'auth.db')
    a.set_user('admin', PASSWORD)
    a.set_user('viewer', PASSWORD, 'viewer')
    return a


@pytest.fixture
def client(store):
    app = FastAPI()
    install_auth(app, Jinja2Templates(directory='templates'), store, {ORIGIN})
    @app.get('/')
    def index(): return {'home': True}
    @app.get('/api/config')
    def config(): return {'private': True}
    @app.post('/api/run')
    def run(): return {'ok': True}
    @app.put('/api/settings')
    def settings(): return {'ok': True}
    @app.delete('/api/alerts/1')
    def delete(): return {'ok': True}
    @app.get('/health')
    def health(): return {'status': 'ok'}
    return TestClient(app, base_url=ORIGIN, follow_redirects=False)


def login(client, username='admin', password=PASSWORD):
    return client.post('/login', data={'username':username,'password':password}, headers={'Origin':ORIGIN})


def test_default_deny(client):
    assert client.get('/').status_code == 303
    assert client.get('/api/config').status_code == 401
    assert client.get('/docs').status_code == 303
    assert client.post('/api/run',headers={'Origin':ORIGIN}).status_code == 401
    assert client.get('/health').status_code == 200
    assert client.get('/login').status_code == 200


def test_login_and_cookie(client, store):
    r = login(client)
    assert r.status_code == 303
    cookie = r.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie
    assert client.get('/api/config').json() == {'private': True}
    with store.connection() as c:
        row = c.execute('SELECT token_hash FROM sessions').fetchone()
        assert row[0] == token_hash(client.cookies[COOKIE])
        assert c.execute('SELECT password_hash FROM users WHERE username="admin"').fetchone()[0].startswith('$argon2id$')


def test_csrf(client):
    assert client.post('/login', data={'username':'admin','password':PASSWORD}).status_code == 403
    assert login(client).status_code == 303
    for method,path in [('POST','/api/run'),('PUT','/api/settings'),('DELETE','/api/alerts/1'),('POST','/logout')]:
        assert client.request(method,path).status_code == 403
        assert client.request(method,path,headers={'Origin':'https://evil.example'}).status_code == 403
    assert client.post('/api/run',headers={'Origin':ORIGIN}).status_code == 200


def test_viewer_role(client):
    assert login(client,'viewer').status_code == 303
    assert client.get('/api/config').status_code == 200
    assert client.post('/api/run',headers={'Origin':ORIGIN}).status_code == 403
    assert client.put('/api/settings',headers={'Origin':ORIGIN}).status_code == 403
    assert client.delete('/api/alerts/1',headers={'Origin':ORIGIN}).status_code == 403
    assert client.post('/logout',headers={'Origin':ORIGIN}).status_code == 303


def test_logout_revoke(client, store):
    login(client)
    token = client.cookies[COOKIE]
    assert client.post('/logout', headers={'Origin':ORIGIN}).status_code == 303
    assert store.identity(token) is None
    assert client.get('/api/config').status_code == 401


def test_password_rotation_and_delete(client, store):
    login(client)
    token = client.cookies[COOKIE]
    store.set_user('admin', 'new password long enough')
    assert store.identity(token) is None
    assert login(client,password='new password long enough').status_code == 303
    token = client.cookies[COOKIE]
    store.delete_user('admin')
    assert store.identity(token) is None


def test_expiry(client, store):
    login(client)
    with store.connection() as c: c.execute('UPDATE sessions SET expires=?',(int(time.time())-1,))
    assert client.get('/api/config').status_code == 401


def test_rate_limit_persists(client, store):
    for _ in range(MAX_FAILURES): assert login(client,password='wrong').status_code == 401
    assert login(client).status_code == 429
    reopened = AuthStore(store.path)
    assert reopened.login('admin',PASSWORD)[0] == 'limited'
    reopened.clear_limits()
    assert login(client).status_code == 303


def test_wrong_host(client):
    assert client.get('/health',headers={'Host':'evil.example'}).status_code == 400


def test_body_bound(client):
    assert client.post('/login',data={'username':'admin','password':'x'*5000},headers={'Origin':ORIGIN}).status_code == 413


def test_fail_closed_empty_database(tmp_path):
    a = AuthStore(tmp_path/'empty.db')
    assert a.login('admin',PASSWORD)[0] == 'invalid'
    assert a.identity('invalid') is None


def test_headers(client):
    r = client.get('/login')
    assert r.headers['cache-control'] == 'no-store'
    assert r.headers['x-frame-options'] == 'DENY'
