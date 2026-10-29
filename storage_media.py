"""Expose only image GETs from an explicitly enabled, loopback Storage API."""
import os
import re
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from flask import abort, current_app, request, Response, url_for
import requests

MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
BUCKETS = {'public': {'book-covers'}, 'sign': {'board-uploads', 'engagement-photos'}}


def image_session():
    session = requests.Session()
    session.trust_env = False  # No ambient proxy or .netrc credentials for loopback.
    return session


def valid_object(mode, bucket, key):
    return (bucket in BUCKETS.get(mode, set()) and len(key) <= 512
            and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./-]*', key)
            and all(part not in {'', '.', '..'} for part in key.split('/')))


def browser_storage_url(value):
    """Keep hosted Storage unchanged; never return a loopback URL to a browser."""
    if not value:
        return value
    if not current_app.config.get('LOCAL_STORAGE_PROXY'):
        if urlsplit(value).hostname in {'127.0.0.1', 'localhost', '::1'}:
            raise ValueError('Local Storage media route is not enabled')
        return value
    source = urlsplit(value)
    upstream = urlsplit(current_app.config['LOCAL_STORAGE_UPSTREAM'])
    if (source.scheme, source.netloc) != (upstream.scheme, upstream.netloc):
        raise ValueError('Unexpected Storage URL origin')
    parts = source.path.split('/', 6)
    if len(parts) != 7 or parts[1:4] != ['storage', 'v1', 'object']:
        raise ValueError('Unexpected Storage URL path')
    mode, bucket, key = parts[4:]
    if not valid_object(mode, bucket, key) or source.fragment:
        raise ValueError('Unexpected Storage object')
    args = parse_qs(source.query, keep_blank_values=True, max_num_fields=2)
    if mode == 'sign':
        if set(args) != {'token'} or len(args['token']) != 1 or not valid_token(args['token'][0]):
            raise ValueError('Invalid Storage signature')
    elif args:
        raise ValueError('Unexpected public image query')
    return url_for('storage_image', mode=mode, bucket=bucket, key=key,
                   **({'token': args['token'][0]} if mode == 'sign' else {}))


def valid_token(token):
    return bool(token and len(token) <= 4096 and re.fullmatch(r'[A-Za-z0-9_.-]+', token))


def install_storage_media(app):
    enabled = os.environ.get('LOCAL_STORAGE_PROXY', '').lower() in {'1', 'true', 'yes', 'on'}
    app.config['LOCAL_STORAGE_PROXY'] = enabled
    if not enabled:
        return
    upstream = os.environ.get('SUPABASE_URL', '').rstrip('/')
    parsed = urlsplit(upstream)
    if (parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        raise ValueError('Local Storage requires an explicit HTTP loopback API URL')
    app.config['LOCAL_STORAGE_UPSTREAM'] = upstream

    @app.get('/media/storage/<mode>/<bucket>/<path:key>', endpoint='storage_image')
    def storage_image(mode, bucket, key):
        if not valid_object(mode, bucket, key):
            abort(404)
        token = request.args.get('token')
        if mode == 'sign':
            if set(request.args) != {'token'} or len(request.args.getlist('token')) != 1 or not valid_token(token):
                abort(403)
        elif request.args:
            abort(404)
        upstream_url = f'{upstream}/storage/v1/object/{mode}/{bucket}/{quote(key, safe="/")}'
        if mode == 'sign':
            upstream_url += '?' + urlencode({'token': token})
        try:
            # Never forward cookies, service keys, client headers, or arbitrary destinations.
            with image_session() as session, session.get(upstream_url, timeout=(3, 10), stream=True, allow_redirects=False) as upstream_response:
                if upstream_response.status_code != 200:
                    abort(404 if upstream_response.status_code in {400, 401, 403, 404} else 502)
                mime = upstream_response.headers.get('Content-Type', '').split(';', 1)[0].strip().lower()
                if mime not in IMAGE_TYPES:
                    abort(502)
                payload = bytearray()
                for chunk in upstream_response.iter_content(64 * 1024):
                    if len(payload) + len(chunk) > MAX_IMAGE_BYTES:
                        abort(502)
                    payload.extend(chunk)
        except requests.RequestException:
            # Signed URLs and internal addresses must not appear in logs or error pages.
            abort(502)
        response = Response(bytes(payload), mimetype=mime)
        response.headers['Cache-Control'] = 'public, max-age=86400' if mode == 'public' else 'private, no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response
