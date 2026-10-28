"""Small same-origin wiki surface. No generic proxy or native admin endpoints."""
import hmac
import os
import secrets
from urllib.parse import unquote, urlsplit

import bleach
from bs4 import BeautifulSoup
from flask import Blueprint, abort, current_app, g, redirect, render_template, request, session, url_for
from markupsafe import Markup

from wiki_access import wiki_access
from wiki_engine import OpenNamu, EngineUnavailable, EditConflict, EditRejected


def clean_wiki_html(source):
    """Keep NamuMark prose/tables; executable engine/user HTML is never embedded."""
    soup = BeautifulSoup(source, 'html.parser')
    for node in soup.select('script, style, iframe, object, embed, form, input, button, meta, link'):
        node.decompose()
    for a in soup.find_all('a', href=True):
        href = a['href']
        parsed = urlsplit(href)
        if href.startswith('/w/'):
            a['href'] = url_for('wiki.document', title=unquote(parsed.path[3:]), _anchor=parsed.fragment or None)
        elif parsed.scheme in ('http', 'https') and parsed.hostname == 'knu-read.xyz':
            a['href'] = (parsed.path or '/') + ('?' + parsed.query if parsed.query else '')
        elif href.startswith('#') or parsed.scheme in ('http', 'https'):
            a['rel'] = 'noreferrer noopener'
        elif href.startswith('/edit/'):
            a.decompose()
        else:
            # Section-edit, file, user-tool and engine-only links cannot escape
            # the authenticated adapter into unimplemented native endpoints.
            a.unwrap()
    tags = {'a', 'p', 'br', 'hr', 'b', 'strong', 'i', 'em', 'u', 's', 'del', 'span', 'div',
            'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
            'table', 'thead', 'tbody', 'tr', 'th', 'td', 'caption', 'sup', 'sub', 'dl', 'dt', 'dd',
            'details', 'summary'}
    return Markup(bleach.clean(str(soup), tags=tags, attributes={
        '*': ['id'], 'a': ['href', 'title', 'rel'], 'td': ['colspan', 'rowspan'],
        'th': ['colspan', 'rowspan', 'scope'], 'ol': ['start'], 'details': ['open'],
    }, protocols=['http', 'https'], strip=True))


