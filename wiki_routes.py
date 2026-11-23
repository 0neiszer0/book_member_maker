"""Small same-origin wiki surface. No generic proxy or native admin endpoints."""
import difflib
import hmac
import os
import re
import secrets
import threading
import time
from urllib.parse import unquote, urlsplit

import bleach
from bs4 import BeautifulSoup
from flask import Blueprint, abort, current_app, g, redirect, render_template, request, session, url_for
from markupsafe import Markup, escape
from minipc_security import LOGIN_PROVIDERS

from wiki_access import (wiki_access, can_edit_title, can_read_title, is_officer_title,
                         strip_officer_includes, OFFICER_PREFIX)
from wiki_engine import OpenNamu, EngineUnavailable, EditConflict, EditRejected
from wiki_templates import WIKI_STARTER_TEMPLATES, starter_template


_CSS_LEN = r'(?:0|\d{1,4}(?:\.\d{1,2})?(?:px|%|em|rem))'
_CSS_COLOR = r'(?:#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,20}|rgba?\(\s*\d{1,3}%?\s*,\s*\d{1,3}%?\s*,\s*\d{1,3}%?\s*(?:,\s*(?:0|1|0?\.\d{1,3})\s*)?\))'
_CSS_RULES = {
    'width': _CSS_LEN, 'min-width': _CSS_LEN, 'max-width': _CSS_LEN, 'height': _CSS_LEN,
    'text-align': r'(?:left|center|right|justify)', 'vertical-align': r'(?:top|middle|bottom)',
    'color': _CSS_COLOR, 'background': _CSS_COLOR, 'background-color': _CSS_COLOR, 'border-color': _CSS_COLOR,
    'border': r'(?:[0-5]px\s+(?:solid|dashed|dotted)\s+' + _CSS_COLOR + r')',
    'margin': r'(?:auto|0)', 'margin-left': r'(?:\d{1,3}px)',
    'padding': _CSS_LEN + r'(?:\s+' + _CSS_LEN + r'){0,3}',
    'font-size': r'(?:[5-9]\d|[12]\d\d|300)%',
}
_STYLE_TAGS = {'table', 'tr', 'td', 'th', 'div', 'span', 'li'}


class WikiStyle:
    """Small allow-list for the inline styles openNamu emits (table width/align/colors,
    text color/size, list indent). Anything else (url(), position, expressions) is dropped.
    openNamu adds an implicit 'text-align: X;' (with a space) to every cell; we drop that so
    existing tables keep the site look, and keep explicit <:> / <(> / <)> ('!important')."""

    def sanitize_css(self, style):
        kept = []
        for part in str(style or '').split(';'):
            if ':' not in part:
                continue
            name, value = part.split(':', 1)
            name, raw = name.strip().lower(), value.strip()
            important = raw.lower().endswith('!important')
            value = raw[:-len('!important')].strip() if important else raw
            if name == 'text-align' and not important:
                continue
            rule = _CSS_RULES.get(name)
            if rule and re.fullmatch(rule, value):
                kept.append(f'{name}:{value}')
        return ';'.join(kept)


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
            a['href'] = (parsed.path or '/') + ('?' + parsed.query if parsed.query else '') + ('#' + parsed.fragment if parsed.fragment else '')
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
    attributes = {
        '*': ['id'], 'a': ['href', 'title', 'rel'], 'td': ['colspan', 'rowspan'],
        'th': ['colspan', 'rowspan', 'scope'], 'ol': ['start'], 'details': ['open'],
    }
    for tag in _STYLE_TAGS:
        attributes[tag] = attributes.get(tag, ['id']) + ['style']
    cleaned = bleach.clean(str(soup), tags=tags, attributes=attributes, css_sanitizer=WikiStyle(),
                           protocols=['http', 'https'], strip=True)
    return Markup(re.sub(r'\sstyle=""', '', cleaned))


MAX_SOURCE_BYTES = 512_000
MAX_FORM_BYTES = 3 * MAX_SOURCE_BYTES + 16_000

DIFF_CONTEXT = 3
MAX_INLINE_DIFF_CHARS = 100_000
MAX_INLINE_LINE_CHARS = 4_000


