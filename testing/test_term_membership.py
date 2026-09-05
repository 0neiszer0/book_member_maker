import importlib
import os
from types import SimpleNamespace
import unittest
from term_membership import scope_members, validate_entries, choose_term
from testing._fake_supabase import FakeSupabase

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'term-members-test')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'term-members-test')


class SemesterMembershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')

    def setUp(self):
        self.original = self.module.supabase
        self.fake = FakeSupabase({
            'members': [{'id':1, 'name':'운영', 'role':'admin', 'account_status':'active', 'member_status':'active', 'is_active':True},
                        {'id':2, 'name':'봄만참석', 'is_active':True}, {'id':3, 'name':'가을복귀', 'is_active':False}],
            'seminar_terms': [dict(id='spring', name='1학기', start_date='2026-03-01', end_date='2026-06-30', roster_initialized_at='yes', roster_revision=2),
                              dict(id='fall', name='2학기', start_date='2026-09-01', end_date='2026-12-31', roster_initialized_at='yes', roster_revision=3)],
            'seminar_term_members': [dict(term_id='spring', member_id=2, status='active', entry_type='new'),
                                     dict(term_id='fall', member_id=3, status='active', entry_type='returning')],
            'seminar_sessions': [dict(id='thu',term_id='fall', day_type='thu',participation_mode='absence_only',meeting_date='2026-09-10',planned_member_ids=None)],
        })
        self.module.supabase = self.fake
        self.client = self.module.app.test_client()
        with self.client.session_transaction() as state:
            state.update(user_id=1, user_role='admin', term_members_csrf='csrf', attendance_csrf='csrf')
        self.headers = {'X-CSRF-Token':'csrf'}

    def tearDown(self):
        self.module.supabase = self.original

    def test_semester_membership_overrides_only_local_copies(self):
        members = self.fake.rows['members']
        spring = scope_members(self.fake, members, term_id='spring')
        fall = scope_members(self.fake, members, term_id='fall')
        self.assertEqual([m['id'] for m in spring if m['is_active']], [2])
        self.assertEqual([m['id'] for m in fall if m['is_active']], [3])
        self.assertFalse(members[2]['is_active'])

    def test_legacy_fallback_and_initialized_empty_are_distinct(self):
        members = self.fake.rows['members']
        self.assertEqual(sum(m['is_active'] for m in scope_members(self.fake, members, term={'id':'old'})), 2)
        self.assertFalse(any(m['is_active'] for m in scope_members(self.fake, members, term={'id':'empty','roster_initialized_at':'yes'})))

    def test_pages_and_monday_thursday_defaults_use_selected_term(self):
        self.assertEqual(self.client.get('/admin/term_members?term_id=fall').status_code, 200)
        response = self.client.post('/api/admin/seminar_sessions/thu/roster/preview', headers=self.headers, json={'method':'selected', 'member_ids':[]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['expected_count'], 1)
        self.fake.rows['seminar_sessions'][0]['day_type'] = 'mon'
        response = self.client.post('/api/admin/seminar_sessions/thu/roster/preview', headers=self.headers, json={'method':'selected', 'member_ids':[2]})
        self.assertEqual(response.status_code, 400, 'outside-term member must not join through import')

    def test_save_uses_revisioned_atomic_rpc(self):
        captured = {}
        def rpc(name, params):
            captured.update(name=name, params=params)
            return SimpleNamespace(execute=lambda:SimpleNamespace(data={'accepted':True,'revision':4}))
        self.fake.rpc = rpc
        result = self.client.post('/api/admin/term_members/fall', headers=self.headers,
                                  json={'revision':3, 'entries':[{'member_id':3,'status':'active','entry_type':'returning'}]})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(captured['name'], 'save_seminar_term_members')
        self.assertEqual(captured['params']['p_revision'], 3)
        self.assertEqual(captured['params']['p_actor'], 1)

    def test_conflict_does_not_report_success(self):
        self.fake.rpc = lambda *args:SimpleNamespace(execute=lambda:SimpleNamespace(data={'accepted':False}))
        response = self.client.post('/api/admin/term_members/fall', headers=self.headers, json={'revision':3,'entries':[]})
        self.assertEqual(response.status_code, 409)

    def test_all_new_writes_require_csrf_and_admin(self):
        for route in ['/api/admin/term_members/fall', '/api/admin/term_members/new_member', '/api/admin/term_members/create_term']:
            self.assertEqual(self.client.post(route, json={}).status_code, 403)
        self.fake.rows['members'][0]['role'] = 'member'
        for route in ['/api/admin/term_members/fall', '/api/admin/term_members/new_member', '/api/admin/term_members/create_term']:
            self.assertEqual(self.client.post(route, headers=self.headers, json={}).status_code, 403)
        self.client.get('/admin/term_members')
        self.assertFalse(any(call[0] in {'insert','update','delete'} for call in self.fake.calls))

    def test_invalid_rows_never_write(self):
        for entries in [None, [{'member_id':True}], [{'member_id':999, 'status':'active', 'entry_type':'new'}],
                        [{'member_id':2, 'status':'unknown', 'entry_type':'new'}]]:
            with self.assertRaises(ValueError): validate_entries(entries, {1,2,3})

    def test_report_shortfall_uses_semester_not_global_activity(self):
        page = self.client.get('/admin/term_attendance?term_id=fall').get_data(as_text=True)
        self.assertIn('data-active="yes" data-shortage="3" data-search="가을복귀', page)
        self.assertIn('data-active="no" data-shortage="3" data-search="봄만참석', page)

    def test_invalid_term_does_not_silently_show_another_term(self):
        self.assertEqual(self.client.get('/admin/term_members?term_id=missing').status_code, 404)

    def test_returning_member_topic_identity_uses_event_semester(self):
        self.fake.rows['members'][2].update(account_status='active', member_status='dormant')
        self.fake.rows['topic_events'] = [dict(id='topic',seminar_session_id='thu')]
        with self.module.app.test_request_context('/'):
            from flask import session
            session['user_id'] = 3
            self.assertEqual(self.module._authenticated_topic_member('topic')['id'], 3)
            self.fake.rows['seminar_term_members'][1]['status'] = 'paused'
            self.assertIsNone(self.module._authenticated_topic_member('topic'))

    def test_term_roster_blocks_unsafe_legacy_member_merge_before_writes(self):
        response = self.client.post('/api/admin/members/merge', json={'source_id':2, 'target_id':3})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(any(call[0] in {'insert','update','delete'} for call in self.fake.calls))

    def test_invalid_term_dates_are_rejected_before_inserting(self):
        for start,end in [('2026-12-01','2026-09-01'),('invalid','2026-09-01')]:
            response = self.client.post('/api/admin/term_members/create_term', headers=self.headers,
                                       json={'name':'2026-겨울학기','start_date':start,'end_date':end})
            self.assertEqual(response.status_code, 400)
        self.assertFalse(any(call[0]=='insert' for call in self.fake.calls))


if __name__ == '__main__': unittest.main()