def init_wiki_routes(app, get_db):
    app.config.setdefault('WIKI_ENABLED', os.getenv('WIKI_ENABLED', '').lower() in ('1', 'true'))
    app.config.setdefault('WIKI_UPSTREAM', os.getenv('WIKI_UPSTREAM', 'http://127.0.0.1:5096'))
    app.config.setdefault('WIKI_DATABASE', os.getenv('WIKI_DATABASE', ''))
    app.config.setdefault('WIKI_IDENTITY_SECRET', os.getenv('WIKI_IDENTITY_SECRET', ''))
    bp = Blueprint('wiki', __name__, url_prefix='/wiki')

    def engine():
        if 'wiki_engine' not in app.extensions:
            try:
                app.extensions['wiki_engine'] = OpenNamu(app.config['WIKI_UPSTREAM'],
                    app.config['WIKI_DATABASE'], app.config['WIKI_IDENTITY_SECRET'])
            except ValueError as exc:
                raise EngineUnavailable('Wiki integration is not configured') from exc
        return app.extensions['wiki_engine']

    def page(template, **context):
        return render_template('wiki/' + template, lms_title='위키', lms_page='wiki',
                               access=getattr(g, 'wiki_access', None),
                               wiki_csrf=session.get('wiki_csrf', ''), **context)

    def message(text, status):
        return page('message.html', message=text), status

    @bp.before_request
    def authorize():
        if not app.config['WIKI_ENABLED']:
            return message('위키 연결을 준비 중입니다.', 503)
        if session.get('auth_provider') != 'kakao' or not session.get('user_id'):
            if request.method == 'GET':
                return redirect(url_for('login', next=request.full_path.rstrip('?')))
            return message('카카오 로그인 후 다시 시도해 주세요.', 401)
        try:
            g.wiki_access = wiki_access(get_db(), session)
        except Exception:
            current_app.logger.exception('Wiki membership lookup failed')
            return message('회원·학기 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.', 503)
        if not g.wiki_access:
            return message('가입 승인된 회원 계정으로 로그인해야 위키를 읽을 수 있습니다.', 403)
        session.setdefault('wiki_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            if not g.wiki_access.can_edit:
                return message(g.wiki_access.reason, 403)
            expected = session['wiki_csrf']
            supplied = request.form.get('wiki_csrf', '')
            origin = request.headers.get('Origin')
            public = os.getenv('PUBLIC_BASE_URL', '').rstrip('/')
            if (not supplied or not hmac.compare_digest(expected, supplied)
                    or (origin and origin != public)
                    or request.headers.get('Sec-Fetch-Site') == 'cross-site'):
                return message('편집 화면이 만료되었거나 요청 출처가 다릅니다. 다시 열어 주세요.', 403)

    @bp.after_request
    def private_response(response):
        response.headers['Cache-Control'] = 'private, no-store, max-age=0'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        response.headers['Referrer-Policy'] = 'same-origin'
        return response

    @bp.errorhandler(EngineUnavailable)
    def unavailable(exc):
        current_app.logger.warning('Wiki engine unavailable: %s', exc)
        return message('위키에 연결하지 못했습니다. 저장 중이었다면 저장 결과를 먼저 확인해 주세요.', 503)

    def title_value(value):
        if not value or len(value) > 200 or any(ord(c) < 32 for c in value) or '\\' in value:
            abort(400)
        return value

    def page_number():
        try:
            value = int(request.args.get('page', '1'))
        except ValueError:
            abort(400)
        if not 1 <= value <= 10000:
            abort(400)
        return value

    @bp.get('')
    @bp.get('/')
    def home():
        return redirect(url_for('wiki.document', title='대문'))

    @bp.get('/w/<path:title>')
    def document(title):
        title_value(title)
        revision = request.args.get('revision')
        if revision is not None and (not revision.isascii() or not revision.isdigit()):
            abort(400)
        backend = engine()
        with backend.user(g.wiki_access.member_id) as client:
            doc = backend.document(client, title, revision)
            rendered = clean_wiki_html(backend.render(client, title, doc['source'])) if doc['exists'] else ''
        return page('document.html', doc=doc, rendered=rendered, revision=revision), 200 if doc['exists'] else 404

    @bp.get('/pages')
    def pages():
        query = request.args.get('q', '').strip()[:200]
        number = page_number()
        backend = engine()
        with backend.user(g.wiki_access.member_id) as client:
            titles = backend.titles(client, query, number)
        return page('pages.html', titles=titles, query=query, number=number)

    @bp.get('/history/<path:title>')
    def history(title):
        title_value(title)
        number = page_number()
        backend = engine()
        with backend.user(g.wiki_access.member_id) as client:
            revisions = backend.history(client, title, number)
        return page('history.html', title=title, revisions=revisions, number=number)

    @bp.get('/new')
    def new():
        if not g.wiki_access.can_edit:
            return message(g.wiki_access.reason, 403)
        title = request.args.get('title', '').strip()
        if title:
            return redirect(url_for('wiki.edit', title=title_value(title)))
        return page('new.html')

    @bp.route('/edit/<path:title>', methods=['GET', 'POST'])
    def edit(title):
        title_value(title)
        if not g.wiki_access.can_edit:
            return message(g.wiki_access.reason, 403)
        backend = engine()
        status, notice, preview, summary = 200, '', None, ''
        with backend.user(g.wiki_access.member_id) as client:
            if request.method == 'GET':
                doc = backend.document(client, title)
            else:
                content = request.form.get('content', '').replace('\r', '')
                version = request.form.get('version', '')
                summary = request.form.get('summary', '').strip()
                if (len(content.encode()) > 512_000 or len(summary) > 300
                        or not version.isascii() or not version.isdigit()):
                    abort(400)
                doc = dict(title=title, source=content, version=version, exists=version != '0')
                if request.form.get('action') == 'preview':
                    preview = clean_wiki_html(backend.render(client, title, content))
                elif not summary or not content.strip():
                    notice, status = '본문과 편집 요약을 입력해 주세요.', 400
                else:
                    # Refresh immediately before saving, not only when opening
                    # the editor (including after a preview or roster change).
                    try:
                        fresh = wiki_access(get_db(), session)
                    except Exception:
                        fresh = None
                        notice, status = '회원 상태를 다시 확인하지 못해 저장하지 않았습니다.', 503
                    if not fresh or not fresh.can_edit:
                        notice, status = notice or '현재 학기의 활동 회원만 저장할 수 있습니다.', status if notice else 403
                    else:
                        try:
                            backend.save(client, title, content, summary, version)
                            return redirect(url_for('wiki.document', title=title), code=303)
                        except EditConflict as exc:
                            notice, status = str(exc), 409
                        except EditRejected as exc:
                            notice, status = str(exc), 422
                        except EngineUnavailable:
                            notice, status = '저장 결과를 확인하지 못했습니다. 작성한 내용은 유지했습니다. 최신 문서와 이력을 먼저 확인해 주세요.', 503
        return page('edit.html', doc=doc, notice=notice, preview=preview, summary=summary), status

    app.register_blueprint(bp)
