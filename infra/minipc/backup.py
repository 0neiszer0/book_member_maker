"""Opt-in Ubuntu backup: PostgreSQL app schemas + Storage -> age -> rclone.

No scheduler is enabled by this file. See README before first production run.
"""
import argparse
import configparser
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
from urllib.parse import urlsplit

from dotenv import dotenv_values
from storage3 import SyncStorageClient
import httpx


def private_file(path):
    path = Path(path)
    info = path.stat()
    if os.name != 'posix' or info.st_uid != 0 or info.st_mode & 0o077:
        raise ValueError('Configuration must be a root-owned private file on Linux')
    if not path.is_file() or path.is_symlink():
        raise ValueError('Expected a regular private file')
    return path


def check_config(path, require_remote=True):
    cfg = dotenv_values(private_file(path), interpolate=False)
    required = ['PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSFILE',
                'AGE_RECIPIENT',
                'APP_ENV_FILE', 'BACKUP_DIR']
    if require_remote:
        required += ['BACKUP_REMOTE', 'RCLONE_CONFIG']
    if any(not cfg.get(key) for key in required):
        raise ValueError('Backup configuration is incomplete')
    mode = cfg.get('DATABASE_MODE', 'remote')
    if mode == 'remote':
        if cfg.get('PGSSLMODE') != 'verify-full' or not cfg.get('PGSSLROOTCERT'):
            raise ValueError('Remote TLS certificate verification is required')
        if not Path(cfg['PGSSLROOTCERT']).is_file():
            raise ValueError('CA certificate file missing')
    elif mode == 'local':
        if (cfg.get('PGHOST') != '127.0.0.1' or cfg.get('PGSSLMODE') != 'disable'
                or not cfg.get('PGCLIENT_IMAGE')
                or not re.fullmatch(r'container:[A-Za-z0-9][A-Za-z0-9_.-]+', cfg.get('PGCLIENT_NETWORK', ''))):
            raise ValueError('Local backup must share the database container loopback network')
    else:
        raise ValueError('Unknown database mode')
    if not re.fullmatch(r'age1[0-9a-z]+', cfg['AGE_RECIPIENT']):
        raise ValueError('Use an age public recipient; keep its private key off the server')
    # A named, explicitly approved remote, never an implicit local path or URL.
    if require_remote and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*:[^\r\n]+', cfg['BACKUP_REMOTE']):
        raise ValueError('An off-machine rclone remote path is required')
    for key in ('PGPASSFILE', 'APP_ENV_FILE', *(('RCLONE_CONFIG',) if require_remote else ())):
        private_file(cfg[key])
    if require_remote:
        remote_config = configparser.ConfigParser(interpolation=None)
        with open(cfg['RCLONE_CONFIG'], encoding='utf-8') as handle:
            remote_config.read_file(handle)
        section = cfg['BACKUP_REMOTE'].split(':', 1)[0]
        if (not remote_config.has_section(section)
                or remote_config.get(section, 'type', fallback='') != 'drive'
                or remote_config.get(section, 'scope', fallback='') != 'drive.file'
                or not remote_config.get(section, 'root_folder_id', fallback='')):
            raise ValueError('Use a Google Drive file-scoped remote rooted at the backup folder')
    pg_tools = ('docker',) if cfg.get('PGCLIENT_IMAGE') else ('pg_dump', 'pg_restore', 'psql')
    if cfg.get('PGCLIENT_IMAGE') and not re.fullmatch(r'supabase/postgres@sha256:[0-9a-f]{64}', cfg['PGCLIENT_IMAGE']):
        raise ValueError('A pinned PostgreSQL client image digest is required')
    if mode == 'remote' and cfg.get('PGCLIENT_NETWORK', 'host') != 'host':
        raise ValueError('Unexpected remote client network')
    for tool in (*pg_tools, 'age', *(('rclone',) if require_remote else ())):
        if not shutil.which(tool):
            raise ValueError('Required backup tools are not installed')
    app = dotenv_values(cfg['APP_ENV_FILE'], interpolate=False)
    api = urlsplit(app.get('SUPABASE_URL', ''))
    valid_api = api.scheme == 'https' and bool(api.hostname) if mode == 'remote' else (
        api.scheme == 'http' and api.hostname == '127.0.0.1' and bool(api.port))
    if (not app.get('SUPABASE_SERVICE_KEY') or not valid_api or api.username or api.password
            or api.path not in {'', '/'} or api.query or api.fragment):
        raise ValueError('Supabase application configuration missing')
    if mode == 'remote':
        match = re.fullmatch(r'([a-z0-9]+)\.supabase\.co', api.hostname)
        if not match or not (
                cfg['PGHOST'] == 'db.' + match[1] + '.supabase.co'
                or (cfg['PGHOST'].endswith('.pooler.supabase.com')
                    and cfg['PGUSER'] == 'postgres.' + match[1])):
            raise ValueError('Database and Storage must belong to the same Supabase project')
    if not Path(cfg['BACKUP_DIR']).is_absolute():
        raise ValueError('Backup directory must be absolute')
    output = Path(cfg['BACKUP_DIR']).resolve()
    repo = Path(__file__).resolve().parents[2]
    if not output.is_absolute() or output == repo or repo in output.parents:
        raise ValueError('Backup directory must be outside the source checkout')
    return cfg, app


