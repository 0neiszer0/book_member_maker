"""Generate isolated trial files; does not install, start, expose or connect to a DB."""
from pathlib import Path
import argparse,base64,hashlib,hmac,json,os,secrets,shutil,time

def prepare(output):
    output=Path(output).resolve()
    if output.exists():
        raise ValueError('Use a new trial directory; never overwrite an existing database')
    output.mkdir(mode=0o700,parents=True)
    source=Path(__file__).resolve().parent
    for name in ['compose.yaml','envoy.yaml','roles.sql']:
        shutil.copyfile(source/name,output/name)
    key=secrets.token_hex(32);password=secrets.token_hex(24)
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value,separators=(',',':')).encode()).rstrip(b'=')
    def token(role):
        now=int(time.time())
        data=encode({'alg':'HS256','typ':'JWT'})+b'.'+encode({'role':role,'iss':'supabase','iat':now,'exp':now+86400})
        return (data+b'.'+base64.urlsafe_b64encode(hmac.new(key.encode(),data,hashlib.sha256).digest()).rstrip(b'=')).decode()
    env=output/'trial.env'
    with env.open('x',encoding='ascii',newline='\n') as file:
        file.write(f'TRIAL_DB_PASSWORD={password}\nTRIAL_JWT_SECRET={key}\nTRIAL_ANON_KEY={token("anon")}\nTRIAL_SERVICE_KEY={token("service_role")}\n')
    env.chmod(0o600)
    (output/'SYNTHETIC-ONLY').write_text('No production secrets or data. Tokens expire after 24 hours.\n')
    print('Trial files prepared; nothing installed or started; credentials not printed')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    prepare(parser.parse_args().output)
