"""ID/password login that replaces Kakao.

- New members sign up with the semester's shared signup code (officers set and
  rotate it) and wait for officer approval before they can log in.
- Passwords are Argon2id hashes (argon2-cffi). Officers never see or set them;
  they can only issue a one-time 24h setup/reset link.
- Failed logins are throttled per account+IP, per account and per IP.
- Kakao members convert once ('기존 회원 전환'): while logged in with Kakao, or
  through an officer-issued link, they choose an ID/password and keep their row.
- No email or contact details are collected. No passkeys or 2FA by design.
"""
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import abort, flash, g, jsonify, redirect, render_template, request, session, url_for

from member_identity import normalize_member_student_id
from security_utils import forwarded_client_address, safe_internal_next_url
import signup_notify

LOGIN_ID_RE = re.compile(r'^[a-z0-9_]{4,20}$')
MEMBER_MIN_PASSWORD = 8
OFFICER_MIN_PASSWORD = 12
MAX_PASSWORD = 128
SETUP_TOKEN_HOURS = 24
# (failures, window): account+IP pair, the account from any IP, one IP for any account.
PAIR_LIMIT = (5, timedelta(minutes=15))
ACCOUNT_LIMIT = (20, timedelta(hours=1))
IP_LIMIT = (30, timedelta(minutes=15))
SIGNUP_CODE_LIMIT = (10, timedelta(minutes=15))
# Open signup (no code, officer approval only): per-IP caps kept in memory (single app process).
SIGNUP_POST_LIMIT = (20, 15 * 60)     # signup form submissions per IP
SIGNUP_CREATE_LIMIT = (10, 60 * 60)   # pending requests actually created per IP
# A signup_codes row with this marker means "no code needed, officer approval only".
# It is term-bound like a real code, so open signup closes by itself when the term ends.
OPEN_SIGNUP_MARKER = 'OPEN-SIGNUP-NO-CODE'
HONEYPOT_FIELD = 'website'
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
KST = timezone(timedelta(hours=9))

hasher = PasswordHasher()  # Argon2id, RFC 9106 low-memory profile (t=3, m=64MiB, p=4)
_DUMMY_HASH = hasher.hash(secrets.token_urlsafe(18))
GENERIC_LOGIN_ERROR = '아이디 또는 비밀번호가 맞지 않습니다.'
LOCKED_MESSAGE = '로그인 시도가 너무 많아 잠시 막았습니다. 15분 뒤 다시 시도하거나 운영진에게 재설정 링크를 요청해주세요.'


@lru_cache(maxsize=1)
def common_passwords():
    path = Path(__file__).with_name('data') / 'common_passwords.txt'
    return frozenset(line.strip() for line in path.read_text(encoding='utf-8').splitlines() if line.strip())


