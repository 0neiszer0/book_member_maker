"""Initial wiki install only, invoked after explicit production approval.

Provision identity keys on the server without printing or importing test keys.
Existing data/configuration are deliberately refused, never reset by a rerun.
"""
import argparse
import hashlib
import os
from pathlib import Path
import pwd
import secrets
import shutil
import sqlite3

from wiki_backup import snapshot

ENGINE_SHA256 = 'e25961ce88205a228069365ed4d502531ece956e531f5103839de7f6698b0e28'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Run as root after deployment approval')
    stage = args.stage.resolve()
    binary = stage / 'opennamu-linux-amd64'
    with binary.open('rb') as handle:
        assert hashlib.file_digest(handle, 'sha256').hexdigest() == ENGINE_SHA256
    state = Path('/var/lib/bookmembers-wiki')
    config = Path('/etc/bookmembers-wiki')
    install = Path('/opt/bookmembers-wiki')
    assert not any(path.exists() for path in (state, config, install)), 'Wiki already exists; do not reset it'
    with sqlite3.connect((stage / 'seed.db').as_uri() + '?mode=ro', uri=True) as db:
        assert db.execute('pragma integrity_check').fetchone() == ('ok',)
        assert db.execute('select count(*) from data').fetchone()[0] == 14
        assert db.execute('select count(*) from history').fetchone()[0] == 19
        assert not db.execute("select 1 from other where name='copyright_checkbox_text' and data<>''").fetchone()
    user = pwd.getpwnam('bookapp')
    os.umask(0o077)
    state.mkdir(mode=0o700)
    config.mkdir(mode=0o700)
    install.mkdir(mode=0o755)
    install.chmod(0o755)
    snapshot(stage / 'seed.db', state / 'data.db')
    with sqlite3.connect(state / 'data.db') as db:
        before = db.execute('select * from data order by title').fetchall(), db.execute('select * from history order by title,cast(id as integer)').fetchall()
        # Keep historical names, but invalidate every local demo password.
        for (username,) in db.execute("select distinct id from user_set where name='pw'").fetchall():
            password_hash = hashlib.sha3_256(secrets.token_bytes(48)).hexdigest()
            db.execute("update user_set set data=? where name='pw' and id=?", (password_hash, username))
        for name, value in {'auto_update':'', 'back_up':'', 'body':'', 'head':'', 'domain':'', 'http_select':'http'}.items():
            db.execute('delete from other where name=? and coverage=?', (name, ''))
            db.execute('insert into other(name,data,coverage) values(?,?,?)', (name, value, ''))
        assert before == (db.execute('select * from data order by title').fetchall(), db.execute('select * from history order by title,cast(id as integer)').fetchall())
    (config / 'bridge.env').write_text(
        'WIKI_ENABLED=1\nWIKI_UPSTREAM=http://127.0.0.1:5096\n'
        'WIKI_DATABASE=/var/lib/bookmembers-wiki/data.db\n'
        'WIKI_IDENTITY_SECRET=' + secrets.token_urlsafe(48) + '\n', encoding='utf-8')
    (config / 'engine.env').write_text(
        'NAMU_DB=/var/lib/bookmembers-wiki/data\nNAMU_DB_TYPE=sqlite\nNAMU_TLS_MODE=off\n'
        'NAMU_SESSION_KEY=' + secrets.token_urlsafe(48) + '\n', encoding='utf-8')
    for path in config.iterdir():
        path.chmod(0o600)
    for path in (state, state / 'data.db'):
        os.chown(path, user.pw_uid, user.pw_gid)
    shutil.copyfile(binary, install / 'opennamu')
    (install / 'opennamu').chmod(0o755)
    shutil.copytree(stage / 'licenses', install / 'licenses')
    for path in (install / 'licenses').rglob('*'):
        path.chmod(0o755 if path.is_dir() else 0o644)
    print('Private wiki installed; 14 documents and 19 revisions preserved; fresh secrets generated')


if __name__ == '__main__':
    main()
