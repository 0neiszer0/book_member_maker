import importlib
import os
import unittest
from copy import deepcopy
from unittest.mock import patch

from testing._fake_supabase import FakeSupabase

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'schedule-test')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'schedule-test')


class SeminarScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')
        cls.module.app.config.update(TESTING=True, SECRET_KEY='schedule-test')

    def setUp(self):
        self.fake = FakeSupabase({
            'members': [{'id': 1, 'name': '운영자', 'role': 'admin', 'is_active': True,
                         'member_status': 'active', 'account_status': 'active'}],
            'seminar_weeks': [{'id': 'w', 'book_title': '원래 책', 'note': '기존 안내'}],
            'seminar_sessions': [
                {'id': 'thu', 'seminar_week_id': 'w', 'meeting_date': '2026-09-03', 'moderator_name': '목사회자', 'actual_member_ids': [1]},
                {'id': 'mon', 'seminar_week_id': 'w', 'meeting_date': '2026-09-07', 'moderator_name': '월사회자'},
                {'id': 'other', 'seminar_week_id': 'other-week', 'meeting_date': '2026-09-10', 'moderator_name': '다른 사회자'},
            ],
            'topic_events': [{'id': 'event', 'seminar_week_id': 'w', 'book_title': '원래 책'}],
            'history': [{'id': 'h', 'seminar_session_id': 'thu', 'book_title': '원래 책', 'groups': [['가', '나']]}],
        })
        self.patch = patch.object(self.module, 'supabase', self.fake)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = self.module.app.test_client()
        with self.client.session_transaction() as session:
            session.update(user_id=1, user_role='admin', topic_moderator_csrf='test-csrf')
        self.payload = {'book_title': '새 책', 'book_author': '저자', 'note': '안내',
                        'moderators': [{'id': 'thu', 'moderator_name': '새 목사회자'},
                                       {'id': 'mon', 'moderator_name': '새 월사회자'}]}

    def save(self, payload=None, token='test-csrf'):
        return self.client.patch('/api/admin/seminar_weeks/w', json=payload if payload is not None else self.payload,
                                 headers={'X-Schedule-CSRF': token})

    def test_books_sync_and_moderators_are_separate_without_attendance_changes(self):
        self.assertEqual(self.save().status_code, 200)
        self.assertEqual(self.fake.rows['seminar_sessions'][0]['moderator_name'], '새 목사회자')
        self.assertEqual(self.fake.rows['seminar_sessions'][1]['moderator_name'], '새 월사회자')
        self.assertEqual(self.fake.rows['seminar_sessions'][2]['moderator_name'], '다른 사회자')
        for table in ['seminar_weeks', 'seminar_sessions', 'topic_events', 'history']:
            self.assertEqual(self.fake.rows[table][0]['book_title'], '새 책')
        self.assertEqual(self.fake.rows['history'][0]['groups'], [['가', '나']])
        self.assertEqual(self.fake.rows['seminar_sessions'][0]['actual_member_ids'], [1])

    def test_invalid_moderators_are_rejected_before_any_writes(self):
        for moderators in [[{'id': 'other', 'moderator_name': '잘못'}],
                           [{'id': 'thu', 'moderator_name': '가' * 101}],
                           [{'id': 'thu', 'moderator_name': []}],
                           [{'id': 'thu', 'moderator_name': '가'}] * 2, 'not-a-list']:
            before = deepcopy(self.fake.rows)
            response = self.save(dict(self.payload, moderators=moderators))
            self.assertEqual(response.status_code, 400, response.get_json())
            self.assertEqual(before, self.fake.rows)

    def test_csrf_and_admin_required(self):
        self.assertEqual(self.save(token='wrong').status_code, 403)
        with self.client.session_transaction() as session:
            session.clear()
        self.assertIn(self.save().status_code, [302, 401, 403])
        self.assertFalse(any(call[0] == 'update' for call in self.fake.calls))

    def test_blank_moderator_is_valid_schedule_draft(self):
        self.payload['moderators'] = [{'id': 'mon', 'moderator_name': '   '}]
        self.assertEqual(self.save().status_code, 200)
        self.assertIsNone(self.fake.rows['seminar_sessions'][1]['moderator_name'])
        self.assertEqual(self.fake.rows['seminar_sessions'][0]['moderator_name'], '목사회자')

    def test_book_only_legacy_request_preserves_moderators(self):
        del self.payload['moderators']
        self.assertEqual(self.save().status_code, 200)
        self.assertEqual(self.fake.rows['seminar_sessions'][0]['moderator_name'], '목사회자')

    def test_invalid_book_data_does_not_write(self):
        self.assertEqual(self.save(dict(self.payload, book_title=['잘못된 값'])).status_code, 400)
        self.assertEqual(self.save([]).status_code, 400)
        self.assertFalse(any(call[0] == 'update' for call in self.fake.calls))

    def test_failure_is_explicit_and_retry_is_safe(self):
        table = self.fake.table
        def fail_history(name):
            query = table(name)
            if name == 'history':
                query.execute = lambda: (_ for _ in ()).throw(RuntimeError('test outage'))
            return query
        with patch.object(self.fake, 'table', side_effect=fail_history):
            response = self.save()
        self.assertEqual(response.status_code, 500)
        self.assertIn('일부 항목', response.get_json()['message'])
        self.assertEqual(self.save().status_code, 200)
        self.assertEqual(len(self.fake.rows['seminar_sessions']), 3)


if __name__ == '__main__':
    unittest.main()
