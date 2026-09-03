"""Independent adversarial runtime checks for the September attendance change."""
import importlib
import os
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from testing._fake_supabase import FakeSupabase
from attendance_workflow import build_term_attendance
from topic_lifecycle import topic_event_is_expired

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'sol-runtime-review')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'sol-runtime-review')


class RuntimeReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')
        cls.original = cls.module.supabase
        cls.module.app.config.update(TESTING=True)

    def setUp(self):
        self.fake = FakeSupabase({
            'members': [
                {'id': 1, 'name': '운영자', 'role': 'admin', 'is_active': True,
                 'member_status': 'active', 'account_status': 'active', 'department': '국문'},
                {'id': 2, 'name': '불참회원', 'student_id': '202600002', 'is_active': True},
            ],
            'seminar_terms': [{'id': 'term', 'name': '검증학기', 'start_date': '2026-08-01',
                               'end_date': '2026-08-31', 'is_active': True, 'attendance_minimum': 3}],
            'seminar_sessions': [{'id': 'thu', 'day_type': 'thu', 'seminar_week_id': 'week',
                                  'meeting_date': '2026-08-13', 'term_id': 'term', 'planned_member_ids': [1, 2],
                                  'actual_member_ids': None, 'attendance_confirmed_at': None}],
            'history': [{'id': 'h', 'date': '2026-08-13', 'present': ['운영자', '불참회원'],
                         'groups': [['운영자', '불참회원']], 'seminar_session_id': 'thu',
                         'attendance_confirmed_at': '2026-09-03T00:00:00Z'}],
            'seminar_no_shows': [{'session_id': 'thu', 'member_id': 2, 'cancelled_at': None}],
        })
        self.module.supabase = self.fake
        self.client = self.module.app.test_client()
        with self.client.session_transaction() as state:
            state.update(user_id=1, user_role='admin', user_name='운영자', attendance_csrf='review-csrf')

    def tearDown(self):
        self.module.supabase = self.original

    def test_migrated_history_does_not_credit_active_no_show(self):
        with patch('attendance_routes.render_template', return_value='ok') as attendance_render:
            response = self.client.get('/admin/term_attendance?term_id=term')
        self.assertEqual(response.status_code, 200)
        report = attendance_render.call_args.kwargs['report']
        absent = next(row for row in report['members'] if row['id'] == 2)
        self.assertEqual(absent['total'], 0, 'A saved historical group is not evidence that an active no-show attended.')

    def test_actual_confirmation_rejects_existing_no_show_without_writes(self):
        response = self.client.post('/api/admin/seminar_sessions/thu/attendance/confirm',
            headers={'X-CSRF-Token': 'review-csrf'}, json={'member_ids': [1, 2]})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(any(call[0] == 'update' for call in self.fake.calls))

    def test_groups_saved_after_actual_confirmation_are_counted(self):
        self.fake.rows['history'][0]['attendance_confirmed_at'] = None
        self.fake.rows['seminar_no_shows'] = []
        self.fake.rows['seminar_sessions'][0].update(
            actual_member_ids=[1, 2], attendance_confirmed_at='2026-08-13T22:00:00+09:00')
        rows = self.module._effective_group_history_rows()
        self.assertEqual(len(rows), 1, 'Session attendance was confirmed before its group plan was saved.')
        self.assertFalse(rows[0].get('excluded_names'))

    def test_actual_attendance_exclusions_filter_pairs_without_no_show_label(self):
        self.fake.rows['seminar_no_shows'] = []
        self.fake.rows['seminar_sessions'][0].update(
            actual_member_ids=[1], attendance_confirmed_at='2026-08-13T22:00:00+09:00')
        rows = self.module._effective_group_history_rows()
        self.assertEqual(rows[0]['excluded_names'], ['불참회원'])
        self.assertEqual(self.module._matrix_rows_from_history(rows), {})

    def test_unconfirmed_or_future_groups_never_count_as_previous_meetings(self):
        self.fake.rows['history'].extend([
            {'id': 'draft', 'date': '2026-08-20', 'groups': [['운영자', '불참회원']], 'attendance_confirmed_at': None},
            {'id': 'future', 'date': '2099-08-20', 'groups': [['운영자', '불참회원']], 'attendance_confirmed_at': 'yes'},
        ])
        self.assertEqual([row['id'] for row in self.module._effective_group_history_rows()], ['h'])

    def test_direct_history_update_cannot_bypass_private_pair_restriction(self):
        with patch.object(self.module, '_restricted_name_pairs', return_value={('불참회원', '운영자')}):
            response = self.client.post('/api/admin/history/h/update_meta',
                json={'groups': [['운영자', '불참회원']]})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(any(call[0] in {'update', 'insert'} for call in self.fake.calls))
        self.assertNotIn('불참회원', response.get_data(as_text=True))

    def test_excluded_pool_persists_without_becoming_attendance(self):
        with patch.object(self.module, 'rebuild_co_matrix', return_value={}), \
             patch.object(self.module, '_restricted_name_pairs', return_value=set()):
            response = self.client.post('/api/admin/history/h/update_meta', json={
                'groups': [['운영자']], 'facilitators': ['운영자', '불참회원'],
                'group_editor_state': {'participants': ['운영자', '불참회원'],
                                       'excluded': [{'name': '불참회원', 'reason': '편성 제외'}]}})
        self.assertEqual(response.status_code, 200)
        row = self.fake.rows['history'][0]
        self.assertEqual(row['present'], ['운영자'])
        self.assertEqual(row['facilitators'], ['운영자'])
        self.assertEqual(row['group_editor_state']['excluded'][0]['name'], '불참회원')
        self.assertIsNone(self.fake.rows['seminar_sessions'][0]['actual_member_ids'])

    def test_editing_legacy_confirmed_groups_preserves_actual_term_credit(self):
        self.fake.rows['seminar_no_shows'] = []
        with patch.object(self.module, 'rebuild_co_matrix', return_value={}), \
             patch.object(self.module, '_restricted_name_pairs', return_value=set()):
            response = self.client.post('/api/admin/history/h/update_meta', json={
                'groups': [['운영자']],
                'group_editor_state': {'participants': ['운영자', '불참회원'],
                                       'excluded': [{'name': '불참회원', 'reason': '조 편성만 수정'}]}})
        self.assertEqual(response.status_code, 200)
        with patch('attendance_routes.render_template', return_value='ok') as render:
            self.client.get('/admin/term_attendance?term_id=term')
        report = render.call_args.kwargs['report']
        member = next(row for row in report['members'] if row['id'] == 2)
        self.assertEqual(member['total'], 1, 'Group-only editing must not rewrite confirmed actual attendance.')

    def test_standalone_manual_record_can_be_confirmed_and_then_safely_reedited(self):
        row = self.fake.rows['history'][0]
        row.update(seminar_session_id=None, attendance_confirmed_at=None, actual_member_ids=None)
        with patch.object(self.module, 'rebuild_co_matrix', return_value={}), \
             patch.object(self.module, '_restricted_name_pairs', return_value=set()):
            confirmed = self.client.post('/api/admin/history/h/update_meta', json={
                'groups': [['운영자', '불참회원']], 'date': '2026-08-13', 'confirm_attendance': True})
            self.assertEqual(confirmed.status_code, 200)
            self.assertEqual(sorted(row['actual_member_ids']), [1, 2])
            self.assertTrue(row['attendance_confirmed_at'])
            silent_drop = self.client.post('/api/admin/history/h/update_meta', json={'groups': [['운영자']]})
            self.assertEqual(silent_drop.status_code, 400)
            self.assertEqual(row['present'], ['운영자', '불참회원'])
            # The shared editor explicitly preserves removed people and their
            # reasons; this is the actual UI payload for a valid re-edit.
            edited = self.client.post('/api/admin/history/h/update_meta', json={
                'groups': [['운영자']],
                'group_editor_state': {'participants': ['운영자', '불참회원'],
                                       'excluded': [{'name': '불참회원', 'reason': '편성만 수정'}],
                                       'group_names': ['조 1']}})
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(sorted(row['actual_member_ids']), [1, 2])
        with patch('attendance_routes.render_template', return_value='ok') as render:
            self.client.get('/admin/term_attendance?term_id=term')
        totals = {m['id']: m['total'] for m in render.call_args.kwargs['report']['members']}
        self.assertEqual(totals, {1: 1, 2: 1})

    def test_roster_preview_refuses_duplicate_or_unknown_ids(self):
        for ids in ([1, 1], [9999]):
            with self.subTest(ids=ids):
                response = self.client.post('/api/admin/seminar_sessions/thu/roster/preview',
                    headers={'X-CSRF-Token': 'review-csrf'}, json={'method': 'selected', 'member_ids': ids})
                self.assertEqual(response.status_code, 400)
        self.assertFalse(any(call[0] in {'insert', 'update'} for call in self.fake.calls))

    def test_roster_preview_does_not_change_actual_attendance(self):
        response = self.client.post('/api/admin/seminar_sessions/thu/roster/preview',
            headers={'X-CSRF-Token': 'review-csrf'}, json={'method': 'selected', 'member_ids': [2]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['expected_count'], 1)
        self.assertIsNone(self.fake.rows['seminar_sessions'][0]['actual_member_ids'])
        self.assertFalse(any(call[0] in {'insert', 'update'} for call in self.fake.calls))

    def test_roster_apply_rejects_tampered_token_without_rpc(self):
        response = self.client.post('/api/admin/seminar_sessions/thu/roster/apply',
            headers={'X-CSRF-Token': 'review-csrf'}, json={'token': 'tampered'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(any(call[0] in {'insert', 'update'} for call in self.fake.calls))

    def test_member_cannot_see_another_members_term_totals(self):
        self.fake.rows['members'][0]['role'] = 'member'
        with patch('attendance_routes.render_template', return_value='ok') as render:
            response = self.client.get('/my/term_attendance?term_id=term&member_id=2')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(render.call_args.kwargs['mine']['id'], 1)
        self.assertNotIn('report', render.call_args.kwargs)
        denied = self.client.get('/admin/term_attendance?term_id=term')
        self.assertNotEqual(denied.status_code, 200)


class PureBoundaryReview(unittest.TestCase):
    def test_kst_boundary_in_utc_and_year_rollover(self):
        event = {'session_dates': ['2026-12-31', '2027-01-04'], 'seminar_week_id': 'week'}
        self.assertFalse(topic_event_is_expired(event, datetime(2027, 1, 4, 14, 59, 59, tzinfo=timezone.utc)))
        self.assertTrue(topic_event_is_expired(event, datetime(2027, 1, 4, 15, 0, tzinfo=timezone.utc)))

    def test_actual_session_overrides_legacy_group_and_deduplicates_week(self):
        members = [{'id': 1, 'name': '참석'}, {'id': 2, 'name': '불참'}]
        sessions = [{'id': 'thu', 'meeting_date': '2026-08-13', 'attendance_confirmed_at': 'yes', 'actual_member_ids': [1]},
                    {'id': 'mon', 'meeting_date': '2026-08-17', 'attendance_confirmed_at': 'yes', 'actual_member_ids': [1]},
                    {'id': 'next', 'meeting_date': '2026-08-20', 'planned_member_ids': [1, 2]}]
        histories = [{'id': 'h', 'date': '2026-08-13', 'seminar_session_id': 'thu', 'attendance_confirmed_at': 'yes', 'present': ['참석', '불참']}]
        report = build_term_attendance(members, histories, sessions, [], [], [], [], '2026-08-01', '2026-08-31', today=date(2026, 8, 31))
        self.assertEqual([m['total'] for m in report['members']], [1, 0])
        self.assertEqual(len(report['columns']), 2)


if __name__ == '__main__':
    unittest.main()
