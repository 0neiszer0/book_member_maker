"""Opt-in Ubuntu backup: PostgreSQL app schemas + Storage -> age -> rclone.

No scheduler is enabled by this file. See README before first production run.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from uuid import uuid4

from dotenv import dotenv_values
from storage3 import SyncStorageClient


def private_file(path):
    path = Path(path)
    info = path.stat()
    if os.name != 'posix' or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('Configuration must be a root-owned private file on Linux')
    if not path.is_file() or path.is_symlink():
        raise ValueError('Expected a regular private file')
    return path


def check_config(path):
    cfg = dotenv_values(private_file(path), interpolate=False)
    required = ['PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSFILE',
                'PGSSLROOTCERT', 'AGE_RECIPIENT', 'BACKUP_REMOTE', 'RCLONE_CONFIG',
                'APP_ENV_FILE', 'BACKUP_DIR']
    if any(not cfg.get(key) for key in required):
        raise ValueError('Backup configuration is incomplete')
    if cfg.get('PGSSLMODE') != 'verify-full':
        raise ValueError('TLS certificate verification is required')
    if not re.fullmatch(r'age1[0-9a-z]+', cfg['AGE_RECIPIENT']):
        raise ValueError('Use an age public recipient; keep its private key off the server')
    # A named, explicitly approved remote, never an implicit local path or URL.
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*:[^\r\n]+', cfg['BACKUP_REMOTE']):
        raise ValueError('An off-machine rclone remote path is required')
    for key in ('PGPASSFILE', 'RCLONE_CONFIG', 'APP_ENV_FILE'):
        private_file(cfg[key])
    if not Path(cfg['PGSSLROOTCERT']).is_file():
        raise ValueError('CA certificate file missing')
    for tool in ('pg_dump', 'pg_restore', 'psql', 'age', 'rclone'):
        if not shutil.which(tool):
            raise ValueError('Required backup tools are not installed')
    app = dotenv_values(cfg['APP_ENV_FILE'], interpolate=False)
    if not app.get('SUPABASE_SERVICE_KEY') or not app.get('SUPABASE_URL', '').startswith('https://'):
        raise ValueError('Supabase application configuration missing')
    if not Path(cfg['BACKUP_DIR']).is_absolute():
        raise ValueError('Backup directory must be absolute')
    output = Path(cfg['BACKUP_DIR']).resolve()
    repo = Path(__file__).resolve().parents[2]
    if not output.is_absolute() or output == repo or repo in output.parents:
        raise ValueError('Backup directory must be outside the source checkout')
    return cfg, app


def command(args, env=None):
    # Never include subprocess output: database errors can contain personal data.
    result = subprocess.run(args, env=env, capture_output=True, timeout=900)
    if result.returncode:
        raise RuntimeError('Backup command failed: ' + Path(args[0]).name)
    return result.stdout


def storage_entries(bucket, prefix=''):
    offset = 0
    while True:
        page = bucket.list(prefix, {'limit':100, 'offset':offset,
                                   'sortBy':{'column':'name', 'order':'asc'}})
        for row in page:
            name = row['name']
            if not name or '/' in name or name in ('.', '..'):
                raise ValueError('Unexpected storage object name')
            path = prefix + '/' + name if prefix else name
            if row.get('id') is None:
                yield from storage_entries(bucket, path)
            else:
                yield path, row
        if len(page) < 100:
            break
        offset += len(page)


def add_bytes(archive, path, data):
    info = tarfile.TarInfo(path)
    info.size = len(data)
    info.mode = 0o600
    archive.addfile(info, io.BytesIO(data))


def write_archive(stream, dump, storage, metadata):
    """Names in the TAR are generated locally, never taken from object paths."""
    manifest = {'format':1, 'database_schemas':['public', 'supabase_migrations'],
                'database_sha256':sha256(dump),
                'metadata':metadata, 'buckets':[], 'objects':[]}
    with tarfile.open(fileobj=stream, mode='w|') as archive:
        archive.add(dump, arcname='database.dump')
        storage_schema = dump.with_name('storage-schema.sql')
        if storage_schema.exists():
            archive.add(storage_schema, arcname='storage-schema.sql')
        for bucket in storage.list_buckets():
            if getattr(bucket, 'type', None) not in (None, 'STANDARD'):
                raise ValueError('Non-standard Storage bucket needs a separate backup design')
            manifest['buckets'].append(bucket.model_dump(mode='json'))
            api = storage.from_(bucket.id)
            for path, row in storage_entries(api):
                data = api.download(path)
                # Detect size changes; DB and Storage are not one atomic snapshot.
                expected = (row.get('metadata') or {}).get('size')
                if expected is not None and int(expected) != len(data):
                    raise ValueError('Storage object changed during backup')
                name = f'objects/{len(manifest["objects"]):08d}'
                add_bytes(archive, name, data)
                manifest['objects'].append({'bucket':bucket.id, 'path':path, 'file':name,
                    'sha256':hashlib.sha256(data).hexdigest(), 'size':len(data),
                    'metadata':row.get('metadata') or {}})
        add_bytes(archive, 'manifest.json', json.dumps(manifest, ensure_ascii=False).encode())


def sha256(path):
    with open(path, 'rb') as file:
        return hashlib.file_digest(file, 'sha256').hexdigest()


def run_backup(cfg, app):
    import fcntl
    os.umask(0o077)
    root = Path(cfg['BACKUP_DIR'])
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or root.stat().st_uid != 0 or root.stat().st_mode & 0o077:
        raise ValueError('Backup directory must be root-owned and private')
    with (root / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
        target = root / run_id
        target.mkdir(mode=0o700)
        encrypted = target / 'backup.tar.age'
        env = {k:v for k,v in os.environ.items() if not k.startswith('PG')}
        env.update({k:v for k,v in cfg.items() if k.startswith('PG') and v})
        env['PGCONNECT_TIMEOUT'] = '15'
        with tempfile.TemporaryDirectory(prefix='.plain-', dir=root) as tmp:
            dump = Path(tmp) / 'database.dump'
            command(['pg_dump', '--no-password', '--format=custom', '--lock-wait-timeout=5s',
                     '--schema=public', '--schema=supabase_migrations', '--file='+str(dump)], env)
            command(['pg_restore', '--list', str(dump)])
            command(['pg_dump', '--no-password', '--schema-only', '--schema=storage',
                     '--lock-wait-timeout=5s', '--file='+str(dump.with_name('storage-schema.sql'))], env)
            metadata = json.loads(command(['psql', '-X', '--no-password', '-At', '-v', 'ON_ERROR_STOP=1',
                '-c', "select json_build_object('server_version',current_setting('server_version'),"
                "'extensions',(select json_agg(json_build_object('name',extname,'version',extversion)) from pg_extension))"], env))
            headers = {'apikey':app['SUPABASE_SERVICE_KEY'],
                       'Authorization':'Bearer '+app['SUPABASE_SERVICE_KEY']}
            partial = target / 'backup.tar.age.partial'
            with SyncStorageClient(app['SUPABASE_URL'].rstrip('/')+'/storage/v1', headers) as storage, \
                 partial.open('xb') as file, \
                 subprocess.Popen(['age', '-r', cfg['AGE_RECIPIENT']], stdin=subprocess.PIPE,
                                  stdout=file, stderr=subprocess.DEVNULL) as process:
                try:
                    write_archive(process.stdin, dump, storage, metadata)
                    process.stdin.close()
                    if process.wait(timeout=900):
                        raise RuntimeError('Backup encryption failed')
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
            partial.rename(encrypted)
        remote = cfg['BACKUP_REMOTE'].rstrip('/') + '/' + run_id
        common = ['--config', cfg['RCLONE_CONFIG'], '--retries', '2']
        command(['rclone', 'copy', str(target), remote, *common])
        command(['rclone', 'check', str(target), remote, '--download', '--one-way', *common])
        # Only a verified off-machine copy gets a success marker. Never prune remotely.
        marker = target / 'COMPLETE.json'
        marker.write_text(json.dumps({'format':1, 'run_id':run_id,
                                     'ciphertext_sha256':sha256(encrypted)}), encoding='utf-8')
        command(['rclone', 'copyto', str(marker), remote+'/COMPLETE.json', *common])
        print('OK: encrypted backup uploaded and verified; restore drill still required')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='/etc/book_member_maker/backup.env')
    parser.add_argument('--run', action='store_true', help='Export and upload after explicit approval')
    args = parser.parse_args()
    try:
        config, app_config = check_config(args.config)
        if args.run:
            run_backup(config, app_config)
        else:
            print('OK: local configuration only; no network or backup performed')
    except Exception:
        # No exception strings, paths, object names, connection strings, or secrets in journals.
        raise SystemExit('FAIL: backup incomplete; inspect private configuration and tool availability')
