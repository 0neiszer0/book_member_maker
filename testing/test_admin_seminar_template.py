import unittest
from pathlib import Path


class AdminSeminarTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (Path(__file__).parents[1] / 'templates' / 'admin_seminars.html') \
            .read_text(encoding='utf-8')

    def test_topic_actions_do_not_stretch_to_card_height(self):
        self.assertIn('flex flex-wrap items-start justify-between', self.source)
        self.assertIn('flex items-center self-start gap-2 flex-wrap', self.source)
        css = (Path(__file__).parents[1] / 'static' / 'lms_operations.css').read_text(encoding='utf-8')
        self.assertRegex(css, r'\.lms-operations :is\(\.chip[^)]*\)\{display:inline-flex;flex:none;')

    def test_both_cards_use_attendance_lists(self):
        self.assertIn('for m in thu.attendees', self.source)
        self.assertIn('for m in mon.attendees', self.source)
        self.assertEqual(self.source.count('카카오톡 참석 명단 반영·출석 확정'), 2)
        self.assertNotIn('absence-picker', self.source)

    def test_no_show_picker_is_available_on_each_session(self):
        self.assertIn('macro no_show_panel(seminar_session)', self.source)
        self.assertIn('미연락 불참', self.source)
        self.assertIn('/no_shows', self.source)
        self.assertIn('{{ no_show_panel(thu) }}', self.source)
        self.assertIn('{{ no_show_panel(mon) }}', self.source)

    def test_review_management_is_rendered_inside_each_session(self):
        self.assertIn('macro review_panel(seminar_session)', self.source)
        self.assertIn('{{ review_panel(mon) }}', self.source)
        self.assertIn('{{ review_panel(thu) }}', self.source)
        self.assertNotIn('id="seminar-reviews"', self.source)

    def test_wave32_css_hierarchy_and_layout_fixes(self):
        ops_css = (Path(__file__).parents[1] / 'static' / 'lms_operations.css').read_text(encoding='utf-8')
        att_css = (Path(__file__).parents[1] / 'static' / 'lms_attendance.css').read_text(encoding='utf-8')
        self.assertIn('.lms-operations .op-btn-primary{background:#a6192e', ops_css)
        self.assertIn('button[data-focus-session],.lms-operations .op-inline-edit-btn{min-height:28px;min-width:auto;padding:3px 10px;font-size:0.82rem', ops_css)
        self.assertIn('.op-status-pill{border-radius:999px;padding:4px 12px;white-space:nowrap', ops_css)
        self.assertIn('.op-review-photo{max-height:160px;border-radius:8px;object-fit:cover;margin-top:8px', ops_css)
        self.assertIn('.ops-session-tools-2col{grid-template-columns:minmax(280px,310px) minmax(0,1fr)}', ops_css)
        self.assertIn('.attendance-actions{display:flex;flex-wrap:wrap;align-items:center;gap:10px', att_css)
        self.assertIn('.attendance-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))', att_css)
        self.assertIn('.attendance-kpi-card{', att_css)


