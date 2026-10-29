"""Synthetic backup format/failure checks; never connects to production."""
import io
import json
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from infra.minipc import backup
from infra.localdb.verify_archive import verify


class BackupTests(unittest.TestCase):
    def test_scope_guard_refuses_data_outside_the_dump(self):
        baseline={'schemas':['public','auth','storage'], 'large_objects':0,
                  'cross_schema_foreign_keys':0, 'excluded_data':{'auth_users':0,'cron_jobs':0,'vault_secrets':0}}
        backup.validate_scope(baseline)
        for change in [{'schemas':['public','uncovered']}, {'large_objects':1},
                       {'cross_schema_foreign_keys':1}, {'excluded_data':{'auth_users':1}},
                       {'excluded_data':{'storage_owner_metadata':1}}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                backup.validate_scope({**baseline,**change})

    def test_failed_container_client_is_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg={'PGCLIENT_IMAGE':'supabase/postgres@sha256:'+'a'*64,
                 'PGHOST':'127.0.0.1','PGPASSFILE':str(Path(temp)/'pgpass')}
            with patch.object(backup,'command',side_effect=RuntimeError('failure')) as command, \
                 patch.object(backup.subprocess,'run') as cleanup, self.assertRaises(RuntimeError):
                backup.pg_command(cfg,['pg_dump'],temp)
            args=command.call_args.args[0]
            cleanup.assert_called_once_with(['docker','rm','-f',args[args.index('--name')+1]],
                                            capture_output=True,timeout=30)

    def test_nested_objects_pagination_and_empty_bucket_are_preserved(self):
        class Bucket:
            def list(self, prefix, options):
                if prefix == 'nested':
                    return [{'name':'photo.webp', 'id':'file', 'metadata':{'size':3}}]
                if options['offset'] == 0:
                    return [{'name':'nested', 'id':None}] + [
                        {'name':f'{i}.webp', 'id':str(i), 'metadata':{'size':3}} for i in range(99)]
                return [{'name':'last.webp', 'id':'last', 'metadata':{'size':3}}]
            def download(self, path):
                return b'pic'
        full = SimpleNamespace(id='photos', type='STANDARD', model_dump=lambda **kw:{'id':'photos','public':False})
        empty = SimpleNamespace(id='empty', type='STANDARD', model_dump=lambda **kw:{'id':'empty','public':True})
        storage = SimpleNamespace(list_buckets=lambda:[full, empty],
            from_=lambda bid: Bucket() if bid == 'photos' else SimpleNamespace(list=lambda *a:[]))
        with tempfile.TemporaryDirectory() as temp:
            dump = Path(temp) / 'database.dump'
            dump.write_bytes(b'synthetic-database')
            stream = io.BytesIO()
            backup.write_archive(stream, dump, storage, {'test':True})
            stream.seek(0)
            with tarfile.open(fileobj=stream) as archive:
                manifest = json.load(archive.extractfile('manifest.json'))
                self.assertEqual(len(manifest['objects']), 101)
                self.assertEqual(len(manifest['buckets']), 2)
                self.assertEqual(manifest['objects'][0]['path'], 'nested/photo.webp')
                self.assertEqual(archive.extractfile('objects/00000000').read(), b'pic')
                self.assertEqual(archive.extractfile('database.dump').read(), b'synthetic-database')
                self.assertFalse(any('nested/' in n for n in archive.getnames()))

    def test_missing_storage_object_aborts_instead_of_silent_partial_success(self):
        bucket = SimpleNamespace(id='photos', type=None, model_dump=lambda **kw:{'id':'photos'})
        api = SimpleNamespace(list=lambda *a:[{'name':'gone.webp','id':'gone','metadata':{}}],
                              download=lambda path: (_ for _ in ()).throw(RuntimeError('gone')))
        storage = SimpleNamespace(list_buckets=lambda:[bucket], from_=lambda bid:api)
        with tempfile.TemporaryDirectory() as temp:
            dump = Path(temp) / 'database.dump'
            dump.write_bytes(b'synthetic')
            with self.assertRaises(RuntimeError):
                backup.write_archive(io.BytesIO(), dump, storage, {})

    def test_database_errors_do_not_expose_output(self):
        with patch.object(backup.subprocess, 'run', return_value=SimpleNamespace(
                returncode=1, stdout=b'private-row', stderr=b'private-password')):
            with self.assertRaises(RuntimeError) as error:
                backup.command(['pg_dump'])
        self.assertNotIn('private', str(error.exception))

    def test_recovery_archive_verifies_wiki_config_and_detects_tampering(self):
        storage = SimpleNamespace(list_buckets=lambda: [])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dump, config, schema = root/'database.dump', root/'app.env', root/'storage-schema.sql'
            dump.write_bytes(b'PGDMPsynthetic')
            config.write_bytes(b'SYNTHETIC_NOT_A_SECRET=true')
            schema.write_bytes(b'-- synthetic storage schema')
            path = root/'backup.tar'
            with path.open('wb') as handle:
                backup.write_archive(handle, dump, storage, {}, {'config/app.env':config})
            self.assertEqual(verify(path)['recovery_files'], 1)
            data = path.read_bytes().replace(b'SYNTHETIC_NOT_A_SECRET=true', b'SYNTHETIC_NOT_A_SECRET=evil')
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                verify(path)

    def test_recovery_manifest_cannot_name_traversal_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); dump=root/'database.dump'; dump.write_bytes(b'PGDMPsynthetic')
            path=root/'backup.tar'
            with path.open('wb') as handle, self.assertRaises(ValueError):
                backup.write_archive(handle, dump, SimpleNamespace(list_buckets=lambda:[]), {}, {'../escape':dump})

    def test_pinned_container_client_mounts_only_named_files_and_uses_no_password_env(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg={'PGCLIENT_IMAGE':'supabase/postgres@sha256:'+'a'*64,
                 'PGHOST':'127.0.0.1', 'PGPASSFILE':str(Path(temp)/'pgpass'),
                 'PGSSLROOTCERT':str(Path(temp)/'ca.crt')}
            with patch.object(backup, 'command', return_value=b'') as command:
                backup.pg_command(cfg, ['pg_dump', '--schema=public'], temp)
                args, env = command.call_args.args
                self.assertEqual(args[:3], ['docker','run','--rm'])
                self.assertIn('--read-only', args)
                self.assertEqual(args.count('--mount'), 3)
                self.assertNotIn('PGPASSWORD', ' '.join(args))
                self.assertNotIn('PGPASSWORD', env)

    def test_export_only_does_not_require_rclone_or_claim_offsite_success(self):
        # Configuration validation on Windows uses mocked private Linux files/tool inventory.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'ca').write_text('synthetic')
            cfg={'PGHOST':'db.project.supabase.co','PGPORT':'5432','PGDATABASE':'postgres',
                 'PGUSER':'postgres','PGPASSFILE':str(root/'pgpass'),'PGSSLMODE':'verify-full',
                 'PGSSLROOTCERT':str(root/'ca'),'AGE_RECIPIENT':'age1synthetic',
                 'APP_ENV_FILE':str(root/'app.env'),'BACKUP_DIR':str(root/'output')}
            app={'SUPABASE_URL':'https://project.supabase.co','SUPABASE_SERVICE_KEY':'synthetic'}
            with patch.object(backup, 'private_file', side_effect=Path), \
                 patch.object(backup, 'dotenv_values', side_effect=[cfg,app]), \
                 patch.object(backup.shutil, 'which', side_effect=lambda tool:None if tool=='rclone' else '/bin/'+tool):
                actual,_=backup.check_config(root/'backup.env', require_remote=False)
                self.assertNotIn('RCLONE_CONFIG',actual)
            with patch.object(backup,'private_file',side_effect=Path), \
                 patch.object(backup,'dotenv_values',side_effect=[cfg,{**app,'SUPABASE_URL':'https://different.supabase.co'}]), \
                 patch.object(backup.shutil,'which',return_value='/bin/tool'), self.assertRaises(ValueError):
                backup.check_config(root/'backup.env',require_remote=False)

    def test_upload_configuration_rejects_local_alias_and_broad_drive_access(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'ca').write_text('synthetic')
            cfg={'PGHOST':'db.project.supabase.co','PGPORT':'5432','PGDATABASE':'postgres',
                 'PGUSER':'postgres','PGPASSFILE':str(root/'pgpass'),'PGSSLMODE':'verify-full',
                 'PGSSLROOTCERT':str(root/'ca'),'AGE_RECIPIENT':'age1synthetic',
                 'APP_ENV_FILE':str(root/'app.env'),'BACKUP_DIR':str(root/'output'),
                 'BACKUP_REMOTE':'backup:daily','RCLONE_CONFIG':str(root/'rclone.conf')}
            app={'SUPABASE_URL':'https://project.supabase.co','SUPABASE_SERVICE_KEY':'synthetic'}
            for kind,scope,folder in [('local','drive.file','id'),('alias','drive.file','id'),('drive','drive','id'),('drive','drive.file','')]:
                (root/'rclone.conf').write_text(f'[backup]\ntype={kind}\nscope={scope}\nroot_folder_id={folder}\n')
                with patch.object(backup,'private_file',side_effect=Path), \
                     patch.object(backup,'dotenv_values',side_effect=[cfg,app]), \
                     patch.object(backup.shutil,'which',return_value='/bin/tool'), self.assertRaises(ValueError):
                    backup.check_config(root/'backup.env')

    def test_v2_archive_rejects_missing_storage_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);dump=root/'database.dump';dump.write_bytes(b'PGDMPsynthetic')
            (root/'storage-schema.sql').write_bytes(b'-- synthetic schema')
            original=io.BytesIO();backup.write_archive(original,dump,SimpleNamespace(list_buckets=lambda:[]),{})
            original.seek(0);target=root/'without-schema.tar'
            with tarfile.open(fileobj=original) as src,tarfile.open(target,'w') as dst:
                for item in src:
                    if item.name!='storage-schema.sql':dst.addfile(item,src.extractfile(item))
            with self.assertRaises(ValueError):verify(target)


if __name__ == '__main__':
    unittest.main()
