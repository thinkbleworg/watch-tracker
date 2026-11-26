"""Local account authentication; no external identity service or API secrets."""
from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

COOKIE = "hmt_session"
TTL = 12 * 3600
WINDOW = 300
MAX_FAILURES = 8
SAFE = {"GET", "HEAD", "OPTIONS"}
USERNAME = re.compile(r"[a-zA-Z0-9_.-]{1,64}\Z")
HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        self._lock = threading.Lock()
        self._dummy = HASHER.hash(secrets.token_urlsafe(32))
        with self.connection() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','viewer')));
                CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, username TEXT NOT NULL REFERENCES users(username) ON DELETE CASCADE, expires INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS login_failures(at INTEGER NOT NULL);
            """)

    @contextmanager
    def connection(self):
        c = sqlite3.connect(self.path, timeout=5)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            with c:
                yield c
        finally:
            c.close()

    def set_user(self, username, password, role='admin'):
        if not USERNAME.fullmatch(username) or role not in ('admin','viewer'):
            raise ValueError('Invalid username or role')
        if len(password) < 14 or len(password.encode()) > 256:
            raise ValueError('Password must have at least 14 characters and at most 256 UTF-8 bytes')
        hashed = HASHER.hash(password)
        with self.connection() as c:
            c.execute('INSERT INTO users VALUES(?,?,?) ON CONFLICT(username) DO UPDATE SET password_hash=excluded.password_hash, role=excluded.role', (username, hashed, role))
            c.execute('DELETE FROM sessions WHERE username=?', (username,))

    def delete_user(self, username):
        with self.connection() as c:
            c.execute('DELETE FROM users WHERE username=?', (username,))

    def login(self, username, password):
        """Persistent global failure cap; single app process, bounded Argon2 concurrency."""
        if not self._lock.acquire(blocking=False):
            return 'busy', None
        try:
            now = int(time.time())
            with self.connection() as c:
                c.execute('BEGIN IMMEDIATE')
                c.execute('DELETE FROM login_failures WHERE at<=?', (now-WINDOW,))
                c.execute('DELETE FROM sessions WHERE expires<=?', (now,))
                if c.execute('SELECT count(*) FROM login_failures').fetchone()[0] >= MAX_FAILURES:
                    return 'limited', None
                user = c.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone() if USERNAME.fullmatch(username) else None
                valid = False
                if len(password.encode()) <= 256:
                    try:
                        valid = HASHER.verify(user['password_hash'] if user else self._dummy, password)
                    except (VerificationError, InvalidHashError):
                        pass
                if not (user and valid):
                    c.execute('INSERT INTO login_failures VALUES(?)', (now,))
                    return 'invalid', None
                token = secrets.token_urlsafe(32)
                c.execute('INSERT INTO sessions VALUES(?,?,?)', (token_hash(token), username, now+TTL))
                return 'ok', token
        finally:
            self._lock.release()

    def identity(self, token):
        if not token or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            return None
        with self.connection() as c:
            row = c.execute('SELECT users.username, users.role FROM sessions JOIN users USING(username) WHERE token_hash=? AND expires>?', (token_hash(token), int(time.time()))).fetchone()
            return dict(row) if row else None

    def logout(self, token):
        if token:
            with self.connection() as c:
                c.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(token),))

    def clear_limits(self):
        with self.connection() as c:
            c.execute('DELETE FROM login_failures')


def auth_path():
    # A separate SQLite file on the existing persistent database mount.
    from config import config
    return Path(config.database_path).resolve().parent / 'hmt_auth.db'


def allowed_origins():
    public = os.getenv('HMT_PUBLIC_ORIGIN', 'https://34.10.110.32').strip().rstrip('/')
    u = urlsplit(public)
    if u.scheme != 'https' or not u.hostname or u.username or u.password or u.path or u.query or u.fragment:
        raise ValueError('HMT_PUBLIC_ORIGIN must be an HTTPS origin without a path')
    return {public, 'http://localhost:8000', 'http://127.0.0.1:8000', 'http://localhost:8080', 'http://127.0.0.1:8080'}


def install_auth(app, templates, store: AuthStore, origins=None):
    origins = set(origins or allowed_origins())
    hosts = {urlsplit(o).netloc for o in origins}

    def login_page(request, error='', status=200):
        return templates.TemplateResponse(request=request, name='login.html', context={'error': error}, status_code=status)

    @app.middleware('http')
    async def protect(request: Request, call_next):
        path = request.url.path
        method = request.method
        host = request.headers.get('host', '')
        if host not in hosts:
            response = JSONResponse({'detail': 'Unrecognized host'}, status_code=400)
        elif method not in SAFE and (request.headers.get('origin') not in origins or urlsplit(request.headers.get('origin','')).netloc != host):
            response = JSONResponse({'detail': 'Same-origin request required'}, status_code=403)
        elif (path == '/health' and method in ('GET','HEAD')) or (path.startswith('/static/') and method in ('GET','HEAD')) or (path == '/login' and method in ('GET','POST')):
            response = await call_next(request)
        else:
            identity = await run_in_threadpool(store.identity, request.cookies.get(COOKIE))
            if not identity:
                if path.startswith('/api/') or method not in SAFE:
                    response = JSONResponse({'detail': 'Authentication required'}, status_code=401)
                else:
                    response = RedirectResponse('/login', status_code=303)
            elif identity['role'] != 'admin' and method not in SAFE and path != '/logout':
                response = JSONResponse({'detail': 'Administrator access required'}, status_code=403)
            else:
                request.state.identity = identity
                response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = "frame-ancestors 'none'; base-uri 'none'; object-src 'none'; form-action 'self'"
        return response

    @app.get('/login', include_in_schema=False)
    async def login_get(request: Request):
        if await run_in_threadpool(store.identity, request.cookies.get(COOKIE)):
            return RedirectResponse('/', status_code=303)
        return login_page(request)

    @app.post('/login', include_in_schema=False)
    async def login_post(request: Request):
        if request.headers.get('content-type','').split(';')[0].strip() != 'application/x-www-form-urlencoded':
            return login_page(request, 'Invalid login request.', 400)
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 4096:
                return login_page(request, 'Login request too large.', 413)
            body.extend(chunk)
        try:
            fields = parse_qs(body.decode('utf-8'), max_num_fields=4)
            username = fields.get('username',[''])[0]
            password = fields.get('password',[''])[0]
        except (ValueError, UnicodeError):
            return login_page(request, 'Invalid login request.', 400)
        state, token = await run_in_threadpool(store.login, username, password)
        if state in ('busy','limited'):
            response = login_page(request, 'Too many attempts. Try again in five minutes.', 429)
            response.headers['Retry-After'] = str(WINDOW)
            return response
        if state != 'ok':
            return login_page(request, 'Invalid username or password.', 401)
        await run_in_threadpool(store.logout, request.cookies.get(COOKIE))
        response = RedirectResponse('/', status_code=303)
        response.set_cookie(COOKIE, token, max_age=TTL, httponly=True, secure=True, samesite='strict', path='/')
        return response

    @app.post('/logout', include_in_schema=False)
    async def logout_post(request: Request):
        await run_in_threadpool(store.logout, request.cookies.get(COOKIE))
        response = RedirectResponse('/login', status_code=303)
        response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='strict')
        return response


def main():
    parser = argparse.ArgumentParser(description='Manage HMT accounts on the VM (passwords never passed on command line)')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('set-user'); p.add_argument('username'); p.add_argument('--role', choices=['admin','viewer'], default='admin')
    p = sub.add_parser('delete-user'); p.add_argument('username')
    sub.add_parser('clear-lockout')
    args = parser.parse_args()
    store = AuthStore(auth_path())
    if args.command == 'set-user':
        password = getpass.getpass('Password (at least 14 characters): ')
        if password != getpass.getpass('Confirm password: '):
            parser.error('Passwords do not match')
        try:
            store.set_user(args.username, password, args.role)
        except ValueError as e:
            parser.error(str(e))
        print('Account saved; its old sessions have been revoked.')
    elif args.command == 'delete-user':
        store.delete_user(args.username)
        print('Account and sessions removed.')
    else:
        store.clear_limits()
        print('Login failure counter cleared.')


if __name__ == '__main__':
    main()