def now_utc():
    return datetime.now(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat()


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def normalize_login_id(value):
    return str(value or '').strip().lower()


def password_problem(password, *, officer=False, login_id='', student_id='', name=''):
    """Return a Korean message describing why the password is not allowed, or None."""
    password = password or ''
    minimum = OFFICER_MIN_PASSWORD if officer else MEMBER_MIN_PASSWORD
    if len(password) < minimum:
        who = '운영진 계정은 ' if officer else ''
        return f'{who}비밀번호를 {minimum}자 이상으로 정해주세요.'
    if len(password) > MAX_PASSWORD:
        return f'비밀번호는 {MAX_PASSWORD}자 이하로 정해주세요.'
    lowered = password.lower()
    # A common word with a few digits/symbols bolted on ('password123!') is still common.
    core = re.sub(r'^[\d\W_]+|[\d\W_]+$', '', lowered)
    padded_common = len(core) >= 4 and core in common_passwords() and len(lowered) - len(core) <= 5
    if lowered in common_passwords() or padded_common or len(set(password)) <= 2:
        return '너무 흔하거나 쉽게 추측되는 비밀번호입니다. 다른 비밀번호를 정해주세요.'
    for part in (normalize_login_id(login_id), normalize_member_student_id(student_id), (name or '').strip().lower()):
        if part and len(part) >= 3 and part in lowered:
            return '아이디·학번·이름이 들어간 비밀번호는 쓸 수 없습니다.'
    return None


def login_id_problem(login_id):
    if not LOGIN_ID_RE.fullmatch(login_id or ''):
        return '아이디는 영문 소문자·숫자·밑줄(_)로 4~20자입니다.'
    return None


def hash_password(password):
    return hasher.hash(password)


def verify_password(stored_hash, password):
    """Constant-work check; a missing account still spends one Argon2 verification."""
    try:
        return hasher.verify(stored_hash or _DUMMY_HASH, password or '') and bool(stored_hash)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def token_digest(token):
    return hashlib.sha256(str(token or '').encode()).hexdigest()


def generate_signup_code():
    return ''.join(secrets.choice(CODE_ALPHABET) for _ in range(8))


def normalize_code(value):
    return re.sub(r'\s+', '', str(value or '')).upper()


class _IpWindow:
    """Small in-memory sliding-window counter per key."""

    def __init__(self, limit, seconds, clock=None):
        self.limit, self.seconds, self.clock = limit, seconds, clock or time.monotonic
        self.hits = {}
        self.lock = threading.Lock()

    def _trim(self, key, now):
        recent = [t for t in self.hits.get(key, []) if now - t < self.seconds]
        if recent:
            self.hits[key] = recent
        else:
            self.hits.pop(key, None)
        return recent

    def full(self, key):
        with self.lock:
            return len(self._trim(key, self.clock())) >= self.limit

    def add(self, key):
        with self.lock:
            now = self.clock()
            self._trim(key, now)
            self.hits.setdefault(key, []).append(now)
            if len(self.hits) > 5000:  # keep memory bounded under abuse
                for stale in list(self.hits)[:1000]:
                    self.hits.pop(stale, None)


signup_posts = _IpWindow(*SIGNUP_POST_LIMIT)
signup_creates = _IpWindow(*SIGNUP_CREATE_LIMIT)


def is_officer_role(member):
    return (member or {}).get('role') in ('admin', 'officer')


def install_local_auth(app, get_db, login_required, primary_admin_check):
    def db():
        return get_db()

    def secret():
        return str(app.secret_key or '').encode()

    def keyed(kind, value):
        return hmac.new(secret(), f'{kind}|{value}'.encode(), hashlib.sha256).hexdigest()

    def client_ip():
        return forwarded_client_address(
            request.headers.get('X-App-Client-IP') if g.get('trusted_app_proxy') else None, request.remote_addr)

    # --- throttling -----------------------------------------------------------
    def failure_count(kind, column, value, window):
        since = iso(now_utc() - window)
        rows = db().table('auth_failures').select('id').eq('kind', kind).eq(column, value) \
            .gte('created_at', since).limit(200).execute().data or []
        return len(rows)

    def pair_count(login_key, ip_key):
        since = iso(now_utc() - PAIR_LIMIT[1])
        rows = db().table('auth_failures').select('id').eq('kind', 'login').eq('login_key', login_key) \
            .eq('ip_key', ip_key).gte('created_at', since).limit(50).execute().data or []
        return len(rows)

    def login_locked(login_key, ip_key):
        return (pair_count(login_key, ip_key) >= PAIR_LIMIT[0]
                or failure_count('login', 'login_key', login_key, ACCOUNT_LIMIT[1]) >= ACCOUNT_LIMIT[0]
                or failure_count('login', 'ip_key', ip_key, IP_LIMIT[1]) >= IP_LIMIT[0])

    def record_failure(kind, ip_key, login_key=None):
        db().table('auth_failures').insert({
            'kind': kind, 'login_key': login_key, 'ip_key': ip_key, 'created_at': iso(now_utc())}).execute()

    def clear_login_failures(login_key, ip_key=None):
        query = db().table('auth_failures').delete().eq('kind', 'login').eq('login_key', login_key)
        if ip_key:
            query = query.eq('ip_key', ip_key)
        query.execute()

    # --- lookups --------------------------------------------------------------
    def credential_by_login(login_id):
        rows = db().table('member_credentials').select('*').eq('login_id', login_id).limit(1).execute().data or []
        return rows[0] if rows else None

    def credential_for(member_id):
        rows = db().table('member_credentials').select('*').eq('member_id', member_id).limit(1).execute().data or []
        return rows[0] if rows else None

    def member_row(member_id):
        rows = db().table('members').select(
            'id,name,role,is_active,account_status,member_status,profile_pic,social_id,student_id,'
            'auth_provider,auth_session_version'
        ).eq('id', member_id).limit(1).execute().data or []
        return rows[0] if rows else None

    def current_term():
        today = datetime.now(KST).date().isoformat()
        rows = db().table('seminar_terms').select('id,name,start_date,end_date,is_active') \
            .eq('is_active', True).execute().data or []
        within = [r for r in rows if (r.get('start_date') or '') <= today <= (r.get('end_date') or '9999')]
        return (within or rows or [None])[0]

    def term_officer(member_id):
        term = current_term()
        if not term:
            return False
        return bool(db().table('term_officers').select('member_id').eq('term_id', term['id'])
                    .eq('member_id', member_id).limit(1).execute().data)

    def officer_like(member):
        return bool(member) and (is_officer_role(member) or term_officer(member['id']))

    def active_signup_code():
        rows = db().table('signup_codes').select('*').is_('revoked_at', 'null') \
            .order('created_at', desc=True).limit(1).execute().data or []
        code = rows[0] if rows else None
        if not code:
            return None
        if code.get('term_id'):
            terms = db().table('seminar_terms').select('id,name,end_date').eq('id', code['term_id']).limit(1).execute().data or []
            term = terms[0] if terms else None
            today = datetime.now(KST).date().isoformat()
            if term and term.get('end_date') and term['end_date'] < today:
                return None
            code['term_name'] = term.get('name') if term else ''
        code['open'] = code.get('code') == OPEN_SIGNUP_MARKER
        return code

    def can_login(member):
        return bool(member and member.get('account_status') == 'active'
                    and member.get('member_status') not in ('inactive', 'blocked')
                    and not str(member.get('social_id') or '').startswith('system:'))

    def start_local_session(member, remember, next_url=None):
        session.clear()
        session.update(user_id=member['id'], user_role=member.get('role') or 'member',
                       user_name=member.get('name') or '', profile_pic=member.get('profile_pic') or '',
                       remember_login=remember, auth_provider='local',
                       auth_session_version=int(member.get('auth_session_version') or 0))
        session.permanent = remember
        return next_url

    def after_login_redirect(member, next_url):
        if session.get('password_upgrade_required'):
            return redirect(url_for('account_password'))
        if next_url:
            return redirect(next_url)
        if member.get('role') in ('admin', 'officer'):
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('my_page'))

    def login_page(error=None, status=200, **extra):
        return render_template('login.html', login_error=error,
                               next_url=safe_internal_next_url(request.values.get('next')) or '', **extra), status

    app.extensions['local_auth_login_page'] = login_page

    # --- login ----------------------------------------------------------------
    @app.post('/login/password')
    def login_password():
        login_id = normalize_login_id(request.form.get('login_id'))
        password = request.form.get('password') or ''
        remember = request.form.get('remember') == '1'
        next_url = safe_internal_next_url(request.form.get('next'))
        ip_key = keyed('ip', client_ip())
        login_key = keyed('login', login_id)
        if not login_id or not password:
            return login_page('아이디와 비밀번호를 입력해주세요.', 400, login_id=login_id)
        if login_locked(login_key, ip_key):
            return login_page(LOCKED_MESSAGE, 429, login_id=login_id)
        credential = credential_by_login(login_id)
        if not verify_password(credential and credential.get('password_hash'), password):
            record_failure('login', ip_key, login_key)
            return login_page(GENERIC_LOGIN_ERROR, 401, login_id=login_id)
        if credential.get('status') != 'active':
            return login_page('가입 승인 대기 중입니다. 운영진이 승인하면 로그인할 수 있어요.', 403, login_id=login_id)
        member = member_row(credential['member_id'])
        if not can_login(member):
            return login_page('사용할 수 없는 계정입니다. 운영진에게 문의해주세요.', 403, login_id=login_id)
        if hasher.check_needs_rehash(credential['password_hash']):
            db().table('member_credentials').update({'password_hash': hash_password(password)}) \
                .eq('member_id', member['id']).execute()
        if member.get('auth_provider') != 'local':
            db().table('members').update({'auth_provider': 'local'}).eq('id', member['id']).execute()
        clear_login_failures(login_key, ip_key)
        start_local_session(member, remember)
        if officer_like(member) and len(password) < OFFICER_MIN_PASSWORD:
            session['password_upgrade_required'] = True
            flash(f'운영진 계정은 비밀번호를 {OFFICER_MIN_PASSWORD}자 이상으로 바꿔야 운영 화면을 쓸 수 있어요.', 'warning')
        return after_login_redirect(member, next_url)

    # --- signup ---------------------------------------------------------------
    def signup_form(error=None, status=200, **values):
        code = active_signup_code()
        return render_template('signup.html', error=error, values=values,
                               code_ready=bool(code), code_required=bool(code) and not code.get('open'),
                               member_min=MEMBER_MIN_PASSWORD,
                               next_url=safe_internal_next_url(request.values.get('next')) or ''), status

    @app.route('/signup', methods=['GET', 'POST'])
    def signup():
        if session.get('user_id') and request.method == 'GET':
            return redirect(url_for('my_page'))
        if request.method == 'GET':
            return signup_form()
        form = request.form
        values = dict(name=(form.get('name') or '').strip(),
                      student_id=normalize_member_student_id(form.get('student_id')),
                      department=(form.get('department') or '').strip(),
                      login_id=normalize_login_id(form.get('login_id')))
        ip_key = keyed('ip', client_ip())
        if signup_posts.full(ip_key) or signup_creates.full(ip_key):
            return signup_form('가입 신청이 너무 많이 들어왔습니다. 잠시 뒤 다시 시도해주세요.', 429, **values)
        signup_posts.add(ip_key)
        if failure_count('signup_code', 'ip_key', ip_key, SIGNUP_CODE_LIMIT[1]) >= SIGNUP_CODE_LIMIT[0]:
            return signup_form('가입 코드 확인이 너무 많이 실패했습니다. 15분 뒤 다시 시도해주세요.', 429, **values)
        code = active_signup_code()
        if not code:
            return signup_form('지금은 가입을 받고 있지 않습니다. 운영진에게 이번 학기 가입 코드를 문의해주세요.', 403, **values)
        if not code.get('open') and not hmac.compare_digest(normalize_code(form.get('signup_code')).encode(), normalize_code(code['code']).encode()):
            record_failure('signup_code', ip_key)
            return signup_form('가입 코드가 맞지 않습니다. 운영진이 알려준 이번 학기 코드를 확인해주세요.', 400, **values)
        if (form.get(HONEYPOT_FIELD) or '').strip():
            # Bots fill the hidden field: answer like a success but store and notify nothing.
            app.logger.warning('Signup honeypot triggered; request dropped')
            signup_creates.add(ip_key)
            return render_template('signup_done.html', name=values['name'], login_id=values['login_id'], next_url='')
        if not 1 <= len(values['name']) <= 40:
            return signup_form('이름을 입력해주세요.', 400, **values)
        if not re.fullmatch(r'[0-9]{4,20}', values['student_id']):
            return signup_form('학번을 숫자로 정확히 입력해주세요.', 400, **values)
        if not 1 <= len(values['department']) <= 60:
            return signup_form('학과를 입력해주세요.', 400, **values)
        problem = login_id_problem(values['login_id'])
        if problem:
            return signup_form(problem, 400, **values)
        if credential_by_login(values['login_id']):
            return signup_form('이미 사용 중인 아이디입니다.', 400, **values)
        password = form.get('password') or ''
        if password != (form.get('password_confirm') or ''):
            return signup_form('비밀번호 확인이 일치하지 않습니다.', 400, **values)
        same_sid = db().table('members').select('id,name,role,social_id,student_id,account_status') \
            .eq('student_id', values['student_id']).execute().data or []
        roster = [m for m in same_sid if (m.get('name') or '').strip() == values['name']]
        target = roster[0] if len(roster) == 1 else None
        if target:
            if credential_for(target['id']):
                return signup_form('이미 가입 신청했거나 아이디가 있는 회원입니다. 아이디·비밀번호를 잊었다면 운영진에게 재설정 링크를 요청해주세요.', 409, **values)
            if target.get('social_id'):
                return signup_form('카카오로 쓰던 기존 회원입니다. 아래 ‘기존 회원 전환’으로 카카오 로그인 후 아이디를 만들거나, 운영진에게 전환 링크를 요청해주세요.', 409, existing_kakao=True, **values)
            if is_officer_role(target):
                return signup_form('운영진 계정은 관리자에게 전환 링크를 받아 아이디를 만들어주세요.', 409, **values)
        problem = password_problem(password, officer=bool(target and officer_like(target)),
                                   login_id=values['login_id'], student_id=values['student_id'], name=values['name'])
        if problem:
            return signup_form(problem, 400, **values)
        created_member = None
        if not target:
            created = db().table('members').insert({
                'name': values['name'], 'student_id': values['student_id'], 'department': values['department'],
                'role': 'member', 'account_status': 'pending', 'member_status': 'inactive', 'is_active': False,
                'auth_provider': 'local',
            }).execute().data or []
            if not created:
                abort(500)
            created_member = target = created[0]
        try:
            db().table('member_credentials').insert({
                'member_id': target['id'], 'login_id': values['login_id'], 'password_hash': hash_password(password),
                'status': 'pending', 'signup_name': values['name'], 'signup_student_id': values['student_id'],
                'signup_department': values['department'], 'created_at': iso(now_utc()),
                'password_changed_at': iso(now_utc()),
            }).execute()
        except Exception:
            app.logger.warning('Signup credential insert failed (likely duplicate login id)')
            if created_member:
                db().table('members').delete().eq('id', created_member['id']).eq('account_status', 'pending').execute()
            return signup_form('이미 사용 중인 아이디입니다. 다른 아이디를 정해주세요.', 409, **values)
        signup_creates.add(ip_key)
        signup_notify.notify_signup(values['login_id'], values['name'], app.logger)
        return render_template('signup_done.html', name=values['name'], login_id=values['login_id'],
                               next_url=safe_internal_next_url(form.get('next')) or '')

    # --- Kakao member conversion -------------------------------------------------
    def set_credential(member, login_id, password, *, status='active'):
        existing = credential_for(member['id'])
        payload = {'password_hash': hash_password(password), 'status': status,
                   'password_changed_at': iso(now_utc())}
        if status == 'active':
            payload.update(approved_at=iso(now_utc()))
        if existing:
            db().table('member_credentials').update(payload).eq('member_id', member['id']).execute()
            login_id = existing['login_id']
        else:
            payload.update(member_id=member['id'], login_id=login_id, created_at=iso(now_utc()))
            db().table('member_credentials').insert(payload).execute()
        version = int(member.get('auth_session_version') or 0) + 1
        db().table('members').update({'auth_provider': 'local', 'auth_session_version': version}) \
            .eq('id', member['id']).execute()
        clear_login_failures(keyed('login', login_id))
        member['auth_session_version'] = version
        member['auth_provider'] = 'local'
        return login_id

    @app.route('/account/convert', methods=['GET', 'POST'])
    @login_required(role='ANY')
    def account_convert():
        member = member_row(session['user_id'])
        if not member or credential_for(member['id']):
            flash('이미 아이디로 로그인하는 계정입니다.', 'info')
            return redirect(url_for('my_page'))
        officer = officer_like(member)
        error = None
        if request.method == 'POST':
            login_id = normalize_login_id(request.form.get('login_id'))
            password = request.form.get('password') or ''
            error = login_id_problem(login_id)
            if not error and credential_by_login(login_id):
                error = '이미 사용 중인 아이디입니다.'
            if not error and password != (request.form.get('password_confirm') or ''):
                error = '비밀번호 확인이 일치하지 않습니다.'
            error = error or password_problem(password, officer=officer, login_id=login_id,
                                              student_id=member.get('student_id'), name=member.get('name'))
            if not error:
                try:
                    set_credential(member, login_id, password)
                except Exception:
                    app.logger.warning('Conversion credential insert failed')
                    error = '이미 사용 중인 아이디입니다.'
                else:
                    start_local_session(member, session.get('remember_login', True))
                    flash('아이디·비밀번호 로그인으로 전환했습니다. 다음부터 아이디로 로그인해주세요.', 'success')
                    return redirect(url_for('my_page'))
        return render_template('account_credentials.html', mode='convert', member=member, error=error,
                               minimum=OFFICER_MIN_PASSWORD if officer else MEMBER_MIN_PASSWORD,
                               login_id=normalize_login_id(request.form.get('login_id'))), (400 if error else 200)

    # --- officer-issued one-time setup/reset link -----------------------------
    def token_row(token):
        if not token or len(token) > 100:
            return None
        rows = db().table('account_setup_tokens').select('*').eq('token_hash', token_digest(token)).limit(1).execute().data or []
        row = rows[0] if rows else None
        if not row or row.get('used_at'):
            return None
        expires = parse_time(row.get('expires_at'))
        return row if expires and expires > now_utc() else None

    @app.route('/account/setup/<token>', methods=['GET', 'POST'])
    def account_setup(token):
        row = token_row(token)
        if not row:
            response = render_template('account_credentials.html', mode='expired'), 404
            return response
        member = member_row(row['member_id'])
        if not member or member.get('member_status') == 'blocked' or str(member.get('social_id') or '').startswith('system:'):
            return render_template('account_credentials.html', mode='expired'), 404
        credential = credential_for(member['id'])
        officer = officer_like(member)
        error = None
        login_id = credential['login_id'] if credential else normalize_login_id(request.form.get('login_id'))
        if request.method == 'POST':
            password = request.form.get('password') or ''
            if not credential:
                error = login_id_problem(login_id)
                if not error and credential_by_login(login_id):
                    error = '이미 사용 중인 아이디입니다.'
            if not error and password != (request.form.get('password_confirm') or ''):
                error = '비밀번호 확인이 일치하지 않습니다.'
            error = error or password_problem(password, officer=officer, login_id=login_id,
                                              student_id=member.get('student_id'), name=member.get('name'))
            if not error:
                used = db().table('account_setup_tokens').update({'used_at': iso(now_utc())}) \
                    .eq('id', row['id']).is_('used_at', 'null').execute().data or []
                if not used:
                    return render_template('account_credentials.html', mode='expired'), 404
                try:
                    set_credential(member, login_id, password)
                except Exception:
                    app.logger.warning('Setup-link credential write failed')
                    db().table('account_setup_tokens').update({'used_at': None}).eq('id', row['id']).execute()
                    error = '이미 사용 중인 아이디입니다.'
                else:
                    session.clear()
                    flash('비밀번호를 정했습니다. 새 비밀번호로 로그인해주세요.', 'success')
                    return redirect(url_for('login'))
        response = app.make_response((render_template(
            'account_credentials.html', mode='reset' if credential else 'setup', member=member, error=error,
            minimum=OFFICER_MIN_PASSWORD if officer else MEMBER_MIN_PASSWORD, login_id=login_id), 400 if error else 200))
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        return response

    # --- change own password ----------------------------------------------------
    @app.route('/account/password', methods=['GET', 'POST'])
    @login_required(role='ANY')
    def account_password():
        member = member_row(session['user_id'])
        credential = credential_for(member['id']) if member else None
        if not credential:
            return redirect(url_for('account_convert'))
        officer = officer_like(member)
        error = None
        if request.method == 'POST':
            ip_key = keyed('ip', client_ip())
            login_key = keyed('login', credential['login_id'])
            if login_locked(login_key, ip_key):
                error = LOCKED_MESSAGE
            elif not verify_password(credential['password_hash'], request.form.get('current_password')):
                record_failure('login', ip_key, login_key)
                error = '현재 비밀번호가 맞지 않습니다.'
            else:
                password = request.form.get('password') or ''
                if password != (request.form.get('password_confirm') or ''):
                    error = '비밀번호 확인이 일치하지 않습니다.'
                error = error or password_problem(password, officer=officer, login_id=credential['login_id'],
                                                  student_id=member.get('student_id'), name=member.get('name'))
                if not error:
                    set_credential(member, credential['login_id'], password)
                    start_local_session(member, session.get('remember_login', True))
                    flash('비밀번호를 바꿨습니다. 다른 기기에서는 다시 로그인해야 합니다.', 'success')
                    return redirect(url_for('my_page'))
        return render_template('account_credentials.html', mode='change', member=member, error=error,
                               login_id=credential['login_id'],
                               minimum=OFFICER_MIN_PASSWORD if officer else MEMBER_MIN_PASSWORD), (400 if error else 200)

    # --- officer tools (전체 회원 관리) -------------------------------------------
    def actor_id():
        return session.get('user_id')

    @app.post('/api/admin/signup-code')
    @login_required(role='admin')
    def admin_signup_code():
        data = request.get_json(silent=True) or {}
        action = data.get('action')
        current = active_signup_code()
        if action == 'revoke':
            db().table('signup_codes').update({'revoked_at': iso(now_utc())}).is_('revoked_at', 'null').execute()
            return jsonify(status='success', code=None)
        if action == 'open':
            term = current_term()
            db().table('signup_codes').update({'revoked_at': iso(now_utc())}).is_('revoked_at', 'null').execute()
            db().table('signup_codes').insert({'code': OPEN_SIGNUP_MARKER, 'term_id': term['id'] if term else None,
                                               'created_by': actor_id(), 'created_at': iso(now_utc())}).execute()
            app.logger.warning('Signup switched to no-code (approval only) by member %s', actor_id())
            return jsonify(status='success', code=None, open=True, term=(term or {}).get('name') or '')
        if action != 'set':
            return jsonify(status='error', message='알 수 없는 요청입니다.'), 400
        code = normalize_code(data.get('code')) or generate_signup_code()
        if code == OPEN_SIGNUP_MARKER:
            return jsonify(status='error', message='다른 코드를 정해주세요.'), 400
        if not re.fullmatch(r'[A-Z0-9가-힣_-]{6,40}', code):
            return jsonify(status='error', message='가입 코드는 띄어쓰기 없이 6~40자로 정해주세요.'), 400
        if code.lower() in common_passwords():
            return jsonify(status='error', message='너무 쉬운 코드입니다. 다른 코드를 정해주세요.'), 400
        term = current_term()
        db().table('signup_codes').update({'revoked_at': iso(now_utc())}).is_('revoked_at', 'null').execute()
        db().table('signup_codes').insert({'code': code, 'term_id': term['id'] if term else None,
                                           'created_by': actor_id(), 'created_at': iso(now_utc())}).execute()
        app.logger.info('Signup code rotated by member %s (previous=%s)', actor_id(), bool(current))
        return jsonify(status='success', code=code, term=(term or {}).get('name') or '')

    def pending_target(member_id):
        credential = credential_for(member_id)
        if not credential or credential.get('status') != 'pending':
            return None, None
        return credential, member_row(member_id)

    @app.post('/api/admin/members/<int:member_id>/approve-login')
    @login_required(role='admin')
    def admin_approve_signup(member_id):
        credential, member = pending_target(member_id)
        if not credential or not member:
            return jsonify(status='error', message='승인 대기 중인 가입 신청이 아닙니다.'), 404
        if member.get('member_status') == 'blocked' or member.get('account_status') == 'disabled':
            return jsonify(status='error', message='차단된 회원은 승인할 수 없습니다.'), 409
        update = {'account_status': 'active', 'auth_provider': 'local'}
        if member.get('member_status') in (None, 'inactive'):
            update.update(member_status='active', is_active=True)
        db().table('members').update(update).eq('id', member_id).execute()
        db().table('member_credentials').update({'status': 'active', 'approved_at': iso(now_utc()),
                                                 'approved_by': actor_id()}).eq('member_id', member_id).execute()
        return jsonify(status='success')

    @app.post('/api/admin/members/<int:member_id>/reject-login')
    @login_required(role='admin')
    def admin_reject_signup(member_id):
        credential, member = pending_target(member_id)
        if not credential or not member:
            return jsonify(status='error', message='승인 대기 중인 가입 신청이 아닙니다.'), 404
        db().table('member_credentials').delete().eq('member_id', member_id).eq('status', 'pending').execute()
        if member.get('account_status') == 'pending':
            try:
                db().table('members').delete().eq('id', member_id).eq('account_status', 'pending').execute()
            except Exception:
                app.logger.warning('Rejected signup member row kept (referenced elsewhere)')
                db().table('members').update({'account_status': 'disabled'}).eq('id', member_id).execute()
        return jsonify(status='success')

    @app.post('/api/admin/members/<int:member_id>/login-link')
    @login_required(role='admin')
    def admin_issue_login_link(member_id):
        member = member_row(member_id)
        if not member or member.get('member_status') == 'blocked' or str(member.get('social_id') or '').startswith('system:'):
            return jsonify(status='error', message='링크를 만들 수 없는 회원입니다.'), 404
        if is_officer_role(member) and member_id != actor_id() and not primary_admin_check():
            return jsonify(status='error', message='운영진 계정의 링크는 관리자만 만들 수 있습니다.'), 403
        credential = credential_for(member_id)
        if credential and credential.get('status') == 'pending':
            return jsonify(status='error', message='먼저 가입 신청을 승인하거나 거절해주세요.'), 409
        now = now_utc()
        db().table('account_setup_tokens').update({'used_at': iso(now)}).eq('member_id', member_id) \
            .is_('used_at', 'null').execute()
        token = secrets.token_urlsafe(32)
        db().table('account_setup_tokens').insert({
            'member_id': member_id, 'token_hash': token_digest(token), 'created_by': actor_id(),
            'created_at': iso(now), 'expires_at': iso(now + timedelta(hours=SETUP_TOKEN_HOURS))}).execute()
        base = (os.environ.get('PUBLIC_BASE_URL') or request.host_url).rstrip('/')
        expires = (now + timedelta(hours=SETUP_TOKEN_HOURS)).astimezone(KST).strftime('%m월 %d일 %H:%M')
        return jsonify(status='success', url=f'{base}/account/setup/{token}',
                       kind='reset' if credential else 'setup', expires=expires, name=member.get('name'))

    def admin_login_overview():
        """Data for the 전체 회원 관리 page: code, pending signups, login type per member."""
        credentials = db().table('member_credentials').select(
            'member_id,login_id,status,signup_name,signup_student_id,signup_department,created_at'
        ).execute().data or []
        by_member = {c['member_id']: c for c in credentials}
        pending = [c for c in credentials if c.get('status') == 'pending']
        if pending:
            rows = db().table('members').select('id,name,student_id,department,account_status,member_status,recruiting_class') \
                .in_('id', [c['member_id'] for c in pending]).execute().data or []
            members = {m['id']: m for m in rows}
            for c in pending:
                m = members.get(c['member_id']) or {}
                c['existing'] = m.get('account_status') != 'pending'
                c['member'] = m
            pending.sort(key=lambda c: c.get('created_at') or '')
        return {'signup_code': active_signup_code(), 'pending_signups': pending, 'credentials': by_member}

    app.extensions['local_auth_overview'] = admin_login_overview
    app.extensions['local_auth_credential_for'] = credential_for
