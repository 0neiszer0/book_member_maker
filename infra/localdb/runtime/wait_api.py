"""Bounded boot readiness; systemd retries app startup if its local API is late."""
import os
import time
from urllib.parse import urlsplit
import requests

def wait_api(timeout=60):
    if os.environ.get('LOCAL_STORAGE_PROXY','').lower() not in {'true','1','yes','on'}:
        return True
    origin=os.environ.get('SUPABASE_URL','').rstrip('/')
    parsed=urlsplit(origin)
    if (parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.port != 55480
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment):
        return False
    token=os.environ.get('SUPABASE_SERVICE_KEY','')
    if not token:
        return False
    until=time.monotonic()+timeout
    with requests.Session() as session:
        session.trust_env=False
        while time.monotonic()<until:
            try:
                result=session.get(origin+'/rest/v1/members?select=id&limit=0',
                    headers={'apikey':token,'Authorization':'Bearer '+token},timeout=5,allow_redirects=False)
                if result.status_code==200:return True
            except requests.RequestException:
                pass
            time.sleep(2)
    return False

if __name__=='__main__':
    raise SystemExit(0 if wait_api() else 'Local database API is not ready; retry after recovery.')
