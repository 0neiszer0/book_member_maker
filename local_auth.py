"""Local password, school email, and regular-member PIN authentication."""
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import abort, flash, g, jsonify, redirect, render_template, request, session, url_for

from member_identity import normalize_member_student_id
from minipc_security import SENSITIVE_AUTH_PAGES, has_term_assignment
from privacy_cleanup import init_privacy_cleanup_routes
from recruitment_dues_routes import init_recruitment_dues_routes
from security_utils import forwarded_client_address, safe_internal_next_url, trusted_client_address
import email_auth_mailer
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
OPEN_SIGNUP_MARKER = 'OPEN-SIGNUP-NO-CODE'
OT_SIGNUP_MARKER = 'OT-AUTO-APPROVAL'
KNU_EMAIL_RE = re.compile(r'^[a-z0-9._%+-]+@knu\.ac\.kr$')
SIX_DIGITS = re.compile(r'^[0-9]{6}$')
EMAIL_PURPOSES = {'login': '로그인', 'signup': '회원가입', 'pin_reset': 'PIN 재설정'}
EMAIL_ERROR = '경북대 학교 메일(@knu.ac.kr)만 사용할 수 있습니다.'
SIGNUP_CLOSED = '현재 신규 가입 기간이 아닙니다. 운영진에게 문의해주세요.'
PIN_STAFF = '운영진은 학교 메일 6자리 인증코드 또는 12자 이상 비밀번호로 로그인해주세요.'
PIN_LOCKED = 'PIN을 5번 틀려 15분간 로그인할 수 없습니다. 학교 메일로 PIN을 재설정할 수 있습니다.'
PIN_PROOF_EXPIRED = '학교 메일 인증 시간이 지났습니다. 인증코드를 다시 받아주세요.'
PIN_LOCK_DURATION = timedelta(minutes=15)
EMAIL_PROOF_DURATION = timedelta(minutes=10)
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
    init_recruitment_dues_routes(app, get_db, login_required)
    init_privacy_cleanup_routes(app, get_db, login_required, primary_admin_check)

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

    def email_auth_member(field, value):
        rows = db().table('members').select(
            'id,name,student_id,role,is_active,account_status,member_status,social_id,profile_pic,'
            'knu_email,knu_email_verified_at,pin_hash,pin_failed_attempts,pin_locked_until,auth_provider,auth_session_version'
        ).eq(field, value).limit(2).execute().data or []
        return rows[0] if len(rows) == 1 else None

    def signup_terms():
        today = now_utc().astimezone(KST).date().isoformat()
        rows = db().table('seminar_terms').select('id,name,start_date,end_date,is_active') \
            .eq('is_active', True).order('start_date', desc=True).execute().data or []
        within = [r for r in rows if (r.get('start_date') or '') <= today <= (r.get('end_date') or '9999')]
        upcoming = sorted((r for r in rows if (r.get('start_date') or '') > today), key=lambda r: r['start_date'])
        return within, upcoming, rows

    def current_term():
        within, upcoming, rows = signup_terms()
        return (within or upcoming or rows or [None])[0]

    def signup_deadline():
        within, upcoming, _ = signup_terms()
        term = (within or upcoming or [None])[0]
        if term and term.get('end_date'):
            end = datetime.fromisoformat(term['end_date']).replace(tzinfo=KST) + timedelta(days=1)
            return term['id'], term['name'], iso(end)
        return None, '', iso(now_utc() + timedelta(days=30))

    def term_officer(member_id):
        term = current_term()
        if not term:
            return False
        return bool(db().table('term_officers').select('member_id').eq('term_id', term['id'])
                    .eq('member_id', member_id).limit(1).execute().data)

    def officer_like(member):
        return bool(member) and (is_officer_role(member) or term_officer(member['id']))

    def signup_setting():
        rows = db().table('signup_codes').select('*').is_('revoked_at', 'null') \
            .order('created_at', desc=True).limit(1).execute().data or []
        return rows[0] if rows else None

    def ot_deadline(setting):
        expiry = parse_time((setting or {}).get('auto_approve_until'))
        return expiry if expiry and expiry > now_utc() else None

    def active_signup_code(setting=None):
        code = dict(setting if setting is not None else signup_setting() or {})
        if not code or code.get('code') == OT_SIGNUP_MARKER:
            return None
        expires = parse_time(code.get('expires_at'))
        if expires and expires <= now_utc():
            return None
        if code.get('term_id'):
            terms = db().table('seminar_terms').select('id,name,end_date').eq('id', code['term_id']).limit(1).execute().data or []
            term = terms[0] if terms else None
            today = now_utc().astimezone(KST).date().isoformat()
            if term and term.get('end_date') and term['end_date'] < today:
                return None
            code['term_name'] = term.get('name') if term else ''
        code['open'] = code.get('code') == OPEN_SIGNUP_MARKER
        return code

    def can_login(member):
        return bool(member and member.get('account_status') == 'active'
                    and member.get('member_status') not in ('inactive', 'blocked')
                    and not str(member.get('social_id') or '').startswith('system:'))

    def start_local_session(member, remember, *, method=None):
        session.clear()
        session.update(user_id=member['id'], user_role=member.get('role') or 'member',
                       user_name=member.get('name') or '', profile_pic=member.get('profile_pic') or '',
                       remember_login=remember, auth_provider='local',
                       auth_session_version=int(member.get('auth_session_version') or 0))
        session.permanent = remember
        if method:
            session['login_method'] = method

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

    @app.after_request
    def protect_auth_responses(response):
        if request.endpoint in SENSITIVE_AUTH_PAGES:
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Referrer-Policy'] = 'same-origin'
        return response

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

    def email_account_active(member):
        return (can_login(member) and member.get('is_active') is True
                and member.get('member_status') != 'pending')

    def verified_email_account(member):
        return (email_account_active(member) and member.get('knu_email_verified_at')
                and member.get('auth_provider') == 'local')

    def email_page(email='', purpose='login', *, sent=False, error=None, status=200):
        return login_page(auth_section='email', email=email, email_purpose=purpose,
                          email_sent=sent, email_error=error, status=status)

    def email_code_digest(code_id, email, purpose, code):
        return keyed('email-otp', f'{code_id}|{email}|{purpose}|{code}')

    @app.post('/auth/email/request')
    def email_auth_request():
        email = (request.form.get('email') or '').strip().lower()
        purpose = request.form.get('purpose') or 'login'
        if purpose not in EMAIL_PURPOSES:
            abort(400)
        if len(email) > 254 or not KNU_EMAIL_RE.fullmatch(email):
            return email_page(email, purpose, error=EMAIL_ERROR, status=400)
        code_id = str(uuid4())
        code = f'{secrets.randbelow(1_000_000):06d}'
        trusted_proxy = bool(g.get('trusted_app_proxy'))
        ip = trusted_client_address(request.headers if trusted_proxy else {}, request.remote_addr, trusted_proxy)
        allowed = db().rpc('reserve_email_auth_code', {
            'p_id': code_id, 'p_email': email, 'p_purpose': purpose,
            'p_code_hash': email_code_digest(code_id, email, purpose, code), 'p_client_ip': keyed('ip', ip),
        }).execute().data
        if not allowed:
            challenge = session.get('email_challenge') or {}
            sent = challenge.get('email') == email and challenge.get('purpose') == purpose
            return email_page(email, purpose, sent=sent, error='요청이 너무 잦습니다. 잠시 뒤 다시 시도해주세요.', status=429)
        try:
            sender = app.extensions.get('email_auth_sender', email_auth_mailer.send_verification_code)
            sender(email, code, EMAIL_PURPOSES[purpose])
        except email_auth_mailer.MailDeliveryError:
            app.logger.warning('School email verification delivery failed')
            return email_page(email, purpose, error='메일을 보내지 못했습니다. 잠시 뒤 다시 시도해주세요.', status=503)
        session.pop('email_grant', None)
        session['email_challenge'] = {'id': code_id, 'email': email, 'purpose': purpose}
        return email_page(email, purpose, sent=True)

    @app.post('/auth/email/verify')
    def email_auth_verify():
        challenge = session.get('email_challenge') or {}
        email, purpose = challenge.get('email', ''), challenge.get('purpose', 'login')
        code = (request.form.get('code') or '').strip()
        if not challenge:
            return email_page(email, purpose, error=PIN_PROOF_EXPIRED, status=400)
        if not SIX_DIGITS.fullmatch(code):
            return email_page(email, purpose, sent=True, error='인증코드 숫자 6자리를 입력해주세요.', status=400)
        codes = db().table('email_auth_codes')
        rows = codes.select('*').eq('id', challenge['id']).limit(1).execute().data or []
        row = rows[0] if rows else None
        now = now_utc()
        if not row or row.get('consumed_at') or parse_time(row['expires_at']) <= now:
            return email_page(email, purpose, error=PIN_PROOF_EXPIRED, status=400)
        attempts = row['attempts']
        if attempts >= 5:
            return email_page(email, purpose, error='인증코드를 5번 틀렸습니다. 인증코드를 다시 받아주세요.', status=429)
        matches = hmac.compare_digest(row['code_hash'], email_code_digest(challenge['id'], email, purpose, code))
        update = {'consumed_at': iso(now)} if matches else {'attempts': attempts + 1}
        changed = db().table('email_auth_codes').update(update).eq('id', row['id']) \
            .eq('attempts', attempts).is_('consumed_at', 'null').gte('expires_at', iso(now)).execute().data
        if not changed:
            return email_page(email, purpose, sent=True, error='인증 요청이 변경되었습니다. 다시 시도해주세요.', status=409)
        if not matches:
            if attempts == 4:
                return email_page(email, purpose, error='인증코드를 5번 틀렸습니다. 인증코드를 다시 받아주세요.', status=429)
            return email_page(email, purpose, sent=True, error='인증코드가 맞지 않습니다.', status=401)
        session.pop('email_challenge', None)
        next_url = safe_internal_next_url(request.form.get('next'))
        grant = {'email': email, 'code_id': row['id'], 'until': iso(now + EMAIL_PROOF_DURATION), 'next': next_url}
        member = email_auth_member('knu_email', email)
        if member:
            if member.get('account_status') == 'pending':
                return email_page(email, purpose, error='가입 승인 대기 중입니다. 운영진이 승인하면 로그인할 수 있어요.', status=403)
            if not email_account_active(member):
                return email_page(email, purpose, error='사용할 수 없는 계정입니다. 운영진에게 문의해주세요.', status=403)
            regular = member.get('role') == 'member' and not has_term_assignment(db(), member['id'])
            if purpose == 'pin_reset' and not regular:
                return email_page(email, purpose, error=PIN_STAFF, status=403)
            if not verified_email_account(member):
                changed = db().table('members').update({
                    'knu_email_verified_at': member.get('knu_email_verified_at') or iso(now), 'auth_provider': 'local',
                }).eq('id', member['id']).eq('knu_email', email).eq('account_status', 'active') \
                    .eq('is_active', True).eq('auth_session_version', member['auth_session_version']).execute().data or []
                if not changed or not verified_email_account(changed[0]):
                    return email_page(email, purpose, error='사용할 수 없는 계정입니다. 운영진에게 문의해주세요.', status=403)
                member = changed[0]
            grant.update(member_id=member['id'], version=member['auth_session_version'] or 0)
            if purpose == 'pin_reset':
                grant['kind'] = 'reset'
                session['email_grant'] = grant
                return redirect(url_for('pin_reset_confirm'), code=303)
            start_local_session(member, True)
            if regular and not member.get('pin_hash'):
                grant['kind'] = 'setup'
                session['email_grant'] = grant
                return redirect(url_for('pin_setup'), code=303)
            return after_login_redirect(member, next_url)
        if purpose == 'pin_reset':
            return email_page(email, purpose, error='이 메일로 연결된 회원 계정을 찾을 수 없습니다.', status=400)
        grant['kind'] = 'enroll'
        session['email_grant'] = grant
        return redirect(url_for('email_auth_enroll'), code=303)

    def valid_email_grant(kind):
        grant = session.get('email_grant') or {}
        until = parse_time(grant.get('until'))
        return grant if grant.get('kind') == kind and until and until > now_utc() else None

    @app.route('/auth/email/enroll', methods=['GET', 'POST'])
    def email_auth_enroll():
        grant = valid_email_grant('enroll')
        if not grant:
            return email_page(error=PIN_PROOF_EXPIRED, status=400)
        values = {}

        def show(error=None, status=200, pending=False):
            setting = signup_setting()
            code = active_signup_code(setting)
            ot = ot_deadline(setting)
            return render_template('signup.html', verified_email=grant['email'], values=values,
                                   code_required=bool(code and not code['open'] and not ot),
                                   enrollment_pending=pending, error=error, next_url=grant['next'] or ''), status

        if request.method == 'GET':
            return show()
        values = dict(name=(request.form.get('name') or '').strip(),
                      student_id=normalize_member_student_id(request.form.get('student_id')),
                      department=(request.form.get('department') or '').strip())
        pin = request.form.get('pin') or ''
        if not 1 <= len(values['name']) <= 40 or not re.fullmatch(r'[0-9]{4,20}', values['student_id']):
            return show('이름과 학번을 정확히 입력해주세요.', 400)
        if len(values['department']) > 60:
            return show('학과는 60자 이하로 입력해주세요.', 400)
        if pin and not SIX_DIGITS.fullmatch(pin):
            return show('PIN은 숫자 6자리로 정해주세요.', 400)
        try:
            result = db().rpc('complete_email_signup', {
                'p_code_id': grant['code_id'], 'p_email': grant['email'], 'p_name': values['name'],
                'p_student_id': values['student_id'], 'p_department': values['department'],
                'p_pin_hash': hash_password(pin) if pin else None,
                'p_signup_code': normalize_code(request.form.get('signup_code')),
            }).execute().data['result']
        except Exception:
            app.logger.warning('School email enrollment could not be completed')
            return show('가입을 처리하지 못했습니다. 잠시 뒤 다시 시도해주세요.', 503)
        if result == 'active':
            member = email_auth_member('knu_email', grant['email'])
            if verified_email_account(member):
                start_local_session(member, True)
                if not member.get('pin_hash') and not has_term_assignment(db(), member['id']):
                    grant.update(kind='setup', member_id=member['id'], version=member['auth_session_version'] or 0)
                    session['email_grant'] = grant
                    return redirect(url_for('pin_setup'), code=303)
                return after_login_redirect(member, grant['next'])
        elif result == 'pending':
            session.pop('email_grant', None)
            signup_notify.notify_signup('학교 메일 가입', values['name'], app.logger)
            return show(pending=True)
        messages = {
            'closed': (SIGNUP_CLOSED, 403),
            'department': ('신규 가입에는 학과를 입력해주세요.', 400),
            'code': ('가입 코드가 맞지 않습니다. 운영진에게 확인해주세요.', 400),
            'conflict': ('회원 정보가 기존 계정과 일치하지 않거나 이미 연결되어 있습니다. 운영진에게 문의해주세요.', 409),
            'expired': (PIN_PROOF_EXPIRED, 400),
        }
        return show(*messages.get(result, ('가입을 완료하지 못했습니다. 다시 로그인해주세요.', 409)))

    @app.post('/login/pin')
    def login_pin():
        identifier = (request.form.get('identifier') or request.form.get('email') or request.form.get('student_id') or '').strip()
        pin = request.form.get('pin') or ''

        def show(message, status):
            return login_page(auth_section='pin', pin_error=message, pin_identifier=identifier, status=status)

        if not SIX_DIGITS.fullmatch(pin):
            return show('PIN 숫자 6자리를 입력해주세요.', 400)
        if '@' in identifier:
            email = identifier.lower()
            if len(email) > 254 or not KNU_EMAIL_RE.fullmatch(email):
                return show(EMAIL_ERROR, 400)
            member = email_auth_member('knu_email', email)
        else:
            student_id = normalize_member_student_id(identifier)
            if not re.fullmatch(r'[0-9]{4,20}', student_id):
                return show('학교 메일 또는 학번을 입력해주세요.', 400)
            member = email_auth_member('student_id', student_id)

        generic_error = '학교 메일·학번 또는 PIN이 맞지 않습니다.'
        if can_login(member) and (is_officer_role(member) or has_term_assignment(db(), member['id'])):
            return show(PIN_STAFF, 403)
        if not verified_email_account(member):
            verify_password(None, pin)
            return show(generic_error, 401)
        if member.get('role') != 'member':
            return show(PIN_STAFF, 403)
        now = now_utc()
        locked_until = parse_time(member.get('pin_locked_until'))
        if locked_until and locked_until > now:
            return show(PIN_LOCKED, 429)
        if not member.get('pin_hash'):
            return show('학교 메일로 로그인한 뒤 PIN을 만들어주세요.', 401)
        verified = verify_password(member['pin_hash'], pin)
        attempts = member['pin_failed_attempts']
        # Compare and swap to count concurrent failures and reject a racing PIN reset.
        for _ in range(6):
            failed = 0 if verified else (0 if locked_until else attempts) + 1
            lock = iso(now + PIN_LOCK_DURATION) if failed >= 5 else None
            query = db().table('members').update({'pin_failed_attempts': failed, 'pin_locked_until': lock}) \
                .eq('id', member['id']).eq('pin_hash', member['pin_hash']).eq('pin_failed_attempts', attempts) \
                .eq('auth_session_version', member['auth_session_version']).eq('role', 'member')
            query = query.eq('pin_locked_until', member['pin_locked_until']) if locked_until else query.is_('pin_locked_until', 'null')
            changed = query.execute().data or []
            if changed:
                if not verified:
                    return show(PIN_LOCKED, 429) if lock else show(generic_error, 401)
                if not verified_email_account(changed[0]) or has_term_assignment(db(), member['id']):
                    return show(generic_error, 401)
                start_local_session(changed[0], True, method='pin')
                return after_login_redirect(changed[0], safe_internal_next_url(request.form.get('next')))
            latest = email_auth_member('knu_email', member['knu_email'])
            if not latest or latest['id'] != member['id'] or latest['pin_hash'] != member['pin_hash'] \
                    or latest['auth_session_version'] != member['auth_session_version'] or latest.get('role') != 'member':
                return show(generic_error, 401)
            attempts = latest['pin_failed_attempts']
            locked_until = parse_time(latest.get('pin_locked_until'))
            if locked_until and locked_until > now:
                return show(PIN_LOCKED, 429)
        return show('PIN 로그인 요청이 너무 잦습니다. 잠시 뒤 다시 시도해주세요.', 429)

    def handle_pin_change(kind):
        grant = valid_email_grant(kind)
        if not grant or (kind == 'setup' and session.get('user_id') != grant.get('member_id')):
            return email_page(purpose='pin_reset' if kind == 'reset' else 'login', error=PIN_PROOF_EXPIRED, status=400)
        member = email_auth_member('knu_email', grant['email'])
        if not verified_email_account(member) or member['id'] != grant['member_id'] \
                or member['auth_session_version'] != grant['version'] or (kind == 'setup' and member.get('pin_hash')):
            return email_page(error=PIN_PROOF_EXPIRED, status=400)
        if member.get('role') != 'member' or has_term_assignment(db(), member['id']):
            return email_page(error=PIN_STAFF, status=403)
        error = None
        if request.method == 'POST':
            pin = request.form.get('pin') or ''
            if not SIX_DIGITS.fullmatch(pin):
                error = 'PIN은 숫자 6자리로 정해주세요.'
            elif pin != request.form.get('pin_confirm'):
                error = 'PIN 확인이 일치하지 않습니다.'
            else:
                update = {'pin_hash': hash_password(pin), 'pin_failed_attempts': 0, 'pin_locked_until': None,
                          'auth_session_version': grant['version'] + 1}
                query = db().table('members').update(update).eq('id', member['id']).eq('knu_email', grant['email']) \
                    .eq('auth_session_version', grant['version']).eq('role', 'member').eq('is_active', True) \
                    .eq('account_status', 'active').eq('auth_provider', 'local')
                member_status = member.get('member_status')
                query = query.eq('member_status', member_status) if member_status else query.is_('member_status', 'null')
                if kind == 'setup':
                    query = query.is_('pin_hash', 'null')
                changed = query.execute().data or []
                if changed and verified_email_account(changed[0]):
                    start_local_session(changed[0], True)
                    return after_login_redirect(changed[0], grant['next'])
                return email_page(error=PIN_PROOF_EXPIRED, status=409)
        return render_template('account_password.html', kind=kind, error=error,
                               skip_url=grant['next'] or url_for('my_page')), 400 if error else 200

    @app.route('/account/pin/setup', methods=['GET', 'POST'])
    def pin_setup():
        return handle_pin_change('setup')

    @app.route('/account/pin/reset', methods=['GET', 'POST'])
    def pin_reset_confirm():
        return handle_pin_change('reset')

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
            if valid_email_grant('enroll'):
                return redirect(url_for('email_auth_enroll'), code=303)
            next_url = safe_internal_next_url(request.args.get('next'))
            return redirect(url_for('login', mode='email', next=next_url), code=303)
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
        same_sid = db().table('members').select('id,name,role,social_id,student_id,account_status,member_status,is_active,knu_email') \
            .eq('student_id', values['student_id']).execute().data or []
        roster = [m for m in same_sid if (m.get('name') or '').strip() == values['name']]
        target = roster[0] if len(roster) == 1 else None
        if same_sid and (len(same_sid) != 1 or not target):
            return signup_form('학번이 기존 명부와 일치합니다. 이름을 확인하거나 운영진에게 문의해주세요.', 409, **values)
        if target:
            if (target.get('member_status') in ('inactive', 'blocked')
                    or target.get('is_active') is False or target.get('account_status') == 'disabled'):
                return signup_form('비활성화된 회원은 운영진에게 문의해주세요.', 409, **values)
            if target.get('knu_email') or credential_for(target['id']):
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
            try:
                created = db().table('members').insert({
                    'name': values['name'], 'student_id': values['student_id'], 'department': values['department'],
                    'role': 'member', 'account_status': 'pending', 'member_status': 'inactive', 'is_active': False,
                    'auth_provider': 'local',
                }).execute().data or []
            except Exception as exc:
                if getattr(exc, 'code', None) != '23505':
                    raise
                return signup_form('학번이 기존 명부와 일치합니다. 운영진에게 문의해주세요.', 409, **values)
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
            app.logger.warning('Signup credential insert failed')
            if created_member:
                db().table('members').delete().eq('id', created_member['id']).eq('account_status', 'pending').execute()
            return signup_form('이미 사용 중인 아이디이거나 로그인 계정이 연결된 회원입니다.', 409, **values)
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
        if session.get('login_method') == 'pin':
            flash('아이디를 만들려면 학교 메일 인증코드로 다시 로그인해주세요.', 'warning')
            return redirect(url_for('my_page'))
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
        response.headers['Referrer-Policy'] = 'same-origin'
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

    def configure_signup(action, *, code=None, term_id=None, expires=None, hours=None):
        return db().rpc('update_signup_configuration', {
            'p_action': action, 'p_actor': actor_id(), 'p_code': code,
            'p_term': term_id, 'p_expires': expires, 'p_hours': hours,
        }).execute().data

    @app.post('/api/admin/signup-code')
    @login_required(role='admin')
    def admin_signup_code():
        data = request.get_json(silent=True) or {}
        action = data.get('action')
        if action == 'revoke':
            configure_signup(action)
            return jsonify(status='success', code=None)
        if action == 'ot_open':
            hours = data.get('hours')
            if type(hours) is not int or hours not in (1, 3, 6):
                return jsonify(status='error', message='자동승인 시간을 1시간, 3시간, 6시간 중에서 골라주세요.'), 400
            expires = configure_signup(action, hours=hours)
            return jsonify(status='success', auto_approve_until=expires)
        if action == 'ot_close':
            configure_signup(action)
            return jsonify(status='success', auto_approve_until=None)
        if action not in ('set', 'open'):
            return jsonify(status='error', message='알 수 없는 요청입니다.'), 400
        opened = action == 'open'
        code = OPEN_SIGNUP_MARKER if opened else normalize_code(data.get('code')) or generate_signup_code()
        if not opened:
            if code in (OPEN_SIGNUP_MARKER, OT_SIGNUP_MARKER):
                return jsonify(status='error', message='다른 코드를 정해주세요.'), 400
            if not re.fullmatch(r'[A-Z0-9가-힣_-]{6,40}', code):
                return jsonify(status='error', message='가입 코드는 띄어쓰기 없이 6~40자로 정해주세요.'), 400
            if code.lower() in common_passwords():
                return jsonify(status='error', message='너무 쉬운 코드입니다. 다른 코드를 정해주세요.'), 400
        term_id, term_name, expires = signup_deadline()
        configure_signup('replace', code=code, term_id=term_id, expires=expires)
        app.logger.info('Signup mode set to %s by member %s', action, actor_id())
        return jsonify(status='success', code=None if opened else code, open=opened, term=term_name, expires_at=expires)

    def decide_signup(member_id, *, approve):
        result = db().rpc('decide_local_signup', {'p_member': member_id, 'p_actor': actor_id(),
                                                  'p_approve': approve}).execute().data
        if result == 'missing':
            return jsonify(status='error', message='승인 대기 중인 가입 신청이 아닙니다.'), 404
        if result == 'inactive':
            return jsonify(status='error', message='비활성화되거나 차단된 회원은 승인할 수 없습니다.'), 409
        return jsonify(status='success')

    @app.post('/api/admin/members/<int:member_id>/approve-login')
    @login_required(role='admin')
    def admin_approve_signup(member_id):
        return decide_signup(member_id, approve=True)

    @app.post('/api/admin/members/<int:member_id>/reject-login')
    @login_required(role='admin')
    def admin_reject_signup(member_id):
        return decide_signup(member_id, approve=False)

    @app.post('/api/admin/members/<int:member_id>/knu-email')
    @login_required(role='admin')
    def admin_set_knu_email(member_id):
        data = request.get_json(silent=True)
        value = data.get('knu_email') if isinstance(data, dict) else None
        if not isinstance(value, str):
            return jsonify(status='error', message=EMAIL_ERROR), 400
        value = value.strip()
        email = value.lower()
        if value and (not value.isascii() or len(value) > 254 or not KNU_EMAIL_RE.fullmatch(email)):
            return jsonify(status='error', message=EMAIL_ERROR), 400

        members = db().table('members')
        rows = members.select('id,role,social_id,knu_email,auth_session_version') \
            .eq('id', member_id).limit(1).execute().data or []
        if not rows or str(rows[0].get('social_id') or '').startswith('system:'):
            return jsonify(status='error', message='회원을 찾을 수 없습니다.'), 404
        member = rows[0]
        staff = is_officer_role(member)
        if staff and member_id != actor_id() and not primary_admin_check():
            return jsonify(status='error', message='다른 운영진의 학교 메일은 관리자만 변경할 수 있습니다.'), 403

        version = member['auth_session_version']
        fields = {
            'knu_email': email or None,
            'knu_email_verified_at': iso(now_utc()) if email else None,
            'auth_session_version': version + 1,
        }
        if email:
            fields['auth_provider'] = 'local'
        if staff or not email or email != member.get('knu_email'):
            fields.update(pin_hash=None, pin_failed_attempts=0, pin_locked_until=None)

        # The unique index arbitrates competing assignments of the same email.
        # Guard the role and version so a concurrent promotion or credential change wins.
        query = members.update(fields).eq('id', member_id).eq('auth_session_version', version)
        role = member.get('role')
        query = query.eq('role', role) if role is not None else query.is_('role', 'null')
        try:
            updated = query.execute().data
        except Exception as exc:
            if getattr(exc, 'code', None) == '23505':
                return jsonify(status='error', message='다른 회원에게 연결된 학교 메일입니다.'), 409
            raise
        if not updated:
            return jsonify(status='error', message='회원 정보가 바뀌었습니다. 새로고침 후 다시 시도해주세요.'), 409
        return jsonify(status='success', knu_email=email or None)

    @app.post('/api/admin/members/<int:member_id>/login-link')
    @login_required(role='admin')
    def admin_issue_login_link(member_id):
        member = member_row(member_id)
        if not member or member.get('member_status') == 'blocked' or str(member.get('social_id') or '').startswith('system:'):
            return jsonify(status='error', message='링크를 만들 수 없는 회원입니다.'), 404
        if is_officer_role(member) and member_id != actor_id() and not primary_admin_check():
            return jsonify(status='error', message='운영진 계정의 링크는 관리자만 만들 수 있습니다.'), 403
        credential = credential_for(member_id)
        if (credential and credential.get('status') == 'pending') or member.get('account_status') == 'pending' \
                and member.get('auth_provider') == 'local':
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
        email_accounts = db().table('members').select(
            'id,name,student_id,department,knu_email,knu_email_verified_at,account_status'
        ).eq('auth_provider', 'local').execute().data or []
        linked = {m['id']: m['knu_email'] for m in email_accounts
                  if m.get('knu_email') and m.get('knu_email_verified_at')}
        email_pending = [dict(member_id=m['id'], signup_name=m['name'], signup_student_id=m.get('student_id'),
                              signup_department=m.get('department'), login_id=linked[m['id']],
                              created_at=m['knu_email_verified_at'])
                         for m in email_accounts if m['id'] in linked and m['id'] not in by_member
                         and m.get('account_status') == 'pending']
        setting = signup_setting()
        ot = ot_deadline(setting)
        return {'signup_code': active_signup_code(setting), 'pending_signups': sorted(
            pending + email_pending, key=lambda c: c.get('created_at') or ''),
            'credentials': by_member, 'linked_email': linked, 'auto_approve_until': iso(ot) if ot else None}

    app.extensions['local_auth_overview'] = admin_login_overview
    app.extensions['local_auth_credential_for'] = credential_for
