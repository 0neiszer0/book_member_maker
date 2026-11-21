import os
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
from testing._fake_supabase import FakeSupabase

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'records-ui-test')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'records-ui-test')


class RecordsUIRefreshTest(unittest.TestCase):
    def setUp(self):
        import app

        self.db = FakeSupabase({
            'members': [{'id': 1, 'name': '운영', 'role': 'admin', 'is_active': True,
                         'member_status': 'active', 'account_status': 'active'}],
            'history': [{'id': 'h1', 'date': '2026-01-10', 'book_title': '겨울',
                         'groups': [['운영']], 'present': ['운영'], 'facilitators': [],
                         'attendance_confirmed_at': '2026-01-10', 'actual_member_ids': [1]}],
            'brick_book_sessions': [{'meeting_date': '2026-01-10'}],
            'study_group_sessions': [{'meeting_date': '2026-01-10'}],
        })
        db_patch = patch.object(app, 'supabase', self.db)
        db_patch.start()
        self.addCleanup(db_patch.stop)
        self.client = app.app.test_client()

    def login(self, role):
        self.db.rows['members'][0]['role'] = role
        with self.client.session_transaction() as state:
            state.update(user_id=1, user_role=role, user_name='운영')

    def page(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return BeautifulSoup(response.data, 'html.parser')

    def test_staff_records_screens(self):
        # Populated data exercises conditional charts, edit buttons and manual attendance.
        screens = [
            ('/records', '기록·통계', '개요', '.records-stats .records-directory'),
            ('/records/seminars', '세미나 진행 현황', '세미나',
             '#termFilter #seminarSearch #seminarEditDialog #seminarEditForm #editHistoryId '
             '#editDate #editBookTitle #editGroupDetail details[open] .edit-seminar'),
            ('/records/analytics', '활동 통계', '통계',
             '#termFilter #rebuild-matrix #genreChart #monthlyChart #bbMonthlyChart #sgMonthlyChart '
             '.attendance-scroll .attendance-present .records-ranking-track script[src*="chart.js"]'),
            ('/records/brick_books', '벽돌책 기록', '벽돌책', '#termFilter #newBookModal #newBookForm'),
            ('/records/study_groups', '소모임 기록', '소모임', '#termFilter #newGroupModal #newGroupForm'),
            ('/records/seminars/h1', '세미나 기록 편집', '세미나',
             '#groupsContainer #save-groups #capture-groups #delete-history #record-image-modal '
             '#confirm-attendance #record-editor-data script[src*="group_editor.js"] '
             'script[src*="group_drag.js"] script[src*="html2canvas"]'),
        ]
        for role in ('officer', 'admin'):
            self.login(role)
            for path, heading, tab, selectors in screens:
                with self.subTest(role=role, path=path):
                    page = self.page(path)
                    self.assertNotIn('기록 시스템', page.get_text())
                    self.assertEqual(page.select_one('.records-header h1').get_text(), heading)
                    self.assertEqual(page.select_one('.records-subbar [aria-current]').get_text(), tab)
                    for selector in selectors.split():
                        self.assertIsNotNone(page.select_one(selector), selector)

    def test_member_management_keeps_shared_styles_and_controls(self):
        self.login('admin')
        page = self.page('/admin/members')
        self.assertIsNotNone(page.select_one('.records-panel#login-admin'))
        self.assertIsNotNone(page.select_one('#member-add'))
        css = self.client.get(page.select_one('link[href*="lms_records.css"]')['href'])
        self.assertEqual(css.status_code, 200)
        for selector in ('.records-panel', '.records-field', '.status-control', '.records-overflow-x-auto'):
            self.assertIn(selector, css.get_data(as_text=True))
        css.close()
