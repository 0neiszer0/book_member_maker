import importlib
import os
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from home_overview import date_label, member_seminar_summary, operations_summary
from testing._fake_supabase import FakeSupabase

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'home-test-only')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'home-test-only')


def fixture():
    return {
        'members': [
            {'id': 1, 'name': '테스트 회원', 'student_id': '202600001', 'department': '독서학과', 'role': 'member', 'is_active': True, 'account_status': 'active', 'member_status': 'active'},
            {'id': 2, 'name': '다른 회원 비공개', 'student_id': '202600002', 'role': 'admin', 'is_active': True, 'account_status': 'active', 'member_status': 'active'}],
        'seminar_terms': [{'id': 'term', 'name': '2026-2학기', 'start_date': '2026-09-01', 'end_date': '2026-12-31', 'is_active': True, 'attendance_minimum': 3, 'share_token': 'term-share'}],
        'seminar_weeks': [{'id': 'week', 'term_id': 'term', 'week_start': '2026-09-21', 'book_title': '마음'}],
        'seminar_sessions': [
            {'id': 'past', 'term_id': 'term', 'seminar_week_id': 'past-week', 'day_type': 'thu', 'meeting_date': '2026-09-17', 'book_title': '표류도', 'is_active': True},
            {'id': 'wed', 'term_id': 'term', 'seminar_week_id': 'week', 'day_type': 'thu', 'meeting_date': '2026-09-23', 'moderator_name': '테스트 사회자', 'is_active': True},
            {'id': 'mon', 'term_id': 'term', 'seminar_week_id': 'week', 'day_type': 'mon', 'meeting_date': '2026-09-28', 'moderator_name': '', 'is_active': True}],
        'topic_events': [{'id': 'event', 'seminar_week_id': 'week', 'meeting_date': '2026-09-23', 'is_active': True, 'share_token': 'share-test', 'created_at': '2026-09-01'}],
        'topic_submissions': [],
        'history': [{'id': 'history', 'seminar_session_id': 'past', 'date': '2026-09-17', 'book_title': '표류도', 'present': ['테스트 회원'], 'actual_member_ids': [1], 'attendance_confirmed_at': '2026-09-17T12:00:00Z'}],
    }


