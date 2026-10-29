import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from infra.localdb.verify_archive import verify


class ArchiveTests(unittest.TestCase):
    def write(self, path, tamper=False, extra=None):
        dump, blob = b'PGDMPsynthetic-restore-test', b'image-bytes'
        manifest = dict(format=1, database_schemas=['public','supabase_migrations'],
            database_sha256=hashlib.sha256(dump).hexdigest(), buckets=[{'id':'private','public':False}],
            objects=[dict(bucket='private',path='folder/image.jpg',file='objects/00000000',size=len(blob),sha256=hashlib.sha256(blob).hexdigest())])
        entries=[('database.dump',dump),('objects/00000000',b'bad' if tamper else blob),('manifest.json',json.dumps(manifest).encode())]
        if extra: entries.append((extra,b'bad'))
        with tarfile.open(path,'w') as archive:
            for name,data in entries:
                member=tarfile.TarInfo(name);member.size=len(data);archive.addfile(member,io.BytesIO(data))

    def test_hash_check_is_not_a_restore_claim(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'backup.tar';self.write(path);result=verify(path)
            self.assertTrue(result['verified']);self.assertEqual(result['objects'],1);self.assertFalse(result['restore_drill_complete'])

    def test_tampered_and_unsafe_archives_rejected_without_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'backup.tar'
            for kw in [{'tamper':True},{'extra':'../escape'},{'extra':'database.dump'},{'extra':'objects/00000001'}]:
                self.write(path,**kw)
                with self.assertRaises(ValueError):verify(path)
            self.assertEqual([p.name for p in Path(d).iterdir()],['backup.tar'])


if __name__=='__main__':unittest.main()
