"""Adapter for the pinned local openNamu v4.4.0-beta.3 engine.

Only identity provisioning touches its existing SQLite account tables. Content,
history, rendering, edit ACLs and atomic revision checks stay in openNamu.
Native cookies/passwords never leave this process. Never expose the native port.
"""
from contextlib import contextmanager
from datetime import datetime
from hashlib import sha256, sha3_256
import hmac
from pathlib import Path
import sqlite3
from urllib.parse import quote, urlsplit, unquote

import requests


class EngineUnavailable(Exception):
    pass


class EditRejected(Exception):
    pass


class EditConflict(EditRejected):
    pass


class OpenNamu:
    GROUP = 'club_bridge_writer'
    # This engine requires document as the parent of edit/new_make. It also
    # implies move/delete internally; the HTTP adapter exposes neither route.
    PERMISSIONS = {'document', 'view', 'edit', 'new_make', 'history_view', 'site_view',
                   'login_available', 'captcha_pass', 'edit_day', 'edit_night',
                   'edit_limit_100'}

    def __init__(self, base_url, database, secret):
        address = urlsplit(base_url)
        if (address.scheme != 'http' or address.hostname != '127.0.0.1'
                or not address.port or address.path not in ('', '/')
                or address.username or address.password or address.query or address.fragment):
            raise ValueError('openNamu must use a private loopback HTTP address')
        if len(secret) < 32:
            raise ValueError('WIKI_IDENTITY_SECRET must contain at least 32 characters')
        self.base_url = base_url.rstrip('/')
        self.database = Path(database).resolve()
        if not self.database.is_file():
            raise ValueError('An initialized openNamu database is required')
        self.secret = secret.encode()

    def credentials(self, member_id):
        digest = hmac.new(self.secret, ('identity:' + str(member_id)).encode(), sha256).hexdigest()
        username = 'member-' + digest[:20]
        password = hmac.new(self.secret, ('password:' + str(member_id)).encode(), sha256).hexdigest()
        return username, password

    def provision(self, member_id):
        username, password = self.credentials(member_id)
        # mode=rw cannot silently create a new or accidentally empty wiki.
        with sqlite3.connect(self.database.as_uri() + '?mode=rw', uri=True, timeout=5) as db:
            db.execute('begin immediate')
            grants = {r[0] for r in db.execute('select acl from alist where name=?', (self.GROUP,))}
            if grants and grants != self.PERMISSIONS:
                raise EngineUnavailable('Unexpected bridge permissions')
            if not grants:
                db.executemany('insert into alist(name,acl) values(?,?)',
                               [(self.GROUP, p) for p in sorted(self.PERMISSIONS)])
            existing = dict(db.execute('select name,data from user_set where id=?', (username,)))
            expected = {'pw': sha3_256(password.encode()).hexdigest(), 'acl': self.GROUP, 'encode': 'sha3'}
            if existing:
                if any(existing.get(k) != v for k, v in expected.items()):
                    raise EngineUnavailable('Unexpected bridge account')
            else:
                expected['date'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                db.executemany('insert into user_set(name,id,data) values(?,?,?)',
                               [(k, username, v) for k, v in expected.items()])
        return username, password

    def request(self, client, method, path, **kwargs):
        try:
            result = client.request(method, self.base_url + path, timeout=(3, 20),
                                    allow_redirects=False, **kwargs)
            result.raise_for_status()
            return result
        except requests.RequestException as exc:
            raise EngineUnavailable('openNamu did not complete the request') from exc

    def json(self, client, path, **kwargs):
        try:
            result = self.request(client, 'POST' if 'data' in kwargs else 'GET', path, **kwargs).json()
        except ValueError as exc:
            raise EngineUnavailable('Invalid openNamu response') from exc
        if not isinstance(result, dict) or result.get('response') not in ('ok', 'not exist'):
            raise EngineUnavailable('openNamu refused the request')
        return result

    @contextmanager
    def user(self, member_id):
        try:
            username, password = self.provision(member_id)
        except sqlite3.Error as exc:
            raise EngineUnavailable('Wiki account store unavailable') from exc
        with requests.Session() as client:
            client.trust_env = False
            self.request(client, 'POST', '/login', data={'id': username, 'password': password})
            auth = self.json(client, '/api/v2/auth')
            if auth.get('name') != self.GROUP or not auth.get('info', {}).get('edit'):
                raise EngineUnavailable('Wiki identity could not be verified')
            try:
                yield client
            finally:
                # The engine uses an in-memory session store; expire each bridge
                # session instead of growing it with every page view.
                try:
                    self.request(client, 'GET', '/logout')
                except EngineUnavailable:
                    pass

    def history(self, client, title, page=1):
        return self.json(client, f'/api/v2/history/{page}/normal/' + quote(title, safe=''))['data']

    def document(self, client, title, revision=None):
        # Read version first. An intervening edit can only cause a safe conflict,
        # never attach a newer version to older text and overwrite another edit.
        history = self.history(client, title)
        latest = history[0][0] if history and history[0][0] else '0'
        path = f'/api/v2/raw_rev/{revision}/' if revision else '/api/v2/raw/'
        raw = self.json(client, path + quote(title, safe=''))
        return {'title': title, 'source': raw.get('data', ''), 'exists': raw['response'] == 'ok',
                'version': revision or latest, 'history': history}

    def render(self, client, title, source):
        return self.json(client, '/api/render', data={'name': title, 'data': source})['data']

    def titles(self, client, query='', page=1):
        path = f'/api/search_page/{page}/' + quote(query, safe='') if query else f'/api/v2/list/document/{page}'
        return self.json(client, path)['data']

    def save(self, client, title, content, summary, version):
        result = self.request(client, 'POST', '/edit/' + quote(title, safe=''), data={
            'content': content, 'send': summary, 'ver': version, 'copyright_agreement': 'yes',
        })
        target = urlsplit(result.headers.get('Location', ''))
        if result.status_code in (302, 303) and not target.netloc and unquote(target.path) == '/w/' + title:
            return
        history = self.history(client, title)
        latest = history[0][0] if history and history[0][0] else '0'
        if latest != version:
            raise EditConflict('다른 회원이 먼저 수정했습니다. 작성한 내용은 아래에 유지했습니다. 최신 문서와 비교한 뒤 다시 편집해 주세요.')
        raise EditRejected('위키가 저장을 거절했습니다. 문서 권한·편집 제한을 확인해 주세요. 작성한 내용은 아래에 유지했습니다.')
