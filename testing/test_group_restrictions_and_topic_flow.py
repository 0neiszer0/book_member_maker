import unittest
from pathlib import Path

from group_restrictions import (
    canonical_name_pair,
    find_restriction_conflicts,
    restricted_pairs_from_rows,
)


ROOT = Path(__file__).resolve().parents[1]


class GroupRestrictionHelperTests(unittest.TestCase):
    def test_pairs_are_canonical_and_id_rows_map_to_names(self):
        rows = [{'member_a_id': 9, 'member_b_id': 2}]
        members = [{'id': 2, 'name': '가람'}, {'id': 9, 'name': '나래'}]
        self.assertEqual({('가람', '나래')}, restricted_pairs_from_rows(rows, members))
        self.assertEqual(('가람', '나래'), canonical_name_pair('나래', '가람'))

    def test_conflict_is_found_only_inside_the_same_group(self):
        restrictions = {('가람', '나래')}
        self.assertEqual(
            [('가람', '나래')],
            find_restriction_conflicts([['가람', '나래'], ['다온']], restrictions),
        )
        self.assertEqual(
            [],
            find_restriction_conflicts([['가람', '다온'], ['나래']], restrictions),
        )


class GroupRestrictionIntegrationContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        cls.index_source = (ROOT / 'templates' / 'bookclub_index.html').read_text(encoding='utf-8')
        cls.topic_admin = (ROOT / 'templates' / 'admin_topic_view.html').read_text(encoding='utf-8')
        cls.migration = (ROOT / 'migrations' / '027_group_pair_restrictions.sql').read_text(encoding='utf-8')

    def test_only_primary_admin_can_manage_restrictions(self):
        self.assertIn('def primary_admin_required', self.app_source)
        self.assertIn('member.get("role") == "admin"', self.app_source)
        self.assertIn('member.get("account_status") == "active"', self.app_source)
        self.assertIn("@app.route('/api/admin/group-pair-restrictions'", self.app_source)
        self.assertIn('@primary_admin_required', self.app_source)
        self.assertIn('{% if can_manage_pair_restrictions %}', self.index_source)

    def test_solver_and_final_outputs_enforce_restrictions(self):
        self.assertIn('restricted_pairs=restricted_pairs', self.app_source)
        self.assertIn('model.Add(x[left_index][g] + x[right_index][g] <= 1)', self.app_source)
        self.assertIn("@app.route('/api/bookclub/validate-groups'", self.app_source)
        self.assertIn('if not _validate_groups_against_restrictions(groups):', self.app_source)

    def test_restriction_table_is_server_only(self):
        self.assertIn('alter table public.group_pair_restrictions enable row level security', self.migration.lower())
        self.assertIn('from public, anon, authenticated', self.migration.lower())
        self.assertIn('to service_role', self.migration.lower())
        self.assertIn('member_a_id < member_b_id', self.migration)

    def test_direct_grouping_page_links_topic_submitters(self):
        self.assertIn("if day_choice in ('mon', 'thu'):", self.app_source)
        self.assertIn('_topic_facilitators_for_session(linked_session, all_active_members)', self.app_source)
        self.assertIn("seminar_session_id = linked_session['id']", self.app_source)

    def test_topic_submission_count_is_dark_and_badged(self):
        self.assertIn('class="submission-total"', self.topic_admin)
        self.assertIn('color: #2F4A24', self.topic_admin)
        self.assertNotIn('class="text-white">{{\n                        submissions|length', self.topic_admin)


if __name__ == '__main__':
    unittest.main()
