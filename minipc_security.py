"""Scoped session/CSRF and authenticated reverse-proxy boundary."""
import hmac
import os
import secrets
import time
from hashlib import sha256
from flask import abort, g, request, session, redirect, url_for, flash
from urllib.parse import urlsplit
from werkzeug.routing import BuildError
from security_utils import safe_internal_next_url

MEMBER_POSTS = {
    'book_suggest', 'support_book_suggestion', 'comment_book_suggestion',
    'seminar_review_claim', 'brick_application_form', 'brick_review_form',
}
# Seminar review links accept guests like topic links; CSRF still applies.
SENSITIVE_POSTS = MEMBER_POSTS | {'seminar_review_form',
    'link_account_submit', 'link_lookup', 'handle_notification', 'boards.write', 'boards.edit', 'seminar_session_toggle',
    'delete_member', 'set_member_status', 'edit_member', 'merge_members', 'create_member',
    'delete_seminar_review',
    # ID/password login (local_auth.py)
    'login_password', 'signup', 'account_convert', 'account_setup', 'account_password',
    'admin_signup_code', 'admin_approve_signup', 'admin_reject_signup', 'admin_issue_login_link',
    'email_auth_request', 'email_auth_verify', 'email_auth_enroll', 'login_pin',
    'pin_setup', 'pin_reset_confirm',
    'admin_set_knu_email', 'admin_recruitment_dues_settings', 'admin_recruitment_toggle_dues',
    'admin_privacy_purge_inactive_members', 'admin_privacy_purge_recruitment_applicants',
}
SENSITIVE_AUTH_PAGES = {
    'login', 'login_password', 'signup', 'email_auth_request', 'email_auth_verify',
    'email_auth_enroll', 'login_pin', 'pin_setup', 'pin_reset_confirm',
}
LOGIN_PROVIDERS = ('kakao', 'local')

# Guest-capable link forms are served as 200 pages, and the CDN drops Set-Cookie on
# those, so a fresh session CSRF value never reaches a first-time visitor. These
# endpoints also accept a signed token bound to the visitor (member id or 'guest').
SIGNED_CSRF_POSTS = {'seminar_review_form', 'seminar_review_claim'}
SIGNED_CSRF_MAX_AGE = 12 * 3600


def _signed_csrf_mac(key, subject, issued):
    return hmac.new(key.encode(), f'csrf|review-link|{subject}|{issued}'.encode(), sha256).hexdigest()


def active_member(row):
    return bool(row and row.get('is_active') is True
                and row.get('account_status') == 'active'
                and row.get('member_status') not in ('inactive', 'blocked'))

def session_login_current(row, sess):
    """False when a saved login no longer matches the member's login method.

    Local sessions share one revocation version across passwords and PINs.
    Kakao sessions end when the member moves to local authentication.
    """
    provider = sess.get('auth_provider')
    if provider == 'local':
        return (row.get('auth_provider') == 'local'
                and int(row.get('auth_session_version') or 0) == int(sess.get('auth_session_version') or 0))
    if provider == 'kakao':
        return row.get('auth_provider') != 'local'
    return True


def has_login_identity(row, sess):
    """A real person's login, including an account linked to verified school email."""
    if str(row.get('social_id') or '').startswith('system:'):
        return False
    if sess.get('auth_provider') == 'local':
        return row.get('auth_provider') == 'local'
    return bool(row.get('social_id'))


def has_term_assignment(db, member_id):
    # Scoped operations may explicitly address a term other than today's.
    return bool(db.table('term_officers').select('member_id').eq('member_id', member_id)
                .limit(1).execute().data)


def authenticated_member(db):
    if not session.get('user_id') or session.get('auth_provider') not in LOGIN_PROVIDERS:
        return None
    rows = db.table('members').select(
        'id,name,student_id,department,role,is_active,account_status,member_status,social_id,'
        'auth_provider,auth_session_version'
    ).eq('id', session['user_id']).limit(1).execute().data or []
    row = rows[0] if rows else None
    if not active_member(row) or not has_login_identity(row, session) or not session_login_current(row, session):
        return None
    return row

def install_security(app, get_db):
    required = os.environ.get('REQUIRE_ORIGIN_AUTH', '').lower() in ('true', '1', 'yes')
    secret = os.environ.get('ORIGIN_AUTH_SECRET', '')
    proxy_callback = os.environ.get('KAKAO_PROXY_REDIRECT_URI', '').strip()
    public_base = os.environ.get('PUBLIC_BASE_URL', '').rstrip('/')
    parsed = urlsplit(public_base)
    if proxy_callback and (len(secret) < 32 or parsed.scheme != 'https'
                           or not parsed.hostname or parsed.username or parsed.password
                           or parsed.path or parsed.query or parsed.fragment
                           or proxy_callback != public_base + '/login/kakao/callback'):
        raise RuntimeError('Proxy OAuth requires an origin secret and the configured public callback')
    if required and (len(secret) < 32 or not os.environ.get('PUBLIC_BASE_URL', '').startswith('https://')):
        raise RuntimeError('Origin protection requires a secret and HTTPS PUBLIC_BASE_URL')
    app.config.update(REQUIRE_ORIGIN_AUTH=required, ORIGIN_AUTH_SECRET=secret,
                      KAKAO_PROXY_REDIRECT_URI=proxy_callback)

    def csrf_token():
        if not session.get('sensitive_csrf'):
            session['sensitive_csrf'] = secrets.token_urlsafe(32)
        return session['sensitive_csrf']

    def csrf_subject():
        return str(session.get('user_id') or 'guest')

    def signed_csrf_token():
        issued = str(int(time.time()))
        return f's1.{issued}.' + _signed_csrf_mac(app.secret_key, csrf_subject(), issued)

    def signed_csrf_valid(token):
        try:
            version, issued, mac = token.split('.')
            age = time.time() - int(issued)
        except ValueError:
            return False
        return (version == 's1' and 0 <= age <= SIGNED_CSRF_MAX_AGE
                and hmac.compare_digest(mac, _signed_csrf_mac(app.secret_key, csrf_subject(), issued)))

    @app.context_processor
    def security_context():
        return {'sensitive_csrf_token': csrf_token, 'review_csrf_token': signed_csrf_token}

    @app.before_request
    def check_security_boundary():
        key = app.config.get('ORIGIN_AUTH_SECRET', '')
        supplied = request.headers.get('X-App-Origin-Auth', '')
        g.trusted_app_proxy = bool(key and hmac.compare_digest(key.encode(), supplied.encode()))
        if app.config.get('REQUIRE_ORIGIN_AUTH') and not g.trusted_app_proxy:
            abort(403)
        if request.method != 'POST' or request.endpoint not in SENSITIVE_POSTS:
            return
        if request.endpoint in MEMBER_POSTS and not authenticated_member(get_db()):
            flash('로그인 후 작성할 수 있습니다.', 'warning')
            next_path = request.path
            if request.endpoint in {'support_book_suggestion', 'comment_book_suggestion'}:
                next_path = request.path.rsplit('/', 1)[0]
            try:
                target = url_for('login', next=safe_internal_next_url(next_path))
            except BuildError:
                target = url_for('kakao_login', next=safe_internal_next_url(next_path))
            return redirect(target, code=303)
        expected = session.get('sensitive_csrf', '')
        token = request.headers.get('X-App-CSRF') or request.form.get('csrf_token', '')
        if request.endpoint in SIGNED_CSRF_POSTS and token.startswith('s1.'):
            if signed_csrf_valid(token):
                return
            abort(403)
        if not expected or not token or not hmac.compare_digest(expected.encode(), token.encode()):
            abort(403)
