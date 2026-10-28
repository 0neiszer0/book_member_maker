"""Root-only local snapshots. These do not replace an off-PC encrypted backup."""
from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3


def snapshot(source, destination):
    """SQLite backup API includes committed WAL changes without copying live WAL."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file() or destination.exists():
        raise ValueError('Snapshot requires an existing source and a new destination')
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=10)) as src, \
            closing(sqlite3.connect(destination)) as dst:
        src.backup(dst, pages=256, sleep=0.1)
        if dst.execute('pragma integrity_check').fetchone() != ('ok',):
            raise RuntimeError('Wiki snapshot integrity check failed')
    destination.chmod(0o600)


def main():
    if os.geteuid() != 0:
        raise SystemExit('Run as root; snapshots contain identity secrets')
    os.umask(0o077)
    base = Path('/var/backups/bookmembers-wiki')
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    base.chmod(0o700)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    pending = base / ('.pending-' + stamp)
    pending.mkdir(mode=0o700)
    snapshot('/var/lib/bookmembers-wiki/data.db', pending / 'data.db')
    for name in ('bridge.env', 'engine.env'):
        shutil.copyfile(Path('/etc/bookmembers-wiki') / name, pending / name)
        (pending / name).chmod(0o600)
    images = Path('/var/lib/bookmembers-wiki/data/images')
    if images.exists():
        if any(p.is_symlink() for p in images.rglob('*')):
            raise RuntimeError('Unexpected symlink in wiki attachments')
        shutil.copytree(images, pending / 'images')
    hashes = {}
    for path in pending.rglob('*'):
        if path.is_file():
            with path.open('rb') as handle:
                hashes[path.relative_to(pending).as_posix()] = hashlib.file_digest(handle, 'sha256').hexdigest()
    (pending / 'manifest.json').write_text(json.dumps({
        'engine': 'openNamu v4.4.0-beta.3', 'created_utc': stamp, 'sha256': hashes,
        'restore': 'Stop app and wiki; restore SQLite, attachments and both env files together; keep ownership bookapp and root respectively.',
    }, indent=2) + '\n', encoding='utf-8')
    destination = base / ('snapshot-' + stamp)
    pending.rename(destination)
    # Retain seven complete snapshots; failed/incomplete runs never replace one.
    completed = sorted(p for p in base.glob('snapshot-*') if p.is_dir() and not p.is_symlink())
    for old in completed[:-7]:
        if old.resolve().parent != base.resolve() or not (old / 'manifest.json').is_file():
            raise RuntimeError('Unexpected backup path')
        shutil.rmtree(old)
    print('Wiki snapshot verified:', destination.name)


if __name__ == '__main__':
    main()