def pg_command(cfg, args, dump_dir=None):
    """Reuse the pinned PG17 image; do not install an older PG16 host client."""
    if args[0] not in {'pg_dump', 'pg_restore', 'psql'}:
        raise ValueError('Unexpected PostgreSQL tool')
    env = {k:v for k,v in os.environ.items() if not k.startswith('PG')}
    keys = ('PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGPASSFILE', 'PGSSLMODE', 'PGSSLROOTCERT')
    settings = {k:cfg[k] for k in keys if cfg.get(k)}
    settings['PGCONNECT_TIMEOUT'] = '15'
    if not cfg.get('PGCLIENT_IMAGE'):
        env.update(settings)
        return command(args, env)
    client_name = 'bookmembers-backup-client-' + uuid4().hex
    invocation = ['docker', 'run', '--rm', '--name', client_name, '--network', cfg.get('PGCLIENT_NETWORK', 'host'),
                  '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges',
                  '--memory=256m', '--cpus=0.5', '--pids-limit=64']
    for key, value in settings.items():
        invocation += ['--env', key + '=' + value]
    mounts = [(cfg['PGPASSFILE'], True)]
    if cfg.get('PGSSLROOTCERT'):
        mounts.append((cfg['PGSSLROOTCERT'], True))
    if dump_dir is not None:
        mounts.append((str(dump_dir), False))
    for path, readonly in mounts:
        if ',' in path or '\n' in path or '\r' in path or not Path(path).is_absolute():
            raise ValueError('Unexpected backup mount path')
        invocation += ['--mount', f'type=bind,source={path},target={path}' + (',readonly' if readonly else '')]
    invocation += ['--entrypoint', args[0], cfg['PGCLIENT_IMAGE'], *args[1:]]
    try:
        return command(invocation, env)
    except BaseException:
        # Killing the CLI does not stop its container. Remove only this generated client.
        subprocess.run(['docker', 'rm', '-f', client_name], capture_output=True, timeout=30)
        raise


SCOPE_CATALOG_SQL = """
select json_build_object(
 'server_version',current_setting('server_version'),
 'schemas',(select json_agg(nspname order by nspname) from pg_namespace
            where nspname !~ '^pg_' and nspname <> 'information_schema'),
 'relations',(select json_agg(n.nspname||'.'||c.relname) from pg_class c
              join pg_namespace n on n.oid=c.relnamespace where c.relkind in ('r','p')
              and n.nspname !~ '^pg_' and n.nspname <> 'information_schema'),
 'extensions',(select json_agg(json_build_object('name',e.extname,'version',e.extversion,'schema',n.nspname))
               from pg_extension e join pg_namespace n on n.oid=e.extnamespace),
 'cross_schema_foreign_keys',(select count(*) from pg_constraint c
   join pg_class target on target.oid=c.confrelid
   join pg_namespace n on n.oid=target.relnamespace
   where c.contype='f' and c.connamespace='public'::regnamespace
   and n.nspname not in ('public','supabase_migrations')),
 'large_objects',(select count(*) from pg_largeobject_metadata))
"""
MANAGED_SCHEMAS = {'public', 'supabase_migrations', 'auth', 'storage', 'extensions',
                   'graphql', 'graphql_public', 'realtime', 'vault', 'pgbouncer',
                   'pgsodium', 'pgsodium_masks', 'net', 'cron', 'supabase_functions',
                   '_realtime', '_analytics'}


def readonly_json(cfg, sql):
    return json.loads(pg_command(cfg, ['psql', '-X', '--no-password', '-qAt', '-v', 'ON_ERROR_STOP=1',
        '-c', "BEGIN TRANSACTION READ ONLY; SET LOCAL statement_timeout='15s'; " + sql + '; COMMIT;']))


