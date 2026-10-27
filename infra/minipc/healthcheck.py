"""Run locally as root; reads the protected systemd env file without printing secrets."""
import json
import urllib.request
from dotenv import dotenv_values

config = dotenv_values('/etc/book_member_maker/app.env')
secret = config.get('ORIGIN_AUTH_SECRET')
if not secret:
    raise SystemExit('FAIL: origin secret missing')
try:
    request = urllib.request.Request('http://127.0.0.1:5000/keep-alive', headers={'X-App-Origin-Auth': secret})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.load(response)
    if data.get('status') != 'ok' or data.get('supabase') != 'alive':
        raise ValueError()
except Exception:
    raise SystemExit('FAIL: application or database health')
print('OK: application and database alive')
