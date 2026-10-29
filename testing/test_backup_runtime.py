"""Only new retention/health/boot failure paths; synthetic data, no cloud calls."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from infra.minipc.backup_maintenance import retention_keep, valid_marker, prune_verified, record_health
from infra.localdb.runtime.wait_api import wait_api
from backup_health import backup_notice


class RuntimeTests(unittest.TestCase):
    def test_retention_keeps_latest_day_and_week_without_keeping_every_retry(self):
        now=datetime(2026,10,29,18,tzinfo=timezone.utc)
        names=[(now-timedelta(days=n)).strftime('%Y%m%dT%H%M%SZ')+'-12345678' for n in range(100)]
        extra=now.strftime('%Y%m%dT%H%M%SZ')+'-aaaaaaaa'
        keep=retention_keep(names+[extra])
        self.assertTrue(set(names[1:14]).issubset(keep))
        self.assertLessEqual(len(keep),22)
        self.assertFalse(set(names[-40:]) & keep)
        self.assertEqual(len([n for n in keep if n.startswith(names[0][:16])]),1)

    def test_retention_rejects_path_traversal_and_remote_root(self):
        with self.assertRaises(ValueError):retention_keep(['../backup'])
        command=MagicMock()
        for remote in ['backup:', 'backup:scheduled/..', 'backup:manual']:
            with self.assertRaises(ValueError):prune_verified({'BACKUP_REMOTE':remote},command)
        command.assert_not_called()

    def test_marker_requires_matching_run_and_hash(self):
        name='20261029T080205Z-67c432c7'
        good={'format':1,'run_id':name,'ciphertext_sha256':'a'*64}
        self.assertTrue(valid_marker(good,name))
        self.assertFalse(valid_marker({**good,'run_id':'another'},name))
        self.assertFalse(valid_marker({**good,'ciphertext_sha256':'invalid'},name))

    def test_notification_off_until_explicitly_configured(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertIsNone(backup_notice(datetime.now(timezone.utc)))

    def test_failure_event_stays_deduplicated_and_success_resolves(self):
        now=datetime(2026,10,29,12,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'health.json'
            record={'version':1,'ok':False,'last_success':now.isoformat(),'failure_since':now.isoformat()}
            path.write_text(json.dumps(record))
            self.assertEqual(backup_notice(now,path)['event_key'],backup_notice(now+timedelta(hours=1),path)['event_key'])
            path.write_text(json.dumps({**record,'ok':True,'failure_since':None}))
            self.assertIsNone(backup_notice(now+timedelta(hours=1),path))
            self.assertIsNotNone(backup_notice(now+timedelta(hours=36),path))

    def test_missing_or_malformed_status_becomes_attention_not_exception(self):
        now=datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'health.json'
            self.assertIsNotNone(backup_notice(now,path))
            for value in ['invalid','[]','{"version":1,"last_success":false}']:
                path.write_text(value)
                self.assertIsNotNone(backup_notice(now,path))

    def test_boot_probe_rejects_remote_or_unauthenticated_configuration(self):
        for url in ['https://project.supabase.co','http://127.0.0.1:55481','http://127.0.0.1:55480/path']:
            with patch.dict(os.environ,{'LOCAL_STORAGE_PROXY':'true','SUPABASE_URL':url,'SUPABASE_SERVICE_KEY':'synthetic'},clear=True),patch('requests.Session') as session:
                self.assertFalse(wait_api())
                session.assert_not_called()

    def test_boot_probe_disables_proxies_and_redirects(self):
        with patch.dict(os.environ,{'LOCAL_STORAGE_PROXY':'true','SUPABASE_URL':'http://127.0.0.1:55480','SUPABASE_SERVICE_KEY':'synthetic'},clear=True),patch('requests.Session') as factory:
            session=factory.return_value.__enter__.return_value
            session.get.return_value.status_code=200
            self.assertTrue(wait_api())
            self.assertFalse(session.trust_env)
            self.assertFalse(session.get.call_args.kwargs['allow_redirects'])

    @unittest.skipUnless(os.name=='posix' and os.geteuid()==0, 'Linux root-only filesystem checks')
    def test_retention_only_removes_verified_generated_runs_and_uses_drive_trash(self):
        now=datetime(2026,10,29,12,tzinfo=timezone.utc)
        names=[(now-timedelta(days=n)).strftime('%Y%m%dT%H%M%SZ')+'-12345678' for n in range(75)]
        folders=[{'Name':n,'Path':n,'IsDir':True} for n in names]
        folders.append({'Name':'manual','Path':'manual','IsDir':True})
        folders.append({'Name':'20261029T130000Z-aaaaaaaa','Path':'20261029T130000Z-aaaaaaaa','IsDir':True})
        markers={n:{'format':1,'run_id':n,'ciphertext_sha256':'a'*64} for n in names}
        calls=[]
        def command(args):
            calls.append(args)
            remote=args[2]
            if args[1]=='lsjson' and remote=='backup:scheduled':return json.dumps(folders).encode()
            name=remote.split('/')[1]
            if args[1]=='lsjson':
                return json.dumps([{'Path':'backup.tar.age','IsDir':False}]+(
                    [{'Path':'COMPLETE.json','IsDir':False}] if name in markers else [])).encode()
            if args[1]=='cat':return json.dumps(markers[name]).encode()
            if args[1]=='purge':return b''
            raise AssertionError('Unexpected command')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);root.chmod(0o700)
            for name in names:
                target=root/name;target.mkdir()
                (target/'COMPLETE.json').write_text(json.dumps(markers[name]))
                (target/'backup.tar.age').write_bytes(b'encrypted-synthetic')
            count=prune_verified({'BACKUP_REMOTE':'backup:scheduled','RCLONE_CONFIG':'synthetic','BACKUP_DIR':tmp},command)
            keep=retention_keep(names)
            self.assertEqual({p.name for p in root.iterdir()},keep)
            self.assertEqual(count,len(names)-len(keep))
            purges=[a for a in calls if a[1]=='purge']
            self.assertEqual({a[2].split('/')[1] for a in purges},set(names)-keep)
            self.assertTrue(all('--drive-use-trash=true' in a and '--drive-skip-shortcuts=true' in a for a in purges))

    @unittest.skipUnless(os.name=='posix' and os.geteuid()==0, 'Linux root-only filesystem checks')
    def test_status_is_group_readable_secret_free_and_failure_is_sticky(self):
        now=datetime(2026,10,29,12,tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'health.json'
            record_health(path,True,now)
            record_health(path,False,now+timedelta(hours=24))
            record_health(path,False,now+timedelta(hours=25))
            value=json.loads(path.read_text())
            self.assertEqual(value['failure_since'],(now+timedelta(hours=24)).isoformat())
            self.assertEqual(value['last_success'],now.isoformat())
            self.assertEqual(path.stat().st_mode & 0o777,0o640)
            record_health(path,True,now+timedelta(hours=26))
            self.assertIsNone(json.loads(path.read_text())['failure_since'])


if __name__=='__main__':unittest.main()