class OverviewDataTests(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase(fixture())
        self.today = date(2026, 9, 23)

    def test_actual_weekday_and_invalid_dates(self):
        self.assertEqual(date_label('2026-09-23'), '2026-09-23 (수)')
        self.assertEqual(date_label('2026-09-28'), '2026-09-28 (월)')
        self.assertEqual(date_label(None), '')
        self.assertEqual(date_label('not-a-date'), 'not-a-date')

    def test_member_summary_shared_submission_and_deadline(self):
        self.db.rows['topic_submissions'] = [{'id': 'own', 'event_id': 'event', 'member_id': None, 'student_id': '202600001'}]
        data = member_seminar_summary(self.db, 1, self.today)
        self.assertEqual(data['seminar']['id'], 'wed')
        self.assertEqual(data['seminar']['book_title'], '마음')
        self.assertTrue(data['submitted'])
        self.assertTrue(data['seminar']['topic']['open'])
        self.assertEqual(data['seminar']['topic']['deadline_label'], '2026-09-29 (화) 00:00')
        self.assertFalse(any(c[0] in {'insert', 'update', 'delete'} for c in self.db.calls))

    def test_other_members_submission_is_not_mine(self):
        self.db.rows['topic_submissions'] = [{'id': 'other', 'event_id': 'event', 'member_id': 2, 'student_id': '202600002'}]
        self.assertFalse(member_seminar_summary(self.db, 1, self.today)['submitted'])

    def test_empty_and_finished_term(self):
        self.assertIsNone(member_seminar_summary(FakeSupabase(), 1, self.today)['seminar'])
        self.assertIsNone(member_seminar_summary(self.db, 1, date(2026, 12, 31))['seminar'])

    def test_tasks_follow_selected_session_and_confirmed_legacy_record(self):
        data = operations_summary(self.db, session_id='wed', today=self.today)
        tasks = {t['key']: t['done'] for t in data['tasks']}
        self.assertTrue(tasks['moderator'])
        self.assertFalse(tasks['roster'])
        self.assertFalse(tasks['groups'])
        self.assertFalse(tasks['attendance'])
        self.assertEqual(data['pending_attendance'], [])
        data = operations_summary(self.db, session_id='mon', today=self.today)
        self.assertFalse(next(t for t in data['tasks'] if t['key'] == 'moderator')['done'])
        self.assertNotIn('attendance', [t['key'] for t in data['tasks']])

    def test_completed_tasks_and_pending_past(self):
        self.db.rows['seminar_sessions'][1].update(roster_updated_at='saved', attendance_confirmed_at='confirmed')
        self.db.rows['history'] = [{'id': 'new', 'seminar_session_id': 'wed', 'groups': [['테스트 회원']]}]
        data = operations_summary(self.db, today=self.today)
        self.assertTrue(all(t['done'] for t in data['tasks']))
        self.assertEqual([s['id'] for s in data['pending_attendance']], ['past'])

    def test_empty_groups_do_not_count_as_saved_and_any_confirmation_counts(self):
        self.db.rows['history'].extend([
            {'id': 'empty', 'seminar_session_id': 'wed', 'groups': [[]]},
            {'id': 'other-past', 'seminar_session_id': 'past', 'groups': []}])
        data = operations_summary(self.db, today=self.today)
        self.assertFalse(next(t for t in data['tasks'] if t['key'] == 'groups')['done'])
        self.assertEqual(data['pending_attendance'], [])


class OverviewRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')
        cls.module.app.config.update(TESTING=True, SECRET_KEY='home-test-only')

    def setUp(self):
        self.db = FakeSupabase(fixture())
        self.db_patch = patch.object(self.module, 'supabase', self.db)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.today_patch = patch.object(self.module, 'member_seminar_summary', side_effect=lambda db, mid: member_seminar_summary(db, mid, date(2026, 9, 23)))
        self.today_patch.start()
        self.addCleanup(self.today_patch.stop)
        clock_patch = patch('attendance_routes.datetime')
        clock_patch.start().now.return_value = datetime(2026, 9, 23, tzinfo=timezone.utc)
        self.addCleanup(clock_patch.stop)
        self.client = self.module.app.test_client()
        self.login(1, 'member')

    def login(self, mid, role):
        with self.client.session_transaction() as state:
            state.update(user_id=mid, user_role=role, user_name='테스트 회원')

    def test_member_home_only_contains_my_progress_and_no_other_identity(self):
        html = self.client.get('/').get_data(as_text=True)
        for expected in ('2026-09-23 (수)', '마음', '테스트 사회자', '발제문 작성', '1 / 3회'):
            self.assertIn(expected, html)
        self.assertNotIn('다른 회원 비공개', html)
        self.assertNotIn('202600002', html)
        self.assertNotIn('운영 개요 열기', html)

    def test_guest_home_exposes_public_tools_without_private_navigation(self):
        with self.client.session_transaction() as state:
            state.clear()
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for path in ('/club-room', '/now', '/books/suggestions', '/login'):
            self.assertIn('href="' + path + '"', html)
        for private_path in ('/admin/dashboard', '/mypage', '/seminars', '/applicant-result/'):
            self.assertNotIn('href="' + private_path, html)
        self.assertEqual(html.count('id="cr-home-status"'), 1)
        self.assertIn('aria-label="로그인 없이 이용하기"', html)
        self.assertIn('이름·학번', html)

    def test_guest_empty_participation_links_remain_public(self):
        from flask import render_template
        with self.module.app.test_request_context('/now'):
            html = render_template('engagement_now.html', cards=[], remembered_member=None)
        self.assertIn('href="/club-room"', html)
        self.assertIn('href="/books/suggestions"', html)
        self.assertNotIn('href="/seminars"', html)
        self.assertNotIn('href="/mypage"', html)

    def test_mobile_attendance_keeps_filter_rows_and_labeled_totals(self):
        self.login(2, 'admin')
        html = self.client.get('/admin/term_attendance?term_id=term').get_data(as_text=True)
        self.assertIn('attendance-table attendance-members', html)
        self.assertIn('data-member-row', html)
        self.assertIn('data-label="합계"', html)
        self.assertIn('data-label="부족"', html)
        self.assertIn('attendance-table attendance-sheet', html)

    def test_empty_charts_have_no_oversized_canvas(self):
        self.login(2, 'admin')
        html = self.client.get('/records/analytics').get_data(as_text=True)
        self.assertIn('아직 기록이 없어요.', html)
        self.assertNotIn('<canvas id="bbMonthlyChart"', html)
        self.assertNotIn('<canvas id="sgMonthlyChart"', html)

    def test_submitted_action_and_closed_event(self):
        self.db.rows['topic_submissions'] = [{'id': 'own', 'event_id': 'event', 'member_id': 1}]
        self.assertIn('제출한 발제문 수정', self.client.get('/').get_data(as_text=True))
        self.db.rows['topic_events'][0]['is_active'] = False
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('접수 마감', html)
        self.assertNotIn('제출한 발제문 수정', html)

    def test_member_home_partial_failure_is_not_zero_attendance(self):
        with patch.object(self.module, '_term_attendance_report', side_effect=RuntimeError('private-database-detail')):
            html = self.client.get('/').get_data(as_text=True)
        self.assertIn('참석 기록을 불러오지 못했어요', html)
        self.assertIn('마음', html)
        self.assertNotIn('0 / 3회', html)
        self.assertNotIn('private-database-detail', html)

    def test_seminar_failure_stays_on_page_with_retry(self):
        with patch.object(self.module, '_load_weekly_seminar_view', side_effect=RuntimeError('private-error')):
            response = self.client.get('/seminars?term_id=term')
        self.assertEqual(response.status_code, 503)
        html = response.get_data(as_text=True)
        self.assertIn('다시 시도', html)
        self.assertIn('/seminars?term_id=term', html)
        self.assertNotIn('private-error', html)
        self.assertIsNone(response.location)

    def test_dashboard_failure_hides_counts_and_keeps_retry(self):
        self.login(2, 'admin')
        with patch.object(self.module, 'operations_summary', side_effect=RuntimeError('private-error')):
            response = self.client.get('/admin/dashboard?term_id=term&session_id=wed')
        self.assertEqual(response.status_code, 503)
        html = response.get_data(as_text=True)
        self.assertIn('다시 시도', html)
        self.assertNotIn('overview-stat-date', html)
        self.assertNotIn('private-error', html)

    def test_staff_checklist_links_are_scoped_to_selected_session(self):
        self.login(2, 'admin')
        response = self.client.get('/admin/dashboard?term_id=term&session_id=wed')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('/admin/seminar_sessions/wed/roster', html)
        self.assertIn('/making_team?session_id=wed', html)
        self.assertIn('2026-09-23 (수)', html)
        self.assertNotIn('href="/admin/seminars" class="wd-menu-item"', html)

    def test_public_home_has_no_member_queries(self):
        with self.client.session_transaction() as state:
            state.clear()
        self.db.calls.clear()
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.db.calls, [])


if __name__ == '__main__':
    unittest.main()
