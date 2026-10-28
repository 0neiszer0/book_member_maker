"""Exercise linked routes with isolated data, including attendance and staff tools."""
import importlib.util
import sys
from pathlib import Path
import os
import re
from datetime import date
import unittest
from unittest.mock import patch

from testing._fake_supabase import FakeSupabase
from testing.test_home_overview import fixture
from home_overview import operations_summary

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'lms-navigation-only')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'lms-navigation-only')


class LmsNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeSupabase()
        spec = importlib.util.spec_from_file_location('_lms_navigation_app', Path(__file__).parents[1] / 'app.py')
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        with patch('supabase.create_client', return_value=cls.fake):
            spec.loader.exec_module(cls.module)

    def setUp(self):
        rows = fixture()
        rows['members'][0].update(gender='F', email='member@example.test')
        rows['members'][1].update(gender='M', email='admin@example.test')
        rows['history'][0].update(groups=[['테스트 회원']], facilitators=['테스트 회원'])
        rows['boards'] = [dict(id='board', name='공지사항', slug='notices', board_type='general', read_role='member', write_role='officer', allow_comments=True, is_active=True)]
        rows['posts'] = [dict(id='post', board_id='board', title='테스트 공지', content='테스트 본문', author_id=2, created_at='2026-10-27T00:00:00Z', deleted_at=None)]
        self.fake.rows = rows
        self.fake.calls.clear()
        self.module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = self.module.app.test_client()

    def login(self, role):
        with self.client.session_transaction() as session:
            session.clear()
            session.update(user_id=2 if role == 'admin' else 1, user_role=role, user_name='테스트 회원')

    def assert_lms_response(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, path)
        html = response.get_data(as_text=True)
        self.assertIn('name="app-layout" content="canvas"', html, path)
        self.assertEqual(html.count('id="lms-global"'), 1, path)
        self.assertEqual(html.count('id="lms-content"'), 1, path)
        for legacy in ('/static/theme.css', '/static/tailwind.css', '/static/attendance.css', '/static/club_room.css', 'data-critical-theme="wood"', 'wd-topbar', 'class="wd-admin-sidebar"'):
            self.assertNotIn(legacy, html, path)
        return html

    def test_member_navigation_destinations_keep_lms_shell(self):
        self.login('member')
        for path in ('/', '/seminars?term_id=term', '/seminars?term_id=term&section=resources', '/my/term_attendance?term_id=term', '/mypage', '/profiles', '/profile/1', '/help/member', '/club-room', '/calendar', '/now', '/books/suggestions', '/books/suggest', '/boards', '/board/notices', '/board/notices/post', '/seminar_vote'):
            with self.subTest(path=path):
                self.assert_lms_response(path)

    def test_staff_navigation_destinations_keep_lms_shell(self):
        self.login('admin')
        for path in ('/admin/dashboard', '/admin/seminars?term_id=term', '/admin/seminar_sessions/wed/roster', '/admin/term_attendance?term_id=term', '/admin/term_members?term_id=term', '/admin/attendance_matrix', '/admin/topics/event/view', '/admin/topics/event/document_setup', '/admin/special_events', '/admin/seminar_rooms', '/making_team', '/manual_entry', '/admin/members', '/records', '/records/members/1', '/records/seminars', '/records/seminars/history', '/records/brick_books', '/records/study_groups', '/records/analytics', '/admin/boards', '/admin/recruitment-results', '/admin/engagement', '/admin/bug-reports', '/help/admin'):
            with self.subTest(path=path):
                self.assert_lms_response(path)

    def test_member_attendance_remains_personal_and_confirmed(self):
        self.login('member')
        html = self.assert_lms_response('/my/term_attendance?term_id=term')
        self.assertIn('2026-09-17', html)
        self.assertIn('확정 출석', html)
        self.assertNotIn('다른 회원 비공개', html)
        self.assertIn('name="term_id"', html)
        self.assertIn('aria-current="page">내 출석', html)
        self.assertFalse(any(c[0] in {'insert', 'update', 'delete', 'upsert', 'rpc'} for c in self.fake.calls))

    def test_member_cannot_open_staff_attendance(self):
        self.login('member')
        response = self.client.get('/admin/term_attendance?term_id=term')
        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn('다른 회원 비공개', response.get_data(as_text=True))

    def test_selected_term_survives_staff_navigation_and_session_pages(self):
        self.login('admin')
        self.fake.rows['seminar_terms'].append(dict(id='archive', name='2025-2학기', start_date='2025-09-01', end_date='2025-12-31', is_active=False, share_token='archive-test'))
        self.fake.rows['seminar_weeks'].append(dict(id='archive-week', term_id='archive', week_start='2025-10-20', book_title='지난 학기 도서'))
        self.fake.rows['seminar_sessions'].append(dict(id='archive-session', term_id='archive', seminar_week_id='archive-week', day_type='thu', meeting_date='2025-10-23'))
        for source in ('/admin/term_attendance?term_id=archive', '/admin/seminars?term_id=archive', '/admin/term_members?term_id=archive', '/admin/dashboard?term_id=archive', '/admin/seminar_sessions/archive-session/roster', '/admin/seminar_sessions/archive-session/moderator'):
            html = self.client.get(source).get_data(as_text=True)
            nav = re.search(r'<nav class="lms-classroom-nav".*?</nav>', html, re.S).group()
            for destination in ('seminars', 'term_members', 'term_attendance'):
                with self.subTest(source=source, destination=destination):
                    href = '/admin/' + destination + '?term_id=archive'
                    self.assertIn('href="' + href + '"', nav)
                    response = self.client.get(href)
                    self.assertEqual(response.status_code, 200)
                    self.assertRegex(response.get_data(as_text=True), r'<option[^>]*value="archive"[^>]*selected')
            self.assertNotIn('/making_team?term_id=', nav)
        with self.client.session_transaction() as state:
            csrf = state['topic_moderator_csrf']
        saved = self.client.post('/admin/seminar_sessions/archive-session/moderator',
                                 data={'moderator_name': '지난 학기 사회자', 'csrf_token': csrf})
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(saved.location, '/admin/seminars?term_id=archive')

    def test_legacy_confirmation_agrees_across_staff_views(self):
        self.login('admin')
        self.fake.rows['seminar_weeks'] = [dict(id='past-week', term_id='term', week_start='2026-09-14', book_title='확정 기록 도서')]
        self.fake.rows['seminar_sessions'] = [dict(id='past', term_id='term', seminar_week_id='past-week', meeting_date='2026-09-17', day_type='thu', planned_member_ids=[2], actual_member_ids=[2])]
        self.fake.rows['topic_events'] = []
        seminars = self.client.get('/admin/seminars?term_id=term').get_data(as_text=True)
        roster = self.client.get('/admin/seminar_sessions/past/roster').get_data(as_text=True)
        report = self.client.get('/admin/term_attendance?term_id=term').get_data(as_text=True)
        overview = operations_summary(self.fake, term_id='term', session_id='past', today=date(2026, 10, 28))
        self.assertIn('실제 출석 확정됨', seminars)
        self.assertNotIn('실제 출석 미확정', seminars)
        self.assertIn('출석 확정됨 · 다시 저장하면', roster)
        self.assertRegex(roster, r'class="actual-choice"[^>]*value="1"[^>]*checked')
        self.assertNotRegex(roster, r'class="actual-choice"[^>]*value="2"[^>]*checked')
        self.assertNotIn('/admin/seminar_sessions/past/roster', report)
        self.assertTrue(next(t['done'] for t in overview['tasks'] if t['key'] == 'attendance'))
        self.assertEqual(overview['pending_attendance'], [])

    def test_member_activity_links_follow_existing_server_permission(self):
        self.login('admin')
        html = self.client.get('/admin/members').get_data(as_text=True)
        self.assertIn('href="/records/members/1"', html)
        self.assertIn('href="/records/members/2"', html)
        self.fake.rows['members'][1]['role'] = 'officer'
        with self.client.session_transaction() as state:
            state.update(user_id=2, user_role='officer')
        html = self.client.get('/admin/members').get_data(as_text=True)
        self.assertNotIn('href="/records/members/1"', html)
        self.assertIn('href="/records/members/2"', html)
        self.assertEqual(self.client.get('/records/members/1').status_code, 302)
        self.assertEqual(self.client.get('/records/members/2').status_code, 200)

    def test_attendance_grid_keeps_session_rows_and_weekly_credit(self):
        self.login('member')
        self.fake.rows['history'] = []
        self.fake.rows['seminar_sessions'] = [
            dict(id='thu', term_id='term', seminar_week_id='week', meeting_date='2026-09-24', day_type='thu', actual_member_ids=[1], attendance_confirmed_at='2026-09-24T12:00:00Z'),
            dict(id='mon', term_id='term', seminar_week_id='week', meeting_date='2026-09-28', day_type='mon', actual_member_ids=[1], attendance_confirmed_at='2026-09-28T12:00:00Z'),
            dict(id='planned', term_id='term', seminar_week_id='week', meeting_date='2026-09-25', day_type='thu', planned_member_ids=[1])]
        html = self.client.get('/my/term_attendance?term_id=term').get_data(as_text=True)
        self.assertIn('<strong>1/3회</strong>', html)
        self.assertIn('data-session-id="thu"', html)
        self.assertIn('data-session-id="mon"', html)
        self.assertNotIn('data-session-id="planned"', html)
        self.assertIn('rowspan="2"', html)
        self.assertIn('href="/seminars?term_id=term#week-week"', html)
        self.assertEqual(html.count('data-attendance-key='), 2)
        self.assertNotIn('다른 회원 비공개', html)

    def test_guest_login_and_room_keep_lms_shell(self):
        self.assert_lms_response('/login')
        self.assert_lms_response('/club-room')
        self.assertIn('/login', self.client.get('/my/term_attendance').location)


if __name__ == '__main__':
    unittest.main()