def _inline(old, new):
    """Mark the changed characters inside a replaced line pair (escaped HTML)."""
    old_out, new_out = [], []
    for tag, a1, a2, b1, b2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        before, after = escape(old[a1:a2]), escape(new[b1:b2])
        if tag == 'equal':
            old_out.append(before); new_out.append(after)
        else:
            if before:
                old_out.append(Markup('<del>') + before + Markup('</del>'))
            if after:
                new_out.append(Markup('<ins>') + after + Markup('</ins>'))
    return Markup('').join(old_out), Markup('').join(new_out)


def diff_rows(old_text, new_text):
    """Line rows like Namuwiki's compare view: kind in same/del/add/skip."""
    old_lines, new_lines = old_text.split('\n'), new_text.split('\n')
    inline = len(old_text) + len(new_text) <= MAX_INLINE_DIFF_CHARS
    rows = []
    for tag, a1, a2, b1, b2 in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False).get_opcodes():
        if tag == 'equal':
            span, after_change, before_change = a2 - a1, a1 > 0 or b1 > 0, a2 < len(old_lines) or b2 < len(new_lines)
            shown = [o for o in range(span) if (after_change and o < DIFF_CONTEXT)
                     or (before_change and o >= span - DIFF_CONTEXT)]
            previous = -1
            for offset in shown:
                if offset != previous + 1:
                    rows.append(dict(kind='skip', count=offset - previous - 1))
                rows.append(dict(kind='same', old=a1 + offset + 1, new=b1 + offset + 1, text=old_lines[a1 + offset]))
                previous = offset
            if span and previous != span - 1:
                rows.append(dict(kind='skip', count=span - previous - 1))
            continue
        removed, added = old_lines[a1:a2], new_lines[b1:b2]
        pairs = min(len(removed), len(added)) if tag == 'replace' else 0
        marked = []
        for i in range(pairs):
            if inline and len(removed[i]) <= MAX_INLINE_LINE_CHARS and len(added[i]) <= MAX_INLINE_LINE_CHARS:
                marked.append(_inline(removed[i], added[i]))
            else:
                marked.append(None)
        for i, line in enumerate(removed):
            rows.append(dict(kind='del', old=a1 + i + 1, new=None,
                             text=marked[i][0] if i < pairs and marked[i] is not None else line))
        for i, line in enumerate(added):
            rows.append(dict(kind='add', old=None, new=b1 + i + 1,
                             text=marked[i][1] if i < pairs and marked[i] is not None else line))
    return rows


