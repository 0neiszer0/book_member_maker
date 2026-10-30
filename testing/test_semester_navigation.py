import copy
import importlib
import unittest
from datetime import date

from lms_learning import historical_courses
from testing.test_lms_improvements import WriteDB
from testing.test_home_overview import fixture


class ArchiveTests(unittest.TestCase):
    def test_unassigned_winter_records_use_previous_academic_year(self):
        histories = [dict(id='jan', date='2026-01-05', book_title='책 A', actual_member_ids=[1], attendance_confirmed_at='yes'),
                     dict(id='feb', date='2026-02-09', book_title='책 B', actual_member_ids=[2], attendance_confirmed_at='yes')]
        result = historical_courses([dict(id=1, name='가'), dict(id=2, name='나')], histories, [], 1, date(2026,10,28))
        self.assertEqual(result[0]['key'], 'legacy-2025-겨울')
        self.assertEqual(result[0]['name'], '25-겨울학기')
        self.assertEqual([r['id'] for r in result[0]['records']], ['jan'])
        self.assertEqual(histories[0]['actual_member_ids'], [1])

    def test_explicit_session_relation_wins_over_overlapping_calendar_dates(self):
        terms = [dict(id='a', name='봄', start_date='2025-03-01', end_date='2025-06-30'),
                 dict(id='b', name='여름', start_date='2025-06-01', end_date='2025-08-31')]
        histories = [dict(id='h', date='2025-06-10', seminar_session_id='s', actual_member_ids=[1], attendance_confirmed_at='yes')]
        result = historical_courses([dict(id=1,name='가')], histories, terms, 1, date(2026,10,28), [dict(id='s',term_id='b')])
        self.assertEqual(result[0]['term_id'], 'b')
        result = historical_courses([dict(id=1,name='가')], histories, terms, 1, date(2026,10,28))
        self.assertIsNone(result[0]['term_id'], 'ambiguous dates must not select an arbitrary term')


class NavigationRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')
        cls.module.app.config['TESTING'] = True

    def setUp(self):
        rows = fixture()
        rows['history'] = [dict(id='own', date='2025-04-01', book_title='내가 읽은 책', actual_member_ids=[1], attendance_confirmed_at='yes'),
                           dict(id='other', date='2024-04-01', book_title='다른 사람의 책', actual_member_ids=[2], attendance_confirmed_at='yes')]
        self.db = WriteDB(rows)
        self.original = self.module.supabase
        self.module.supabase = self.db
        self.client = self.module.app.test_client()
        with self.client.session_transaction() as state:
            state.update(user_id=1, user_role='member')

    def tearDown(self):
        self.module.supabase = self.original

    def test_archive_owned_read_only_and_hidden_cards_still_open(self):
        self.db.rows['member_preferences'] = [dict(member_id=1,hidden_courses=['legacy-2025-1'])]
        before = copy.deepcopy(self.db.rows)
        result = self.client.get('/api/my/courses').get_json()['courses']
        self.assertTrue(result[0]['hidden'])
        self.assertNotIn('records', result[0])
        page = self.client.get('/my/seminars/archive/legacy-2025-1')
        self.assertEqual(page.status_code, 200)
        text = page.get_data(as_text=True)
        self.assertIn('내가 읽은 책', text)
        self.assertNotIn('다른 사람의 책', text)
        self.assertNotIn('actual_member_ids', text)
        self.assertEqual(self.client.get('/my/seminars/archive/legacy-2024-1').status_code, 404)
        self.assertEqual(before, self.db.rows)

    def test_archive_login_and_live_role_checks(self):
        with self.client.session_transaction() as state:
            state.clear()
        self.assertEqual(self.client.get('/my/seminars/archive/legacy-2025-1').status_code, 302)
        with self.client.session_transaction() as state:
            state.update(user_id=1,user_role='member')
        self.db.rows['members'][0]['account_status'] = 'pending'
        self.assertEqual(self.client.get('/my/seminars/archive/legacy-2025-1').status_code, 302)

    def test_scoped_members_use_classroom_navigation_and_global_member_tools_stay_global(self):
        self.db.rows['members'][0].update(role='officer',is_active=True)
        page = self.client.get('/admin/term_members?term_id=term')
        self.assertEqual(page.status_code, 200)
        text = page.get_data(as_text=True)
        self.assertIn('학기 강의실 메뉴', text)
        self.assertIn('/admin/term_members?term_id=term', text)
        self.assertNotIn('id="new-term"', text)
        self.assertIn('href="/admin/dashboard"', text)
        global_page = self.client.get('/admin/term_members').get_data(as_text=True)
        self.assertIn('전체 운영 메뉴', global_page)
        self.assertIn('id="new-term"', global_page)
        self.db.rows['members'][0]['role'] = 'member'
        self.assertEqual(self.client.get('/admin/term_members?term_id=term').status_code, 302)

    def test_social_preview_has_knu_banner_and_club_title(self):
        with self.client.session_transaction() as state:
            state.clear()
        page = self.client.get('/').get_data(as_text=True)
        self.assertIn('content="책반우|경북대학교 중앙독서동아리"', page)
        self.assertIn('content="책 먹는 호반우 홈페이지"', page)
        self.assertIn('content="KNU 책반우"', page)
        self.assertIn('content="1774"', page)


if __name__ == '__main__':
    unittest.main()