def validate_scope(metadata):
    if (set(metadata.get('schemas') or []) - MANAGED_SCHEMAS
            or metadata['large_objects'] or metadata['cross_schema_foreign_keys']
            or any(metadata['excluded_data'].values())):
        raise ValueError('Data outside the supported backup scope requires a separate migration design')


def database_metadata(cfg, app):
    metadata = readonly_json(cfg, SCOPE_CATALOG_SQL)
    relations = set(metadata.pop('relations') or [])
    queries = []
    for label, table, predicate in [
            ('auth_users','auth.users','true'), ('cron_jobs','cron.job','true'),
            ('vault_secrets','vault.secrets','true'),
            ('storage_owner_metadata','storage.objects',
             "owner_id is not null or (user_metadata is not null and user_metadata <> '{}'::jsonb)")]:
        if table in relations:
            queries += ["'" + label + "'", '(select count(*) from ' + table + ' where ' + predicate + ')']
    metadata['excluded_data'] = readonly_json(cfg, 'select json_build_object(' + ','.join(queries) + ')')
    metadata['source'] = {'mode':cfg.get('DATABASE_MODE','remote'), 'api_host':urlsplit(app['SUPABASE_URL']).hostname,
                          'database_host':cfg['PGHOST'], 'database':cfg['PGDATABASE']}
    validate_scope(metadata)
    metadata['scope_checked'] = True
    return metadata


def recovery_files(cfg, temporary):
    """Snapshot host files only when explicitly configured; all enter the encrypted TAR."""
    if cfg.get('BACKUP_HOST_STATE', '').lower() not in {'1', 'true', 'yes'}:
        return {}
    files = {'config/app.env': private_file(cfg['APP_ENV_FILE'])}
    for key, name in [('DATABASE_ENV_FILE', 'config/database.env'),
                      ('WIKI_BRIDGE_ENV_FILE', 'config/wiki-bridge.env'),
                      ('WIKI_ENGINE_ENV_FILE', 'config/wiki-engine.env')]:
        if cfg.get(key):
            files[name] = private_file(cfg[key])
    if cfg.get('WIKI_DATABASE'):
        if not cfg.get('WIKI_BRIDGE_ENV_FILE') or not cfg.get('WIKI_ENGINE_ENV_FILE'):
            raise ValueError('Wiki identity configuration is required for recovery')
        try:
            from infra.minipc.wiki_backup import snapshot
        except ModuleNotFoundError:
            from wiki_backup import snapshot
        destination = Path(temporary) / 'wiki-snapshot.db'
        snapshot(cfg['WIKI_DATABASE'], destination)
        files['wiki/data.db'] = destination
    if cfg.get('WIKI_IMAGES_DIR'):
        images = Path(cfg['WIKI_IMAGES_DIR'])
        if images.is_symlink():
            raise ValueError('Unexpected wiki attachment directory')
        if images.exists():
            for path in sorted(images.rglob('*')):
                if path.is_symlink():
                    raise ValueError('Unexpected wiki attachment symlink')
                if path.is_file():
                    files['wiki/images/' + path.relative_to(images).as_posix()] = path
    return files


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