class Wave32OperationsUiRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        import os
        import sys
        from unittest.mock import patch
        from testing._fake_supabase import FakeSupabase

        os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
        os.environ.setdefault('FLASK_SECRET_KEY', 'wave32-ops-render-test')
        os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
        os.environ.setdefault('SUPABASE_SERVICE_KEY', 'wave32-ops-render-test')

        cls.fake = FakeSupabase()
        spec = importlib.util.spec_from_file_location(
            '_wave32_ops_render_app', Path(__file__).parents[1] / 'app.py'
        )
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        with patch('supabase.create_client', return_value=cls.fake):
            spec.loader.exec_module(cls.module)

    def setUp(self):
        self.fake.rows = {
            'members': [
                {'id': 1, 'name': '홍윤서', 'role': 'admin', 'is_active': True, 'member_status': 'active', 'account_status': 'active', 'student_id': '202600001', 'department': '국문과', 'recruiting_class': 28},
                {'id': 2, 'name': '김세미나', 'role': 'member', 'is_active': True, 'member_status': 'active', 'account_status': 'active', 'student_id': '202600002', 'department': '철학과', 'recruiting_class': 29},
                {'id': 3, 'name': '이미달', 'role': 'member', 'is_active': True, 'member_status': 'active', 'account_status': 'active', 'student_id': '202600003', 'department': '사학과', 'recruiting_class': 29},
            ],
            'seminar_terms': [
                {'id': 'term-1', 'name': '2026-2학기', 'start_date': '2026-09-01', 'end_date': '2026-12-20', 'is_active': True, 'min_attendance': 5, 'share_token': 'st1'},
            ],
            'seminar_weeks': [
                {'id': 'w-normal', 'term_id': 'term-1', 'week_start': '2099-11-16', 'book_title': '정상 주차 도서', 'book_author': '저자A', 'note': '안내'},
                {'id': 'w-extra', 'term_id': 'term-1', 'week_start': '2099-11-23', 'book_title': '추가운영 주차 도서', 'book_author': '저자B', 'note': ''},
            ],
            'seminar_sessions': [
                {'id': 's-thu-1', 'term_id': 'term-1', 'seminar_week_id': 'w-normal', 'day_type': 'thu', 'meeting_date': '2099-11-19', 'is_active': True, 'moderator_name': '홍윤서', 'planned_member_ids': [1, 2], 'actual_member_ids': [1, 2], 'attendance_confirmed_at': '2099-11-19T12:00:00Z'},
                {'id': 's-mon-1', 'term_id': 'term-1', 'seminar_week_id': 'w-normal', 'day_type': 'mon', 'meeting_date': '2099-11-23', 'is_active': False, 'planned_member_ids': []},
                {'id': 's-thu-2', 'term_id': 'term-1', 'seminar_week_id': 'w-extra', 'day_type': 'thu', 'meeting_date': '2099-11-26', 'is_active': True, 'planned_member_ids': [1]},
                {'id': 's-mon-2', 'term_id': 'term-1', 'seminar_week_id': 'w-extra', 'day_type': 'mon', 'meeting_date': '2099-11-30', 'is_active': True, 'planned_member_ids': [2]},
            ],
            'topic_events': [
                {'id': 'te-1', 'seminar_week_id': 'w-normal', 'share_token': 'tok1', 'is_active': True, 'meeting_date': '2099-11-19', 'late_until': None},
                {'id': 'te-2', 'seminar_week_id': 'w-extra', 'share_token': 'tok2', 'is_active': True, 'meeting_date': '2099-11-26', 'late_until': '2099-11-28T14:59:59+00:00'},
            ],
            'topic_submissions': [],
            'history': [],
            'seminar_review_forms': [
                {'id': 'rf-1', 'seminar_session_id': 's-thu-1', 'status': 'open', 'share_token': 'rev1'},
            ],
            'seminar_reviews': [
                {
                    'id': 'rs-1', 'form_id': 'rf-1', 'member_id': 2,
                    'author_name': None,
                    'memorable_point': '인상 깊은 문장',
                    'image_url': 'https://example.test/review.jpg',
                    'deleted_at': None,
                    'created_at': '2099-11-20T09:00:00Z',
                },
            ],
            'seminar_votes': [],
            'seminar_absences': [],
            'seminar_no_shows': [],
            'seminar_term_members': [],
            'brick_books': [],
            'brick_book_sessions': [],
            'brick_session_members': [],
            'special_events': [],
            'special_event_attendees': [],
        }
        self.module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = self.module.app.test_client()
        with self.client.session_transaction() as s:
            s.update(user_id=1, user_role='admin', user_name='홍윤서')

    def test_admin_seminars_layout_extend_menu_and_review_photo(self):
        from bs4 import BeautifulSoup
        resp = self.client.get('/admin/seminars?term_id=term-1')
        self.assertEqual(resp.status_code, 200)
        dom = BeautifulSoup(resp.data, 'html.parser')

        # In-page view bar & section links
        tabs = [a.get_text(strip=True) for a in dom.select('.op-view-bar .op-view-tab')]
        self.assertEqual(tabs, ['전체', '발제문', '출석·조 편성'])
        self.assertIsNotNone(dom.select_one('.op-view-bar [data-open-schedule-tool]'))

        # Normal week (mon inactive) -> spacious 2-col layout + subtle note, no empty 3rd column card
        w_normal = dom.select_one('#week-w-normal')
        self.assertIsNotNone(w_normal.select_one('.ops-session-tools-2col'))
        self.assertIsNone(w_normal.select_one('.ops-session-tools-3col'))
        self.assertIsNotNone(w_normal.select_one('.op-mon-inactive-note .enable-additional'))
        self.assertEqual(len(w_normal.select('.op-session-card')), 1)
        self.assertNotIn('추가 세미나를 운영하지 않는 주차입니다.', str(w_normal))

        # Extra week (mon active) -> 3-col layout with both sessions
        w_extra = dom.select_one('#week-w-extra')
        self.assertIsNotNone(w_extra.select_one('.ops-session-tools-3col'))
        self.assertIsNone(w_extra.select_one('.op-mon-inactive-note'))
        self.assertEqual(len(w_extra.select('.op-session-card')), 2)

        # Collapsible extend menu: collapsed when no late window, open when late window active
        ext_normal = w_normal.select_one('details.op-extend-menu')
        ext_extra = w_extra.select_one('details.op-extend-menu')
        self.assertIsNotNone(ext_normal)
        self.assertFalse(ext_normal.has_attr('open'))
        self.assertIsNotNone(ext_extra)
        self.assertTrue(ext_extra.has_attr('open'))

        # Review panel author fallback & image thumbnail
        review = w_normal.select_one('.review-entry')
        self.assertIsNotNone(review)
        self.assertIn('김세미나', review.get_text())
        photo = review.select_one('a.op-review-photo-link img.op-review-photo')
        self.assertIsNotNone(photo)
        self.assertEqual(photo.get('src'), 'https://example.test/review.jpg')

        # Backward-compatible ?section=topics / attendance
        for section in ('topics', 'attendance'):
            sec_resp = self.client.get(f'/admin/seminars?term_id=term-1&section={section}')
            self.assertEqual(sec_resp.status_code, 200)
            sec_dom = BeautifulSoup(sec_resp.data, 'html.parser')
            self.assertEqual(sec_dom.select_one('.lms-operation-view').get('data-operation-view'), section)

    def test_admin_term_attendance_kpi_cards_and_compact_actions(self):
        from bs4 import BeautifulSoup
        resp = self.client.get('/admin/term_attendance?term_id=term-1')
        self.assertEqual(resp.status_code, 200)
        dom = BeautifulSoup(resp.data, 'html.parser')

        self.assertIsNotNone(dom.select_one('.attendance-actions .attendance-min-field input#minimum.compact-field'))
        self.assertIsNotNone(dom.select_one('.attendance-actions #save-minimum'))
        self.assertIsNotNone(dom.select_one('.attendance-actions #copy-notice'))

        kpis = dom.select('.attendance-summary .attendance-kpi-card')
        self.assertEqual(len(kpis), 3)
        labels = [card.select_one('.attendance-kpi-label').get_text(strip=True) for card in kpis]
        self.assertEqual(labels, ['학기 활동 회원', '기준 충족', '기준 미달'])
        self.assertIsNotNone(dom.select_one('.attendance-kpi-card.attendance-kpi-met'))
        self.assertIsNotNone(dom.select_one('.attendance-kpi-card.attendance-kpi-below'))

        # Ensure admin_term_members still renders cleanly alongside lms_attendance.css
        members_resp = self.client.get('/admin/term_members?term_id=term-1')
        self.assertEqual(members_resp.status_code, 200)


if __name__ == '__main__':
    unittest.main()
