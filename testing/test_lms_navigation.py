"""Exercise linked routes with isolated data, including attendance and staff tools."""
import importlib.util
import sys
from pathlib import Path
import os
import unittest
from unittest.mock import patch

from testing._fake_supabase import FakeSupabase
from testing.test_home_overview import fixture

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

    def test_guest_login_and_room_keep_lms_shell(self):
        self.assert_lms_response('/login')
        self.assert_lms_response('/club-room')
        self.assertIn('/login', self.client.get('/my/term_attendance').location)


if __name__ == '__main__':
    unittest.main()
