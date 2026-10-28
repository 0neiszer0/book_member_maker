import importlib.util
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('wiki_backup', Path(__file__).resolve().parents[1] / 'infra/minipc/wiki_backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class SnapshotTests(unittest.TestCase):
    def test_live_wal_snapshot_restores_committed_content_only(self):
        with tempfile.TemporaryDirectory() as folder:
            source, target = Path(folder) / 'live.db', Path(folder) / 'restored.db'
            with closing(sqlite3.connect(source)) as live:
                live.execute('pragma journal_mode=wal')
                live.execute('create table data(title text, content text)')
                live.execute('insert into data values(?,?)', ('위키', '저장된 내용'))
                live.commit()
                # This subsequent write must not appear until committed.
                live.execute('insert into data values(?,?)', ('작성중', '미저장'))
                backup.snapshot(source, target)
                with closing(sqlite3.connect(target)) as restored:
                    self.assertEqual(restored.execute('select * from data').fetchall(), [('위키', '저장된 내용')])
                with self.assertRaises(ValueError):
                    backup.snapshot(source, target)
                live.rollback()


if __name__ == '__main__':
    unittest.main()
