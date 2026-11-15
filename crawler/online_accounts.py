"""Account identity, revocable sessions and account-scoped cloud library."""
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

SESSION_SECONDS = 7 * 24 * 3600
PASSWORD_ITERATIONS = 600_000


class Conflict(ValueError):
    pass


class RateLimited(ValueError):
    pass


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), PASSWORD_ITERATIONS)
    return salt + ':' + digest.hex()


def password_matches(password, stored):
    return isinstance(password, str) and len(password) <= 200 and hmac.compare_digest(password_hash(password, stored.split(':')[0]), stored)


def validate_password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 200:
        raise ValueError('密码须为 12–200 个字符')


def validate_library(data):
    def fields(value, names):
        return isinstance(value, dict) and set(value) == set(names.split())
    def text(value, maximum, empty=False):
        return isinstance(value, str) and len(value) <= maximum and (empty or bool(value.strip()))
    def ident(value):
        return isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,96}', value))
    def day(value):
        try:
            return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False
    def require(condition):
        if not condition:
            raise ValueError('收藏、目标或待办结构无效，请刷新后重试')
    require(fields(data, 'version targets bookmarks todos') and type(data['version']) is int and data['version'] == 1)
    for name, limit in [('targets', 50), ('bookmarks', 500), ('todos', 1000)]:
        require(isinstance(data[name], list) and len(data[name]) <= limit)
    ids = set()
    for item in data['targets'] + data['bookmarks'] + data['todos']:
        require(isinstance(item, dict) and ident(item.get('id')) and item['id'] not in ids and day(item.get('created_at')))
        ids.add(item['id'])
    for item in data['targets']:
        require(fields(item, 'id path year schools interest created_at') and item['path'] in ('exam', 'recommend') and type(item['year']) is int and 2000 <= item['year'] <= 2100)
        require(text(item['interest'], 200, True) and isinstance(item['schools'], list) and len(item['schools']) <= 20)
        schools = set()
        for school in item['schools']:
            require(fields(school, 'id name') and ident(school['id']) and text(school['name'], 100) and school['id'] not in schools)
            schools.add(school['id'])
    for item in data['bookmarks']:
        require(fields(item, 'id kind title url created_at') and item['kind'] in ('mentor', 'notice', 'opportunity') and text(item['title'], 300) and text(item['url'], 3000))
        value = item['url']; parsed = urlsplit(value); path = unquote(parsed.path)
        require(not parsed.scheme and not parsed.netloc and not value.startswith('/') and not re.search(r'[\\\x00-\x20]', value))
        require(not re.search(r'[%\\:\x00-\x20]|(^|/)\.{1,2}(/|$)', path))
        require(bool(re.fullmatch(r'(?:start|discovery|notices|opportunities|admissions|compare|desk|applications)\.html|p/[^/\\:.%]+\.html', path)))
    target_ids = {item['id'] for item in data['targets']}
    for item in data['todos']:
        require(fields(item, 'id title done due_date target_id created_at') and text(item['title'], 300) and type(item['done']) is bool)
        require((item['due_date'] == '' or day(item['due_date'])) and (item['target_id'] == '' or item['target_id'] in target_ids))


