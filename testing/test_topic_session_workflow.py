import importlib
import os
import unittest
from datetime import datetime, timezone, timedelta
from io import BytesIO
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from testing._fake_supabase import FakeSupabase

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'topic-session-test')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'topic-session-test')


class AfterThursday(datetime):
    @classmethod
    def now(cls, tz=None):
        instant = cls(2026, 8, 14, 12, tzinfo=timezone(timedelta(hours=9)))
        return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)


class AfterMonday(datetime):
    @classmethod
    def now(cls, tz=None):
        instant = cls(2026, 8, 18, 0, tzinfo=timezone(timedelta(hours=9)))
        return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)


class TopicSessionWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')
        cls.original_supabase = cls.module.supabase
        cls.module.app.config.update(TESTING=True, SECRET_KEY='topic-session-test')

    def setUp(self):
        self.fake = FakeSupabase({
            'members': [{'id': 1, 'name': '운영자', 'role': 'admin', 'is_active': True,
                         'member_status': 'active', 'account_status': 'active', 'department': '국문학과'}],
            'topic_events': [{'id': 'event-1', 'share_token': 'shared-token', 'book_title': '공유 도서',
                              'meeting_date': '2026-08-13', 'seminar_week_id': 'week-1',
                              'seminar_session_id': 'thu', 'is_active': True, 'moderator_name': ''}],
            'seminar_sessions': [
                {'id': 'thu', 'seminar_week_id': 'week-1', 'meeting_date': '2026-08-13',
                 'book_title': '공유 도서', 'day_type': 'thu', 'moderator_name': '목요일 사회자'},
                {'id': 'mon', 'seminar_week_id': 'week-1', 'meeting_date': '2026-08-17',
                 'book_title': '공유 도서', 'day_type': 'mon', 'moderator_name': ''},
                {'id': 'other', 'seminar_week_id': 'week-2', 'meeting_date': '2026-08-20',
                 'moderator_name': '다른 주 사회자'},
            ],
            'topic_submissions': [{'id': 'submission-1', 'event_id': 'event-1', 'author_name': '발제자',
                                   'department': '국문학과', 'admission_year': '26',
                                   'topics': [{'topic': '질문 하나 & 질문 둘', 'page': '10'}]}],
        })
        self.module.supabase = self.fake
        self.client = self.module.app.test_client()
        with self.client.session_transaction() as flask_session:
            flask_session['user_id'] = 1
            flask_session['user_role'] = 'admin'
            flask_session['user_name'] = '운영자'

    def tearDown(self):
        self.module.supabase = self.original_supabase

    def _csrf(self):
        with self.client.session_transaction() as flask_session:
            return flask_session['topic_moderator_csrf']

    def test_shared_link_stays_open_on_friday_and_labels_final_deadline(self):
        with patch.object(self.module, 'datetime', AfterThursday):
            response = self.client.get('/shared_topics?token=shared-token')
        self.assertEqual(response.status_code, 200)
        self.assertIn('2026-08-18 00:00', response.get_data(as_text=True))
        self.assertTrue(self.fake.rows['topic_events'][0]['is_active'])

    def test_thursday_entry_is_closed_but_does_not_close_shared_pool(self):
        with patch.object(self.module, 'datetime', AfterThursday):
            response = self.client.get('/shared_topics?token=shared-token&session_id=thu')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.fake.rows['topic_events'][0]['is_active'])

    def test_submit_api_enforces_session_deadline_for_page_left_open(self):
        with patch.object(self.module, 'datetime', AfterThursday):
            response = self.client.post('/api/topics/submit', json={
                'event_id': 'event-1', 'session_id': 'thu', 'topics': [{'topic': '새 질문'}],
            })
        self.assertEqual(response.status_code, 400)
        self.assertIn('마감', response.get_json()['error'])
        self.assertTrue(self.fake.rows['topic_events'][0]['is_active'])
        self.assertEqual(len(self.fake.rows['topic_submissions']), 1)

    def test_monday_entry_uses_same_pool_and_is_still_open_after_thursday(self):
        with patch.object(self.module, 'datetime', AfterThursday):
            response = self.client.post('/api/topics/submit', json={
                'event_id': 'event-1', 'session_id': 'mon', 'topics': [{'topic': '월요일 질문'}],
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.fake.rows['topic_submissions'][-1]['event_id'], 'event-1')

    def test_shared_pool_closes_at_tuesday_midnight_on_direct_submit(self):
        with patch.object(self.module, 'datetime', AfterMonday):
            response = self.client.post('/api/topics/submit', json={
                'event_id': 'event-1', 'topics': [{'topic': '너무 늦은 질문'}],
            })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(self.fake.rows['topic_events'][0]['is_active'])

    def test_unrelated_session_cannot_extend_submission_window(self):
        with patch.object(self.module, 'datetime', AfterThursday):
            response = self.client.post('/api/topics/submit', json={
                'event_id': 'event-1', 'session_id': 'other', 'topics': [{'topic': '다른 주'}],
            })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(len(self.fake.rows['topic_submissions']), 1)

    def test_download_without_selected_session_requires_selection(self):
        response = self.client.get('/admin/topics/event-1/download_word')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/document_setup', response.location)
        self.assertFalse(any(call[0] == 'update' for call in self.fake.calls))

    def test_missing_moderator_prompts_then_saves_before_continuing_download(self):
        response = self.client.get('/admin/topics/event-1/download_word?session_id=mon')
        self.assertEqual(response.status_code, 302)
        self.assertIn('session_id=mon', response.location)
        form = self.client.get(response.location)
        self.assertEqual(form.status_code, 200)
        self.assertIn('사회자 이름', form.get_data(as_text=True))
        saved = self.client.post('/admin/topics/event-1/document_setup', data={
            'session_id': 'mon', 'moderator_name': ' 월요일 사회자 ',
            'csrf_token': self._csrf(), 'download': '1',
        })
        self.assertEqual(saved.status_code, 302)
        self.assertIn('download_word?session_id=mon', saved.location)
        self.assertEqual(self.fake.rows['seminar_sessions'][1]['moderator_name'], '월요일 사회자')
        self.assertEqual(self.fake.rows['seminar_sessions'][0]['moderator_name'], '목요일 사회자')
        self.assertEqual(self.fake.rows['topic_events'][0]['moderator_name'], '')

    def test_empty_moderator_and_cross_session_metadata_are_rejected(self):
        self.client.get('/admin/topics/event-1/document_setup?session_id=mon')
        empty = self.client.post('/admin/topics/event-1/document_setup', data={
            'session_id': 'mon', 'moderator_name': ' ', 'csrf_token': self._csrf(),
        })
        other = self.client.post('/admin/topics/event-1/document_setup', data={
            'session_id': 'other', 'moderator_name': '악의적 변경', 'csrf_token': self._csrf(),
        })
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(other.status_code, 400)
        self.assertEqual(self.fake.rows['seminar_sessions'][2]['moderator_name'], '다른 주 사회자')

    def test_moderator_write_requires_csrf_and_admin_role(self):
        self.client.get('/admin/seminar_sessions/mon/moderator')
        response = self.client.post('/admin/seminar_sessions/mon/moderator', data={'moderator_name': '안됨'})
        self.assertEqual(response.status_code, 403)
        self.fake.rows['members'][0]['role'] = 'member'
        denied = self.client.post('/admin/seminar_sessions/mon/moderator', data={
            'moderator_name': '안됨', 'csrf_token': self._csrf(),
        })
        self.assertEqual(denied.status_code, 302)
        self.assertEqual(self.fake.rows['seminar_sessions'][1]['moderator_name'], '')

    def test_standalone_event_can_save_moderator_and_download(self):
        event = self.fake.rows['topic_events'][0]
        event.update(seminar_week_id=None, seminar_session_id=None)
        self.client.get('/admin/topics/event-1/document_setup')
        saved = self.client.post('/admin/topics/event-1/document_setup', data={
            'moderator_name': '독립 모임 사회자', 'csrf_token': self._csrf(),
        })
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(event['moderator_name'], '독립 모임 사회자')

    def test_actual_word_contains_selected_session_moderator_date_and_shared_questions(self):
        self.fake.rows['seminar_sessions'][1]['moderator_name'] = '월요일 & 사회자'
        response = self.client.get('/admin/topics/event-1/download_word?session_id=mon')
        self.assertEqual(response.status_code, 200)
        self.assertIn('wordprocessingml', response.mimetype)
        with ZipFile(BytesIO(response.data)) as archive:
            xml = ET.fromstring(archive.read('word/document.xml'))
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        text = ''.join(node.text or '' for node in xml.findall('.//w:t', ns))
        self.assertIn('월요일 & 사회자', text)
        self.assertIn('2026.08.17', text)
        self.assertIn('질문 하나 & 질문 둘', text)
        self.assertNotIn('목요일 사회자', text)
        self.assertFalse(any(call[0] == 'update' for call in self.fake.calls))


if __name__ == '__main__':
    unittest.main()
