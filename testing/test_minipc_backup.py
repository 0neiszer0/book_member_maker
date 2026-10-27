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


class BackupTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
