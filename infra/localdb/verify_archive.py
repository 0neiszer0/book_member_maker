"""Verify a decrypted backup archive without extraction, network access or DB writes.

Input is the TAR produced by infra/minipc/backup.py (decrypt into a private
temporary directory first). Hash verification is not a PostgreSQL restore drill.
"""
import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path


def verify(path):
    seen, manifest = {}, None
    with tarfile.open(path, mode='r|') as archive:
        for item in archive:
            if not item.isfile() or item.name in seen or not re.fullmatch(
                    r'database\.dump|storage-schema\.sql|manifest\.json|objects/[0-9]{8}', item.name):
                raise ValueError('Unexpected or duplicate archive member')
            if item.size > 8 * 1024**3:
                raise ValueError('Archive member exceeds validation limit')
            stream = archive.extractfile(item)
            if item.name == 'manifest.json':
                if item.size > 32 * 1024**2:
                    raise ValueError('Manifest exceeds validation limit')
                manifest = json.load(stream)
            else:
                digest, size, magic = hashlib.sha256(), 0, b''
                while chunk := stream.read(1024 * 1024):
                    if not size:
                        magic = chunk[:5]
                    size += len(chunk)
                    digest.update(chunk)
                seen[item.name] = {'size': size, 'sha256': digest.hexdigest(), 'magic': magic}
            if item.name == 'manifest.json':
                seen[item.name] = {}
    if not manifest or manifest.get('format') != 1:
        raise ValueError('Unknown backup format')
    dump = seen.get('database.dump', {})
    if dump.get('magic') != b'PGDMP' or dump.get('sha256') != manifest.get('database_sha256'):
        raise ValueError('Database dump missing or checksum mismatch')
    if set(manifest.get('database_schemas', [])) != {'public', 'supabase_migrations'}:
        raise ValueError('Unexpected database schema coverage')
    buckets = manifest.get('buckets', [])
    ids = {b['id'] for b in buckets}
    if len(ids) != len(buckets):
        raise ValueError('Duplicate bucket')
    expected, keys = set(), set()
    for obj in manifest.get('objects', []):
        filename, key = obj['file'], (obj['bucket'], obj['path'])
        if obj['bucket'] not in ids or key in keys or filename in expected or not filename.startswith('objects/'):
            raise ValueError('Invalid storage inventory')
        actual = seen.get(filename)
        if not actual or actual['size'] != obj['size'] or actual['sha256'] != obj['sha256']:
            raise ValueError('Storage object missing or checksum mismatch')
        expected.add(filename)
        keys.add(key)
    if expected != {n for n in seen if n.startswith('objects/')}:
        raise ValueError('Unlisted storage objects')
    return {'verified': True, 'database_bytes': dump['size'], 'buckets': len(buckets),
            'objects': len(keys), 'restore_drill_complete': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.archive)))
    except Exception:
        raise SystemExit('FAIL: archive verification failed; no files extracted or databases changed')