class Accounts:
    def __init__(self, root):
        self.root = Path(root) / 'var'
        account_dir = self.root / 'accounts'
        account_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = account_dir / 'accounts.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, csrf TEXT NOT NULL, expires INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS attempts (bucket TEXT NOT NULL, at INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS attempts_bucket ON attempts(bucket,at);
                CREATE TABLE IF NOT EXISTS libraries (user_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, body TEXT NOT NULL);
            ''')
        if os.name != 'nt':
            self.path.chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def attempt(self, ip, username, register=False):
        now = int(time.time())
        keys = [(('register:' if register else 'login:') + ip, 20 if register else 30, 3600 if register else 600)]
        if not register:
            keys.append(('login-user:' + ip + ':' + username, 8, 600))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE at < ?', (now - 3600,))
            for key, limit, window in keys:
                key = hashlib.sha256(key.encode()).hexdigest()
                count = db.execute('SELECT COUNT(*) FROM attempts WHERE bucket=? AND at>=?', (key, now - window)).fetchone()[0]
                if count >= limit:
                    raise RateLimited('操作过于频繁，请稍后再试')
            for key, _, _ in keys:
                db.execute('INSERT INTO attempts VALUES (?,?)', (hashlib.sha256(key.encode()).hexdigest(), now))

    def credentials(self, body, ip, register=False):
        if not isinstance(body, dict) or set(body) != {'username', 'password'}:
            raise ValueError('请填写用户名和密码')
        name, password = body['username'], body['password']
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{3,40}', name):
            raise ValueError('用户名须为 3–40 位英文字母、数字、点、下划线或连字符')
        name = name.lower()
        validate_password(password)
        self.attempt(ip, name, register)
        if register:
            user = {'id': secrets.token_hex(16), 'username': name}
            digest = password_hash(password)
            try:
                with self.connect() as db:
                    db.execute('INSERT INTO users VALUES (?,?,?)', (user['id'], name, digest))
            except sqlite3.IntegrityError:
                raise ValueError('该用户名不可用') from None
        else:
            with self.connect() as db:
                row = db.execute('SELECT * FROM users WHERE username=?', (name,)).fetchone()
            # Keep the expensive password operation for unknown names as well.
            stored = row['password'] if row else '0' * 32 + ':' + '0' * 64
            valid = password_matches(password, stored)
            if row is None or not valid:
                raise ValueError('用户名或密码不正确')
            user = {'id': row['id'], 'username': row['username']}
        return self.new_session(user)

    def new_session(self, user):
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE expires < ?', (int(time.time()),))
            db.execute('INSERT INTO sessions VALUES (?,?,?,?)', (hashlib.sha256(token.encode()).hexdigest(), user['id'], csrf, int(time.time()) + SESSION_SECONDS))
        return token, {'authenticated': True, 'user': user, 'csrf_token': csrf}

    def session(self, token):
        if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            return None
        with self.connect() as db:
            row = db.execute('SELECT users.id,username,csrf FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires>?', (hashlib.sha256(token.encode()).hexdigest(), int(time.time()))).fetchone()
        return {'authenticated': True, 'user': {'id': row['id'], 'username': row['username']}, 'csrf_token': row['csrf']} if row else None

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE token_hash=?', (hashlib.sha256(token.encode()).hexdigest(),))

    def change_password(self, session, body):
        if not isinstance(body, dict) or set(body) != {'current_password', 'new_password'}:
            raise ValueError('请填写原密码和新密码')
        validate_password(body['new_password'])
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT password FROM users WHERE id=?', (session['user']['id'],)).fetchone()
            if not row or not password_matches(body['current_password'], row['password']):
                raise ValueError('原密码不正确')
            db.execute('UPDATE users SET password=? WHERE id=?', (password_hash(body['new_password']), session['user']['id']))
            db.execute('DELETE FROM sessions WHERE user_id=?', (session['user']['id'],))
        return self.new_session(session['user'])

    def user_root(self, user_id):
        if not re.fullmatch(r'[a-f0-9]{32}', user_id):
            raise ValueError('无效账号')
        path = self.root / 'users' / user_id
        if any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)() for p in (self.root, self.root / 'users', path)):
            raise ValueError('账号存储不可用')
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    def library(self, user_id, body=None):
        if body is not None:
            if not isinstance(body, dict) or set(body) != {'revision', 'library'} or type(body['revision']) is not int or body['revision'] < 0:
                raise ValueError('收藏版本无效')
            validate_library(body['library'])
            encoded = json.dumps(body['library'], ensure_ascii=False)
            if len(encoded.encode()) > 1_000_000:
                raise ValueError('收藏、目标与待办合计不得超过 1 MB')
        with self.connect() as db:
            if body is not None:
                db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision,body FROM libraries WHERE user_id=?', (user_id,)).fetchone()
            revision = row['revision'] if row else 0
            if body is None:
                return {'revision': revision, 'library': json.loads(row['body']) if row else None}
            if body['revision'] != revision:
                raise Conflict('其他设备已更新记录，请刷新后再保存；本次未覆盖云端记录')
            revision += 1
            db.execute('INSERT INTO libraries VALUES (?,?,?) ON CONFLICT(user_id) DO UPDATE SET revision=excluded.revision,body=excluded.body', (user_id, revision, encoded))
        return {'revision': revision, 'library': body['library']}
