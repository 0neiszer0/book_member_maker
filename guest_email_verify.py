"""Short-lived school-email proofs for public editing links."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from flask import g, request, session
import email_auth_mailer
from security_utils import trusted_client_address

EMAIL_RE = re.compile(r'^[a-z0-9._%+-]+@knu\.ac\.kr$')
PURPOSES = {'topic_edit', 'review_edit', 'room_edit'}


def normalize_knu_email(raw):
    value = str(raw or '').strip().lower()
    return value + '@knu.ac.kr' if value and '@' not in value else value


def is_valid_knu_email(raw, email):
    return str(raw or '').strip().isascii() and len(email) <= 254 and bool(EMAIL_RE.fullmatch(email))


def _digest(app, kind, value):
    return hmac.new(str(app.secret_key or '').encode(), f'{kind}|{value}'.encode(), hashlib.sha256).hexdigest()


def _parse(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def request_guest_email_code(app, db, email, purpose, purpose_label, scope_key):
    raw = email
    email = normalize_knu_email(raw)
    if purpose not in PURPOSES or not is_valid_knu_email(raw, email):
        raise ValueError('학교 메일 주소를 확인해주세요.')
    code_id, code = str(uuid4()), f'{secrets.randbelow(1000000):06d}'
    trusted = bool(g.get('trusted_app_proxy'))
    ip = trusted_client_address(request.headers if trusted else {}, request.remote_addr, trusted)
    result = db.rpc('reserve_email_auth_code', {
        'p_id': code_id, 'p_email': email, 'p_purpose': purpose,
        'p_code_hash': _digest(app, 'email-otp', f'{code_id}|{email}|{purpose}|{code}'),
        'p_client_ip': _digest(app, 'ip', ip),
    }).execute().data
    if not result:
        raise ValueError('요청이 너무 잦습니다. 잠시 뒤 다시 시도해주세요.')
    sender = app.extensions.get('email_auth_sender', email_auth_mailer.send_verification_code)
    sender(email, code, purpose_label)
    key = f'{purpose}:{scope_key}'
    challenges = dict(session.get('guest_email_challenges') or {})
    grants = dict(session.get('guest_email_grants') or {})
    grants.pop(key, None)
    challenges[key] = {'id': code_id, 'email': email}
    session['guest_email_challenges'], session['guest_email_grants'] = challenges, grants
    return email


def verify_guest_email_code(app, db, purpose, scope_key, code):
    key = f'{purpose}:{scope_key}'
    challenge = (session.get('guest_email_challenges') or {}).get(key) or {}
    if purpose not in PURPOSES or not challenge or not re.fullmatch(r'[0-9]{6}', str(code or '').strip()):
        return False
    rows = db.table('email_auth_codes').select('*').eq('id', challenge['id']).limit(1).execute().data or []
    row = rows[0] if rows else None
    now = datetime.now(timezone.utc)
    expiry = _parse((row or {}).get('expires_at'))
    if (not row or row.get('email') != challenge.get('email') or row.get('purpose') != purpose
            or row.get('consumed_at') or not expiry or expiry <= now or row.get('attempts', 0) >= 5):
        return False
    attempts = row.get('attempts', 0)
    expected = _digest(app, 'email-otp', f"{row['id']}|{row['email']}|{purpose}|{str(code).strip()}")
    matches = hmac.compare_digest(row['code_hash'], expected)
    update = {'consumed_at': now.isoformat()} if matches else {'attempts': attempts + 1}
    changed = db.table('email_auth_codes').update(update).eq('id', row['id']).eq('attempts', attempts) \
        .is_('consumed_at', 'null').gte('expires_at', now.isoformat()).execute().data
    if not changed or not matches:
        return False
    challenges = dict(session.get('guest_email_challenges') or {})
    challenges.pop(key, None)
    grants = dict(session.get('guest_email_grants') or {})
    grants[key] = {'email': row['email'], 'until': (now + timedelta(minutes=30)).isoformat()}
    session['guest_email_challenges'], session['guest_email_grants'] = challenges, grants
    return True


def get_verified_guest_email(purpose, scope_key):
    grant = (session.get('guest_email_grants') or {}).get(f'{purpose}:{scope_key}') or {}
    email, until = grant.get('email', ''), _parse(grant.get('until'))
    if until and until > datetime.now(timezone.utc) and is_valid_knu_email(email, email):
        return email
    return None