def init_wiki_routes(app, get_db):
    app.config.setdefault('WIKI_ENABLED', os.getenv('WIKI_ENABLED', '').lower() in ('1', 'true'))
    app.config.setdefault('WIKI_UPSTREAM', os.getenv('WIKI_UPSTREAM', 'http://127.0.0.1:5096'))
    app.config.setdefault('WIKI_DATABASE', os.getenv('WIKI_DATABASE', ''))
    app.config.setdefault('WIKI_IDENTITY_SECRET', os.getenv('WIKI_IDENTITY_SECRET', ''))
    bp = Blueprint('wiki', __name__, url_prefix='/wiki')

    # Thread-safe TTL cache for /wiki/random's raw title list. Created per
    # init_wiki_routes call so separate app instances never share entries.
    random_cache = {'lock': threading.Lock(), 'entries': {}}
    RANDOM_CACHE_TTL = 300

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
                               officer_prefix=OFFICER_PREFIX,
                               access=getattr(g, 'wiki_access', None),
                               wiki_csrf=session.get('wiki_csrf', ''), **context)

    def message(text, status):
        if request.endpoint == 'wiki.preview':
            return {'ok': False, 'error': text}, status
        return page('message.html', message=text), status

    def hidden():
        # Same answer as a missing page: members cannot probe officer titles.
        return message('문서를 찾을 수 없습니다.', 404)

    def edit_denied(title):
        if is_officer_title(title):
            return '운영진 전용 문서는 운영진만 편집할 수 있습니다.'
        return g.wiki_access.reason

    def renderable(source):
        return source if g.wiki_access.is_officer else strip_officer_includes(source)

    @bp.before_request
    def authorize():
        if not app.config['WIKI_ENABLED']:
            return message('위키 연결을 준비 중입니다.', 503)
        if session.get('auth_provider') not in LOGIN_PROVIDERS or not session.get('user_id'):
            if request.method == 'GET':
                return redirect(url_for('login', next=request.full_path.rstrip('?')))
            return message('로그인 후 다시 시도해 주세요.', 401)
        try:
            g.wiki_access = wiki_access(get_db(), session)
        except Exception:
            current_app.logger.exception('Wiki membership lookup failed')
            return message('회원·학기 상태를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.', 503)
        if not g.wiki_access:
            return message('가입 승인된 회원 계정으로 로그인해야 위키를 읽을 수 있습니다.', 403)
        session.setdefault('wiki_csrf', secrets.token_urlsafe(32))
        if request.method == 'POST':
            # A 512,000-byte draft is up to ~1.5 MB once urlencoded (Korean is
            # 9 bytes per syllable), above Werkzeug's 500 kB per-field default.
            request.max_form_memory_size = MAX_FORM_BYTES
            request.max_content_length = MAX_FORM_BYTES + 64_000
            target = (request.view_args or {}).get('title', '')
            if not can_read_title(g.wiki_access, target):
                return hidden()
            if not can_edit_title(g.wiki_access, target):
                return message(edit_denied(target), 403)
            expected = session['wiki_csrf']
            supplied = request.form.get('wiki_csrf', '')
            origin = request.headers.get('Origin')
            public = os.getenv('PUBLIC_BASE_URL', '').rstrip('/')
            if (not supplied or not hmac.compare_digest(expected.encode(), supplied.encode())
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
        if (not value or len(value) > 200 or any(ord(c) < 32 for c in value)
                or '\\' in value or any(part in ('.', '..') for part in value.split('/'))):
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
        if not can_read_title(g.wiki_access, title):
            return hidden()
        revision = request.args.get('revision')
        if revision is not None and (not revision.isascii() or not revision.isdigit()):
            abort(400)
        backend = engine()
        with backend.user(g.wiki_access.member_id) as client:
            doc = backend.document(client, title, revision)
            rendered = clean_wiki_html(backend.render(client, title, renderable(doc['source']))) if doc['exists'] else ''
        return page('document.html', doc=doc, rendered=rendered, revision=revision,
                    can_edit_doc=can_edit_title(g.wiki_access, title),
                    officer_doc=is_officer_title(title)), 200 if doc['exists'] else 404

    @bp.get('/pages')
    def pages():
        query = request.args.get('q', '').strip()[:200]
        if query:
            title_value(query)
        number = page_number()
        officer = g.wiki_access.is_officer
        scope = request.args.get('scope', 'all') if officer else 'all'
        if scope not in ('all', 'officer', 'public'):
            scope = 'all'
        backend = engine()
        has_next = False
        with backend.user(g.wiki_access.member_id) as client:
            if scope == 'officer' and not query:
                # Officer titles sort together but may sit past page 1: gather them all (bounded).
                titles = []
                for n in range(1, 41):
                    batch = backend.titles(client, '', n)
                    titles += [t if isinstance(t, str) else str(t) for t in batch]
                    if len(batch) < 50:
                        break
                number = 1
            else:
                titles = backend.titles(client, query, number)
                # Decide paging on the engine's page size before hiding titles.
                has_next = len(titles) == 50
        titles = [t if isinstance(t, str) else str(t) for t in titles]
        titles = [t for t in titles if can_read_title(g.wiki_access, t)]
        if scope == 'officer':
            titles = [t for t in titles if is_officer_title(t)]
        elif scope == 'public':
            titles = [t for t in titles if not is_officer_title(t)]
        items = [dict(title=t, officer=officer and is_officer_title(t)) for t in titles]
        return page('pages.html', titles=titles, items=items, query=query, number=number,
                    has_next=has_next, scope=scope)

    @bp.get('/random')
    def random_page():
        # Pick from titles this member may read; officer pages are never offered.
        backend = engine()
        key = (backend.base_url, str(backend.database))
        now = time.monotonic()
        with random_cache['lock']:
            entry = random_cache['entries'].get(key)
            candidates = entry[1] if entry and entry[0] > now else None
        if candidates is None:
            candidates = []
            with backend.user(g.wiki_access.member_id) as client:
                for number in range(1, 21):
                    batch = backend.titles(client, '', number)
                    candidates += [t if isinstance(t, str) else str(t) for t in batch]
                    if len(batch) < 50:
                        break
            with random_cache['lock']:
                random_cache['entries'][key] = (now + RANDOM_CACHE_TTL, candidates)
        candidates = [t for t in candidates
                      if t.strip() and not is_officer_title(t) and t.strip() != '대문' and can_read_title(g.wiki_access, t)]
        if not candidates:
            return redirect(url_for('wiki.document', title='대문'))
        return redirect(url_for('wiki.document', title=secrets.choice(candidates)))

    @bp.get('/history/<path:title>')
    def history(title):
        title_value(title)
        if not can_read_title(g.wiki_access, title):
            return hidden()
        number = page_number()
        backend = engine()
        with backend.user(g.wiki_access.member_id) as client:
            revisions = backend.history(client, title, number)
        return page('history.html', title=title, revisions=revisions, number=number)

    @bp.get('/diff/<path:title>')
    def diff(title):
        title_value(title)
        if not can_read_title(g.wiki_access, title):
            return hidden()
        values = [request.args.get(name, '') for name in ('old', 'new')]
        if not all(v.isascii() and v.isdigit() and 0 < int(v) < 10**9 for v in values):
            return message('비교할 두 버전을 골라 주세요.', 400)
        old, new = sorted(int(v) for v in values)
        if old == new:
            return message('서로 다른 두 버전을 골라 주세요.', 400)
        backend = engine()
        with backend.user(g.wiki_access.member_id) as client:
            sources = [backend.revision_source(client, title, number) for number in (old, new)]
        if any(source is None for source in sources):
            return message('비교할 버전을 찾을 수 없습니다.', 404)
        if not g.wiki_access.is_officer:
            sources = [strip_officer_includes(source) for source in sources]
        rows = diff_rows(*sources)
        return page('diff.html', title=title, old=old, new=new, rows=rows,
                    added=sum(r['kind'] == 'add' for r in rows), removed=sum(r['kind'] == 'del' for r in rows))

    @bp.get('/new')
    def new():
        if not (g.wiki_access.can_edit or g.wiki_access.is_officer):
            return message(g.wiki_access.reason, 403)
        title = request.args.get('title', '').strip()
        if title:
            title_value(title)
            if not can_edit_title(g.wiki_access, title):
                return message(edit_denied(title), 403)
            chosen = starter_template(request.args.get('template', ''))
            if chosen:
                return redirect(url_for('wiki.edit', title=title, template=chosen['key']))
            return redirect(url_for('wiki.edit', title=title))
        return page('new.html', starter_templates=WIKI_STARTER_TEMPLATES,
                    officer_new=g.wiki_access.is_officer and request.args.get('officer') == '1')

    def render_draft(backend, client, title, content):
        return clean_wiki_html(backend.render(client, title, renderable(content)))

    @bp.errorhandler(400)
    @bp.errorhandler(413)
    def bad_request(exc):
        if request.endpoint == 'wiki.preview':
            return message('문서 제목이나 본문 크기를 확인해 주세요.', 400)
        return exc

    @bp.post('/api/preview/<path:title>')
    def preview(title):
        title_value(title)
        content = request.form.get('content')
        if content is None or len(content.encode()) > MAX_SOURCE_BYTES:
            abort(400)
        backend = engine()
        with backend.user(g.wiki_access.member_id) as client:
            rendered = render_draft(backend, client, title, content.replace('\r', ''))
        return {'ok': True, 'html': str(rendered)}

    @bp.route('/edit/<path:title>', methods=['GET', 'POST'])
    def edit(title):
        title_value(title)
        if not can_read_title(g.wiki_access, title):
            return hidden()
        if not can_edit_title(g.wiki_access, title):
            return message(edit_denied(title), 403)
        status, notice, preview, summary = 200, '', None, ''
        doc = None
        if request.method == 'POST':
            content = request.form.get('content', '').replace('\r', '')
            version = request.form.get('version', '')
            summary = request.form.get('summary', '').strip()
            if (len(content.encode()) > MAX_SOURCE_BYTES or len(summary) > 300
                    or not version.isascii() or not version.isdigit()):
                abort(400)
            # Capture the draft before configuration, login or rendering can fail.
            doc = dict(title=title, source=content, version=version, exists=version != '0')
        try:
            backend = engine()
            with backend.user(g.wiki_access.member_id) as client:
                if request.method == 'GET':
                    doc = backend.document(client, title)
                    chosen = starter_template(request.args.get('template', ''))
                    # Starter content only ever fills a brand-new, empty page.
                    if chosen and not doc['exists'] and not doc['source'].strip():
                        doc = dict(doc, source=chosen['content'])
                    return page('edit.html', doc=doc, notice=notice, preview=preview, summary=summary,
                                officer_doc=is_officer_title(title), starter_templates=WIKI_STARTER_TEMPLATES)
                if request.form.get('action') == 'preview':
                    preview = render_draft(backend, client, title, content)
                elif not content.strip():
                    notice, status = '문서 본문을 입력해 주세요.', 400
                else:
                    # Refresh immediately before saving, not only when opening
                    # the editor (including after a preview or roster change).
                    try:
                        fresh = wiki_access(get_db(), session)
                    except Exception:
                        fresh = None
                        notice, status = '회원 상태를 다시 확인하지 못해 저장하지 않았습니다.', 503
                    if not can_edit_title(fresh, title):
                        denied = ('운영진 전용 문서는 운영진만 저장할 수 있습니다.' if is_officer_title(title)
                                  else '현재 학기의 활동 회원만 저장할 수 있습니다.')
                        notice, status = notice or denied, status if notice else 403
                    else:
                        try:
                            backend.save(client, title, content, summary or '문서 편집', version)
                            return redirect(url_for('wiki.document', title=title), code=303)
                        except EditConflict as exc:
                            notice, status = str(exc), 409
                        except EditRejected as exc:
                            notice, status = str(exc), 422
        except EngineUnavailable:
            if doc is None:
                raise
            notice, status = '위키 연결 또는 저장 결과를 확인하지 못했습니다. 작성한 내용은 유지했습니다. 최신 문서와 이력을 먼저 확인해 주세요.', 503
        return page('edit.html', doc=doc, notice=notice, preview=preview, summary=summary,
                    officer_doc=is_officer_title(title), starter_templates=WIKI_STARTER_TEMPLATES), status

    # Officer-only nav entry. Same officer rule as officer documents; cached
    # briefly per member so ordinary pages do not re-query the roster each time.
    nav_cache = app.extensions.setdefault('officer_wiki_nav_cache', {})

    def officer_wiki_url():
        if (not app.config['WIKI_ENABLED'] or session.get('auth_provider') not in LOGIN_PROVIDERS
                or not session.get('user_id')):
            return None
        access = getattr(g, 'wiki_access', None)
        if access is not None:
            ok = access.is_officer
        elif hasattr(g, 'officer_wiki_nav'):
            ok = g.officer_wiki_nav
        else:
            key, now = session.get('user_id'), time.monotonic()
            hit = nav_cache.get(key)
            if hit and hit[0] > now:
                ok = hit[1]
            else:
                try:
                    found = wiki_access(get_db(), session)
                    ok = bool(found and found.is_officer)
                except Exception:
                    current_app.logger.exception('Officer wiki nav lookup failed')
                    ok = False
                nav_cache[key] = (now + 120, ok)
            g.officer_wiki_nav = ok
        return url_for('wiki.document', title=OFFICER_PREFIX + '대문') if ok else None

    @app.context_processor
    def officer_wiki_nav_context():
        return {'officer_wiki_url': officer_wiki_url}

    app.register_blueprint(bp)