def add_recovery_file(archive, name, path):
    """Hash the exact bytes copied to TAR, without loading an entire SQLite DB."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        before = os.fstat(handle.fileno())
        info = tarfile.TarInfo(name)
        info.size, info.mode = before.st_size, 0o600
        class Reader:
            def read(self, size):
                data = handle.read(size)
                digest.update(data)
                return data
        archive.addfile(info, Reader())
        after = os.fstat(handle.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError('Recovery file changed during backup')
    return before.st_size, digest.hexdigest()


def write_archive(stream, dump, storage, metadata, recovery=None):
    """Names in the TAR are generated locally, never taken from object paths."""
    manifest = {'format':2, 'database_schemas':['public', 'supabase_migrations'],
                'database_sha256':sha256(dump),
                'metadata':metadata, 'buckets':[], 'objects':[], 'recovery_files':[]}
    with tarfile.open(fileobj=stream, mode='w|') as archive:
        archive.add(dump, arcname='database.dump')
        storage_schema = dump.with_name('storage-schema.sql')
        if storage_schema.exists():
            archive.add(storage_schema, arcname='storage-schema.sql')
            manifest['storage_schema_sha256'] = sha256(storage_schema)
        for logical_name, path in (recovery or {}).items():
            if (not logical_name or logical_name.startswith('/') or '\\' in logical_name
                    or ':' in logical_name or any(p in {'', '.', '..'} for p in logical_name.split('/'))):
                raise ValueError('Unexpected recovery file name')
            if Path(path).is_symlink() or not Path(path).is_file():
                raise ValueError('Unexpected recovery file')
            name = f'recovery/{len(manifest["recovery_files"]):08d}'
            size, checksum = add_recovery_file(archive, name, path)
            manifest['recovery_files'].append({'name':logical_name, 'file':name,
                'size':size, 'sha256':checksum})
        for bucket in storage.list_buckets():
            if getattr(bucket, 'type', None) not in (None, 'STANDARD'):
                raise ValueError('Non-standard Storage bucket needs a separate backup design')
            manifest['buckets'].append(bucket.model_dump(mode='json'))
            api = storage.from_(bucket.id)
            seen = set()
            for path, row in storage_entries(api):
                if path in seen:
                    raise ValueError('Storage inventory changed during backup')
                seen.add(path)
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


def run_backup(cfg, app, upload=True):
    import fcntl
    os.umask(0o077)
    root = Path(cfg['BACKUP_DIR'])
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or root.stat().st_uid != 0 or root.stat().st_mode & 0o077:
        raise ValueError('Backup directory must be root-owned and private')
    with (root / '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Only our generated private staging directories, never completed backups.
        for stale in root.glob('.plain-*'):
            if (not re.fullmatch(r'\.plain-[a-z0-9_]+', stale.name) or stale.is_symlink()
                    or not stale.is_dir() or stale.resolve().parent != root.resolve()
                    or stale.stat().st_uid != 0 or stale.stat().st_mode & 0o077):
                raise ValueError('Unexpected plaintext staging directory')
            shutil.rmtree(stale)
        metadata = database_metadata(cfg, app)
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8]
        target = root / run_id
        target.mkdir(mode=0o700)
        encrypted = target / 'backup.tar.age'
        with tempfile.TemporaryDirectory(prefix='.plain-', dir=root) as tmp:
            dump = Path(tmp) / 'database.dump'
            pg_command(cfg, ['pg_dump', '--no-password', '--format=custom', '--lock-wait-timeout=5s',
                     '--schema=public', '--schema=supabase_migrations', '--file='+str(dump)], tmp)
            pg_command(cfg, ['pg_restore', '--list', str(dump)], tmp)
            pg_command(cfg, ['pg_dump', '--no-password', '--schema-only', '--schema=storage',
                     '--lock-wait-timeout=5s', '--file='+str(dump.with_name('storage-schema.sql'))], tmp)
            extra_files = recovery_files(cfg, tmp)
            headers = {'apikey':app['SUPABASE_SERVICE_KEY'],
                       'Authorization':'Bearer '+app['SUPABASE_SERVICE_KEY']}
            partial = target / 'backup.tar.age.partial'
            with httpx.Client(trust_env=False, follow_redirects=False, timeout=60) as http, \
                 SyncStorageClient(app['SUPABASE_URL'].rstrip('/')+'/storage/v1', headers, http_client=http) as storage, \
                 partial.open('xb') as file, \
                 subprocess.Popen(['age', '-r', cfg['AGE_RECIPIENT']], stdin=subprocess.PIPE,
                                  stdout=file, stderr=subprocess.DEVNULL) as process:
                try:
                    write_archive(process.stdin, dump, storage, metadata, extra_files)
                    process.stdin.close()
                    if process.wait(timeout=900):
                        raise RuntimeError('Backup encryption failed')
                    file.flush()
                    os.fsync(file.fileno())
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
            partial.rename(encrypted)
        if not upload:
            (target / 'EXPORT.json').write_text(json.dumps({'format':2, 'run_id':run_id,
                'ciphertext_sha256':sha256(encrypted), 'off_machine_verified':False,
                'restore_drill_complete':False}), encoding='utf-8')
            print('OK: encrypted export created; off-machine backup and restore are NOT verified')
            return target
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
    parser.add_argument('--export-only', action='store_true', help='Create encrypted local export for an approved connector upload; no remote success marker')
    args = parser.parse_args()
    try:
        if args.run and args.export_only:
            parser.error('Choose --run or --export-only')
        config, app_config = check_config(args.config, require_remote=not args.export_only)
        if args.run or args.export_only:
            run_backup(config, app_config, upload=not args.export_only)
        else:
            print('OK: local configuration only; no network or backup performed')
    except Exception:
        # No exception strings, paths, object names, connection strings, or secrets in journals.
        raise SystemExit('FAIL: backup incomplete; inspect private configuration and tool availability')
