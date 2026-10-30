"""Retired Render address: notice and GET navigation only, no app/DB dependencies."""
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from urllib.parse import quote, unquote, urlsplit

SITE = 'https://knu-read.xyz'


def destination(raw):
    """Keep old read links on the fixed site; never forward OAuth codes or writes."""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return SITE + '/'
    if (parts.scheme or parts.netloc or not raw.startswith('/')
            or raw.startswith('//') or '\\' in unquote(raw)
            or any(ord(c) < 32 or ord(c) == 127 for c in unquote(raw))):
        return SITE + '/'
    if parts.path.startswith('/login') or parts.path == '/logout':
        return SITE + '/login'
    path = quote(parts.path or '/', safe='/%:@!$&()*+,-._~')
    query = quote(parts.query, safe='=&%:@!$()*+,-._~/?')
    return SITE + path + ('?' + query if query else '')


def notice(target, automatic=True):
    safe = escape(target, quote=True)
    refresh = f'<meta http-equiv="refresh" content="3;url={safe}">' if automatic else ''
    detail = ('3초 후 새 주소로 이동합니다.' if automatic else
              '이전 주소에서는 저장할 수 없습니다. 새 홈페이지에서 다시 진행해 주세요.')
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,follow"><meta name="referrer" content="no-referrer">{refresh}
<title>책반우 홈페이지 이전 안내</title>
<style>body{{margin:0;background:#f7f7f5;color:#242424;font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:100svh}}main{{box-sizing:border-box;width:min(100%,560px);padding:40px 28px}}.brand{{color:#b51d28;font-weight:750;letter-spacing:.04em}}h1{{font-size:clamp(25px,5vw,34px);line-height:1.4;margin:24px 0 14px}}p{{line-height:1.75;color:#555}}a{{display:block;background:#b51d28;color:white;padding:17px 20px;border-radius:8px;text-decoration:none;font-weight:650;text-align:center;margin:28px 0 16px}}a:focus-visible{{outline:3px solid #333;outline-offset:4px}}small{{color:#666;line-height:1.7}}</style>
</head><body><main><div class="brand">KNU 책반우</div>
<h1>책반우 공식 홈페이지가<br>이전되었습니다.</h1>
<p>경북대학교 중앙독서동아리 책반우의<br>현재 공식 주소는 <strong>knu-read.xyz</strong>입니다.</p>
<a href="{safe}" rel="noreferrer">새 홈페이지로 이동 · knu-read.xyz</a>
<small>{detail}<br>즐겨찾기를 새 주소로 변경해 주세요.</small>
</main></body></html>'''.encode('utf-8')


class Handler(BaseHTTPRequestHandler):
    server_version = 'BookmembersMoved'
    sys_version = ''

    def log_message(self, format, *args):
        # Old share tokens/OAuth parameters and visitor addresses are not logged.
        return

    def reply(self, code, body, content_type='text/html; charset=utf-8'):
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_GET(self):
        if self.path.split('?', 1)[0] in {'/healthz', '/keep-alive'}:
            return self.reply(200, b'OK\n', 'text/plain; charset=utf-8')
        self.reply(200, notice(destination(self.path)))

    do_HEAD = do_GET

    def retired_write(self):
        self.reply(410, notice(SITE + '/', automatic=False))

    do_POST = do_PUT = do_PATCH = do_DELETE = retired_write


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('PORT', '10000'))), Handler).serve_forever()
