import importlib
import os
import unittest
from unittest.mock import patch

from group_history import meeting_details_from_history, normalize_group_editor_payload
from testing._fake_supabase import FakeSupabase

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'group-editor-test')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'group-editor-test')


class GroupEditorValidationTests(unittest.TestCase):
    def test_complete_snapshot_preserves_exclusion_and_group_names(self):
        state = {'participants': ['가', '나'], 'excluded': [{'name': '나', 'reason': '취소'}], 'group_names': ['사과조']}
        groups, actual = normalize_group_editor_payload([['가']], state)
        self.assertEqual(groups, [['가']])
        self.assertEqual(actual, state)

    def test_incomplete_or_duplicated_charts_are_rejected(self):
        for groups, state in [([['가'], ['가']], None), ([[]], None),
                              ([['가']], {'participants': ['가', '나'], 'excluded': []}),
                              ([['가']], {'participants': ['가'], 'excluded': [{'name': '가', 'reason': '취소'}]})]:
            with self.subTest(groups=groups, state=state), self.assertRaises(ValueError):
                normalize_group_editor_payload(groups, state)

    def test_history_preview_excludes_current_and_later_records(self):
        rows = [{'id': 'old', 'date': '2026-01-01', 'groups': [['가', '나']]},
                {'id': 'current', 'date': '2026-02-01', 'groups': [['가', '나']]},
                {'id': 'future', 'date': '2026-03-01', 'groups': [['가', '나']]}]
        result = meeting_details_from_history(rows, before_date='2026-02-01', exclude_history_id='current')
        self.assertEqual(result['가-나']['dates'], ['2026-01-01'])
        self.assertEqual(result['가-나']['count'], 1)


class GroupEditorRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')
        cls.module.app.config.update(TESTING=True, SECRET_KEY='group-editor-test')

    def setUp(self):
        self.fake = FakeSupabase({
            'members': [{'id': i, 'name': name, 'role': 'admin' if i == 1 else 'member',
                         'is_active': True, 'account_status': 'active'} for i, name in enumerate(['가', '나', '다'], 1)],
            'history': [{'id': 'h', 'date': '2026-01-01', 'groups': [['가', '나']],
                         'present': ['가', '나'], 'facilitators': ['가'],
                         'attendance_confirmed_at': '2026-01-01T15:00:00Z', 'actual_member_ids': None}],
            'seminar_sessions': [], 'seminar_no_shows': [], 'group_pair_restrictions': []})
        self.db = patch.object(self.module, 'supabase', self.fake)
        self.db.start()
        self.rebuild = patch.object(self.module, 'rebuild_co_matrix', return_value={}).start()
        self.client = self.module.app.test_client()
        with self.client.session_transaction() as session:
            session.update(user_id=1, user_role='admin', user_name='가')

    def tearDown(self):
        patch.stopall()

    def test_legacy_actual_attendees_freeze_before_group_edit(self):
        response = self.client.post('/api/admin/history/h/update_meta', json={'groups': [['가', '다']], 'facilitators': ['가']})
        self.assertEqual(response.status_code, 200, response.get_json())
        row = self.fake.rows['history'][0]
        self.assertEqual(row['present'], ['가', '다'])
        self.assertEqual(row['actual_member_ids'], [1, 2])
        details = meeting_details_from_history(self.module._effective_group_history_rows())
        self.assertEqual(details, {})  # 다 was not an actual attendee.

    def test_server_rejects_duplicate_and_confidential_conflict_before_write(self):
        response = self.client.post('/api/admin/history/h/update_meta', json={'groups': [['가'], ['가']]})
        self.assertEqual(response.status_code, 400)
        with patch.object(self.module, '_validate_groups_against_restrictions', return_value=False):
            response = self.client.post('/api/admin/history/h/update_meta', json={'groups': [['가', '나']]})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(any(call[0] == 'update' for call in self.fake.calls))

    def test_explicit_unlinked_confirmation_sets_actual_snapshot(self):
        self.fake.rows['history'][0]['attendance_confirmed_at'] = None
        response = self.client.post('/api/admin/history/h/update_meta', json={'confirm_attendance': True})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.fake.rows['history'][0]['actual_member_ids'], [1, 2])
        self.assertTrue(self.fake.rows['history'][0]['attendance_confirmed_at'])
        self.rebuild.assert_called_once()

    def test_future_actual_confirmation_is_rejected(self):
        self.fake.rows['history'][0].update(date='2099-01-01', attendance_confirmed_at=None)
        response = self.client.post('/api/admin/history/h/update_meta', json={'confirm_attendance': True})
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.fake.rows['history'][0]['attendance_confirmed_at'])

    def test_session_confirmation_before_chart_save_still_counts_actual_only(self):
        self.fake.rows['history'][0].update(seminar_session_id='s', attendance_confirmed_at=None, groups=[['가','나','다']])
        self.fake.rows['seminar_sessions'] = [{'id':'s', 'attendance_confirmed_at':'2026-01-01T15:00:00Z', 'actual_member_ids':[1, 3]}]
        details = meeting_details_from_history(self.module._effective_group_history_rows())
        self.assertEqual(set(details), {'가-다'})

    def test_unconfirmed_plans_never_become_meetings_when_date_passes(self):
        self.fake.rows['history'][0]['attendance_confirmed_at'] = None
        self.assertEqual(self.module._effective_group_history_rows(), [])

    def test_no_show_overrides_actual_snapshot(self):
        self.fake.rows['history'][0].update(seminar_session_id='s', groups=[['가','나','다']])
        self.fake.rows['seminar_sessions'] = [{'id':'s', 'attendance_confirmed_at':'2026-01-01T15:00:00Z', 'actual_member_ids':[1,2,3]}]
        self.fake.rows['seminar_no_shows'] = [{'session_id':'s', 'member_id':2, 'cancelled_at':None}]
        details = meeting_details_from_history(self.module._effective_group_history_rows())
        self.assertEqual(set(details), {'가-다'})

    def test_record_editor_renders_persisted_state_and_history(self):
        response = self.client.get('/records/seminars/h')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('GroupEditor.mount', html)
        self.assertIn('confirm-attendance', html)

    def test_legacy_client_preserves_exclusions_and_named_groups(self):
        state = {'participants':['가','나','다'], 'excluded':[{'name':'다','reason':'취소'}], 'group_names':['사과조']}
        self.fake.rows['history'][0]['group_editor_state'] = state
        response = self.client.post('/api/admin/history/h/update_meta', json={'groups':[['나','가']]})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.fake.rows['history'][0]['group_editor_state'], state)

    def test_legacy_client_cannot_silently_drop_tracked_participant(self):
        self.fake.rows['history'][0]['group_editor_state'] = {'participants':['가','나'], 'excluded':[], 'group_names':['사과조']}
        response = self.client.post('/api/admin/history/h/update_meta', json={'groups':[['가']]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.fake.rows['history'][0]['present'], ['가','나'])

    def test_null_or_forged_snapshot_cannot_drop_tracked_participant(self):
        original_state = {'participants':['가','나'], 'excluded':[], 'group_names':['사과조']}
        self.fake.rows['history'][0]['group_editor_state'] = original_state
        for supplied_state in (None, {'participants':['가'], 'excluded':[], 'group_names':['사과조']}):
            with self.subTest(state=supplied_state):
                response = self.client.post('/api/admin/history/h/update_meta', json={
                    'groups':[['가']], 'group_editor_state':supplied_state})
                self.assertEqual(response.status_code, 400, response.get_json())
                self.assertEqual(self.fake.rows['history'][0]['group_editor_state'], original_state)
                self.assertEqual(self.fake.rows['history'][0]['present'], ['가','나'])
        self.assertFalse(any(call[0] == 'update' for call in self.fake.calls))

    def test_null_snapshot_preserves_exclusions_for_valid_move(self):
        original_state = {'participants':['가','나','다'], 'excluded':[{'name':'다','reason':'취소'}], 'group_names':['사과조']}
        self.fake.rows['history'][0]['group_editor_state'] = original_state
        response = self.client.post('/api/admin/history/h/update_meta', json={
            'groups':[['나','가']], 'group_editor_state':None})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(self.fake.rows['history'][0]['group_editor_state'], original_state)

    def test_explicit_snapshot_keeps_prior_excluded_participant(self):
        self.fake.rows['history'][0]['group_editor_state'] = {
            'participants':['가','나','다'], 'excluded':[{'name':'다','reason':'취소'}], 'group_names':['사과조']}
        response = self.client.post('/api/admin/history/h/update_meta', json={
            'groups':[['가','나']],
            'group_editor_state':{'participants':['가','나'], 'excluded':[], 'group_names':['사과조']}})
        self.assertEqual(response.status_code, 400)


if __name__ == '__main__':
    unittest.main()
