"""Scoped session/CSRF and authenticated reverse-proxy boundary."""
import hmac
import os
import secrets
from flask import abort, g, request, session, redirect, url_for, flash
from urllib.parse import urlsplit
from security_utils import safe_internal_next_url

MEMBER_POSTS = {
    'book_suggest', 'support_book_suggestion', 'comment_book_suggestion',
    'seminar_review_form', 'brick_application_form', 'brick_review_form',
}
SENSITIVE_POSTS = MEMBER_POSTS | {
    'link_account_submit', 'link_lookup', 'handle_notification',
    'delete_member', 'set_member_status', 'edit_member', 'merge_members', 'create_member',
}

def active_member(row):
    return bool(row and row.get('is_active') is True
                and row.get('account_status') == 'active'
                and row.get('member_status') not in ('inactive', 'blocked'))

def authenticated_member(db):
    if not session.get('user_id') or session.get('auth_provider') != 'kakao':
        return None
    rows = db.table('members').select(
        'id,name,student_id,department,role,is_active,account_status,member_status,social_id'
    ).eq('id', session['user_id']).limit(1).execute().data or []
    row = rows[0] if rows else None
    return row if active_member(row) and row.get('social_id') else None

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

    @app.context_processor
    def security_context():
        return {'sensitive_csrf_token': csrf_token}

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
            flash('카카오 로그인 후 작성할 수 있습니다.', 'warning')
            next_path = request.path
            if request.endpoint in {'support_book_suggestion', 'comment_book_suggestion'}:
                next_path = request.path.rsplit('/', 1)[0]
            return redirect(url_for('kakao_login', next=safe_internal_next_url(next_path)), code=303)
        expected = session.get('sensitive_csrf', '')
        token = request.headers.get('X-App-CSRF') or request.form.get('csrf_token', '')
        if not expected or not token or not hmac.compare_digest(expected.encode(), token.encode()):
            abort(403)
