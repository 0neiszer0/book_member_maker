"""Canvas-style admin navigation: every menu click stays in its own context and highlights itself."""
import importlib.util
import os
import re
import sys
import unittest
from html import unescape
from pathlib import Path
from unittest.mock import patch

from testing._fake_supabase import FakeSupabase
from testing.test_home_overview import fixture

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'admin-nav-simplify')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'admin-nav-simplify')

MENU = re.compile(r'<nav class="lms-classroom-nav" aria-label="([^"]+)">(.*?)</nav>', re.S)
LINK = re.compile(r'<a href="([^"]+)"([^>]*)>([^<]+)</a>')


def course_menu(html):
    found = MENU.search(html)
    assert found, 'course menu missing'
    links = [(unescape(href), 'aria-current="page"' in attrs, label.strip()) for href, attrs, label in LINK.findall(found.group(2))]
    return found.group(1), links


class AdminNavigationSimplifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeSupabase()
        spec = importlib.util.spec_from_file_location('_admin_nav_simplify_app', Path(__file__).parents[1] / 'app.py')
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        with patch('supabase.create_client', return_value=cls.fake):
            spec.loader.exec_module(cls.module)

    def setUp(self):
        rows = fixture()
        rows['boards'] = [dict(id='board', name='공지사항', slug='notices', board_type='general', read_role='member', write_role='officer', allow_comments=True, is_active=True)]
        self.fake.rows = rows
        self.module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = self.module.app.test_client()

    def login(self, role):
        if role == 'officer':
            self.fake.rows['members'][0]['role'] = 'officer'
        with self.client.session_transaction() as state:
            state.clear()
            state.update(user_id=2 if role == 'admin' else 1, user_role=role, user_name='테스트')

    def page(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, path)
        return response.get_data(as_text=True)

    def test_global_menu_items_stay_in_global_context_and_highlight(self):
        self.login('admin')
        label, links = course_menu(self.page('/admin/dashboard'))
        self.assertEqual(label, '전체 운영 메뉴')
        self.assertLessEqual(len(links), 12)
        for href, _, text in links:
            with self.subTest(item=text):
                menu, landed = course_menu(self.page(href))
                self.assertEqual(menu, '전체 운영 메뉴', f'{text} must not jump into another menu')
                self.assertEqual([t for _, current, t in landed if current], [text])

    def test_term_menu_items_stay_in_term_context_and_highlight(self):
        self.login('admin')
        label, links = course_menu(self.page('/admin/seminars?term_id=term'))
        self.assertEqual(label, '학기 강의실 메뉴')
        for href, _, text in links:
            with self.subTest(item=text):
                menu, landed = course_menu(self.page(href))
                self.assertEqual(menu, '학기 강의실 메뉴', f'{text} must stay inside the term')
                self.assertIn(text, [t for _, current, t in landed if current])

    def test_term_settings_are_tabs_and_old_urls_still_work(self):
        self.login('admin')
        for path in ('/admin/term_members?term_id=term', '/operations/terms/term/officers', '/operations/terms/term/rules'):
            with self.subTest(path=path):
                html = self.page(path)
                self.assertIn('class="lms-settings-tabs"', html)
                for tab in ('회원 명단', '임원·부원', '반복 업무·알림'):
                    self.assertIn(f'>{tab}</a>', html)
                _, links = course_menu(html)
                self.assertIn('학기 설정', [t for _, current, t in links if current])

    def test_global_settings_are_tabs(self):
        self.login('admin')
        for path in ('/operations/settings', '/admin/boards'):
            with self.subTest(path=path):
                html = self.page(path)
                self.assertIn('class="lms-settings-tabs"', html)
                self.assertIn('>직책·기본 업무</a>', html)
                _, links = course_menu(html)
                self.assertEqual([t for _, current, t in links if current], ['전체 설정'])

    def test_global_term_list_does_not_embed_a_term_roster_editor(self):
        self.login('admin')
        html = self.page('/admin/term_members')
        self.assertIn('class="lms-term-list"', html)
        self.assertIn('id="new-term"', html)
        self.assertNotIn('id="save-term-members"', html)
        self.assertIn('id="save-term-members"', self.page('/admin/term_members?term_id=term'))

    def test_member_sees_no_operations_group(self):
        self.login('member')
        html = self.page('/seminars?term_id=term')
        self.assertNotIn('학기 운영</p>', html)
        _, links = course_menu(html)
        texts = [t for _, _, t in links]
        self.assertIn('맡은 업무', texts)
        for staff_only in ('세미나 운영', '도서·일정·사회자', '발제문 관리', '출석·조 편성', '학기 설정', '학기 참석 현황'):
            self.assertNotIn(staff_only, texts)

    def test_officer_settings_links_follow_capabilities(self):
        self.login('officer')
        _, links = course_menu(self.page('/seminars?term_id=term'))
        texts = [t for _, _, t in links]
        self.assertIn('세미나 운영', texts)
        for removed in ('도서·일정·사회자', '발제문 관리', '출석·조 편성'):
            self.assertNotIn(removed, texts)
        self.assertNotIn('>전체 설정</a>', self.page('/admin/dashboard'), 'global settings stay primary-admin only')
        self.assertEqual(self.client.get('/operations/settings').status_code, 403)

    def test_seminar_subpages_highlight_consolidated_seminar_operations_link(self):
        self.login('admin')
        for path in (
            '/admin/seminars?term_id=term',
            '/admin/seminars?term_id=term&section=topics',
            '/admin/seminars?term_id=term&section=attendance',
            '/admin/topics/event/view',
            '/admin/seminar_sessions/wed/roster',
        ):
            with self.subTest(path=path):
                menu, landed = course_menu(self.page(path))
                self.assertEqual(menu, '학기 강의실 메뉴')
                self.assertIn('세미나 운영', [t for _, current, t in landed if current])


if __name__ == '__main__':
    unittest.main()
