"""Prepare a NEW runtime only. Does not start containers, restore data or switch the app."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import shutil
import time


def prepare():
    if os.geteuid() != 0:
        raise SystemExit('Run as root only after host configuration approval.')
    os.umask(0o077)
    target = Path('/etc/bookmembers-db')
    if target.exists() or target.is_symlink():
        raise SystemExit('Database configuration already exists; will not overwrite.')
    target.mkdir(mode=0o700)
    source = Path(__file__).resolve().parent
    for name in ('compose.yaml', 'envoy.yaml', 'roles.sql'):
        shutil.copyfile(source/name, target/name)
        (target/name).chmod(0o600)
    secret = secrets.token_hex(32)
    password = secrets.token_hex(24)
    created = int(time.time())
    expires = created + 10*365*86400

    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value,separators=(',',':')).encode()).rstrip(b'=')

    def token(role):
        unsigned = encode({'alg':'HS256','typ':'JWT'})+b'.'+encode(
            {'role':role,'iss':'supabase','iat':created,'exp':expires})
        signature = base64.urlsafe_b64encode(hmac.new(secret.encode(),unsigned,hashlib.sha256).digest()).rstrip(b'=')
        return (unsigned+b'.'+signature).decode()

    values = {'LOCAL_DB_PASSWORD':password, 'LOCAL_JWT_SECRET':secret,
              'LOCAL_ANON_KEY':token('anon'), 'LOCAL_SERVICE_KEY':token('service_role')}
    env = target/'database.env'
    env.write_text(''.join(key+'='+value+'\n' for key,value in values.items()))
    env.chmod(0o600)
    (target/'PREPARED.json').write_text(json.dumps({'format':1,'created_at':created,
        'service_key_expires_at':expires,'public_traffic_changed':False}))
    print('Prepared private local database configuration; no services started or app settings changed.')


if __name__ == '__main__':
    prepare()
