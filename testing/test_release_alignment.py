"""Release alignment: pinned CDN assets, production DB volumes, recorded migrations."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)


class AssetReleaseAlignmentTests(unittest.TestCase):
    def setUp(self):
        if not shutil.which('git') or git('rev-parse', 'HEAD').returncode:
            self.skipTest('git checkout required')
        self.release = json.loads((ROOT / 'infra/worker/asset-release.json').read_text(encoding='utf-8'))

    def test_pinned_revision_has_the_same_static_files_as_this_checkout(self):
        revision = self.release['revision']
        self.assertRegex(revision, r'^[0-9a-f]{40}$')
        self.assertEqual(git('cat-file', '-e', revision + '^{commit}').returncode, 0,
                         'asset-release.json revision is not in this repository')
        changed = git('diff', '--name-only', revision, 'HEAD', '--', 'static').stdout.split()
        self.assertEqual(changed, [], 'static files changed after the pinned CDN release; '
                         'bump infra/worker/asset-release.json and rerun prepare-assets.mjs')

    def test_previous_release_stays_retained_for_open_pages(self):
        self.assertIn('9459cfcdac431f40da2caae2534d417f5833f094',
                      [self.release['revision'], *self.release.get('retainedRevisions', [])])

    def test_local_server_manifest_if_present_matches_static_files(self):
        manifest = ROOT / 'asset-manifest.json'
        if not manifest.exists():
            self.skipTest('no generated asset-manifest.json in this checkout')
        from flask import Flask
        from static_assets import validate_static_assets
        app = Flask('manifest-check', root_path=str(ROOT), static_folder=str(ROOT / 'static'))
        self.assertIsNotNone(validate_static_assets(app, manifest))


class ProductionDatabaseLayoutTests(unittest.TestCase):
    def test_compose_pins_the_live_production_volume_names(self):
        compose = (ROOT / 'infra/localdb/runtime/compose.yaml').read_text(encoding='utf-8')
        volumes = compose.split('\nvolumes:', 1)[1]
        for key in ('database', 'database-config', 'files'):
            expected = {'database': 'production-database', 'database-config': 'production-config',
                        'files': 'production-files'}[key]
            self.assertRegex(volumes, rf'\n  {re.escape(key)}:\s*\n    name: bookmembers-db_{expected}\b')


class RecordedMigrationTests(unittest.TestCase):
    MIGRATIONS = ROOT / 'supabase/migrations'

    def test_files_use_the_versions_recorded_in_production(self):
        names = {p.name for p in self.MIGRATIONS.glob('*.sql')}
        self.assertIn('20261028102247_lms_notifications_and_board_content.sql', names)
        self.assertIn('20261028113040_scoped_notices.sql', names)
        self.assertNotIn('20261028093604_lms_notifications_and_board_content.sql', names)
        self.assertNotIn('20261028105758_scoped_notices.sql', names)

    def test_unrecorded_account_security_migration_is_safe_to_rerun(self):
        sql = (self.MIGRATIONS / '20261027122104_minipc_account_security.sql').read_text(encoding='utf-8').lower()
        self.assertIn('create unique index if not exists members_social_id_unique_nonempty', sql)
        self.assertEqual(sql.count('create or replace function'), 2)
        self.assertNotRegex(sql, r'\bcreate (table|index|function|type)\b(?! if not exists)')


if __name__ == '__main__':
    unittest.main()