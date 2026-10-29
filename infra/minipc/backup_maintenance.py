"""Retention for verified, generated backup runs and a secret-free health record."""
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import re
import tempfile

RUN = re.compile(r'\d{8}T\d{6}Z-[0-9a-f]{8}')
KST = timezone(timedelta(hours=9))


def run_time(name):
    if not RUN.fullmatch(name):
        raise ValueError('Unexpected backup run name')
    return datetime.strptime(name[:16], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)


def retention_keep(names, daily=14, weekly=8):
    """Newest run per day/week, including the most recent complete run."""
    days, weeks, keep = set(), set(), set()
    for name in sorted(names, key=run_time, reverse=True):
        local = run_time(name).astimezone(KST)
        day, week = local.date(), local.isocalendar()[:2]
        if day not in days and len(days) < daily:
            keep.add(name)
            days.add(day)
        if week not in weeks and len(weeks) < weekly:
            keep.add(name)
            weeks.add(week)
    return keep


def valid_marker(marker, name):
    return (isinstance(marker, dict) and marker.get('format') == 1
            and marker.get('run_id') == name
            and bool(re.fullmatch(r'[0-9a-f]{64}', str(marker.get('ciphertext_sha256', '')))))


def prune_verified(cfg, command):
    """Drive trash only. Never scan/prune the initial manual backup or remote root."""
    remote = cfg['BACKUP_REMOTE']
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*:scheduled', remote):
        raise ValueError('Retention is limited to the dedicated scheduled directory')
    common = ['--config', cfg['RCLONE_CONFIG'], '--retries', '2',
              '--drive-use-trash=true', '--drive-skip-shortcuts=true']
    folders = json.loads(command(['rclone', 'lsjson', remote, '--dirs-only', *common]))
    if len(folders) > 500:
        raise ValueError('Unexpected backup inventory size')
    verified, seen = {}, set()
    for folder in folders:
        name = folder.get('Name', '')
        if not RUN.fullmatch(name) or folder.get('Path') != name or not folder.get('IsDir'):
            continue
        if name in seen:
            raise ValueError('Duplicate backup directory')
        seen.add(name)
        # Unfinished uploads have no COMPLETE marker; preserve them for inspection.
        entries = json.loads(command(['rclone', 'lsjson', remote+'/'+name, *common]))
        if (len(entries) != 2 or any(row.get('IsDir') for row in entries)
                or {row.get('Path') for row in entries} != {'backup.tar.age', 'COMPLETE.json'}):
            continue
        marker = json.loads(command(['rclone', 'cat', remote+'/'+name+'/COMPLETE.json', '--head', '1024', *common]))
        if valid_marker(marker, name):
            verified[name] = marker
    keep = retention_keep(verified)
    retired = sorted(set(verified)-keep)
    root = Path(cfg['BACKUP_DIR'])
    if root.is_symlink() or root.stat().st_uid != 0 or root.stat().st_mode & 0o077:
        raise ValueError('Unexpected local backup root')
    for name in retired:
        target = root/name
        # Validate before removal; do not traverse links or delete unknown files.
        local_files = []
        if target.is_symlink():
            raise ValueError('Unexpected local backup symlink')
        if target.exists():
            if target.resolve().parent != root.resolve() or not target.is_dir():
                raise ValueError('Unexpected local backup directory')
            local_files = list(target.iterdir())
            if {p.name for p in local_files} != {'backup.tar.age', 'COMPLETE.json'}:
                raise ValueError('Unexpected local backup contents')
            if any(p.is_symlink() or not p.is_file() for p in local_files):
                raise ValueError('Unexpected local backup file')
            if json.loads((target/'COMPLETE.json').read_text()) != verified[name]:
                raise ValueError('Local and remote completion records differ')
        command(['rclone', 'purge', remote+'/'+name, *common])
        for path in local_files:
            path.unlink()
        if local_files:
            target.rmdir()
    return len(retired)


def record_health(path, success, now=None):
    """Only status/timestamps. Neither credentials nor raw exception text are saved."""
    path = Path(path)
    directory = path.parent
    info = directory.stat()
    if directory.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022 or path.is_symlink():
        raise ValueError('Health directory must be root-owned without write access for others')
    try:
        previous = json.loads(path.read_text()) if path.exists() else {}
        if not isinstance(previous, dict):
            previous = {}
    except (OSError, ValueError):
        previous = {}
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    value = {'version':1, 'attempt_at':stamp, 'ok':bool(success),
             'last_success':stamp if success else previous.get('last_success'),
             'failure_since':None if success else previous.get('failure_since') or stamp}
    fd, name = tempfile.mkstemp(prefix='.backup-status-', dir=directory)
    temp = Path(name)
    try:
        os.fchown(fd, 0, info.st_gid)
        os.fchmod(fd, 0o640)
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
