import importlib
import inspect
import os
import unittest
from unittest.mock import patch

from flask import Flask, jsonify

from engagement import init_engagement_routes
from testing._fake_supabase import FakeQuery, FakeSupabase
from testing.test_topic_session_workflow import AfterMonday, AfterThursday

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'now-topic-test')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'now-topic-test')


class NowTopicLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')

    def setUp(self):
        self.fake = FakeSupabase({
            'topic_events': [
                {'id': 'shared', 'meeting_date': '2026-08-13', 'book_title': '공유 발제문',
                 'share_token': 'shared-token', 'is_active': True, 'seminar_week_id': 'week-1',
                 'seminar_session_id': 'thu'},
                {'id': 'standalone', 'meeting_date': '2026-08-13', 'book_title': '독립 발제문',
                 'share_token': 'standalone-token', 'is_active': True},
            ],
            'seminar_sessions': [
                {'id': 'thu', 'seminar_week_id': 'week-1', 'meeting_date': '2026-08-13', 'book_title': '공유 도서'},
                {'id': 'mon', 'seminar_week_id': 'week-1', 'meeting_date': '2026-08-17', 'book_title': '공유 도서'},
            ],
            'seminar_review_forms': [
                {'id': 'review', 'seminar_session_id': 'thu', 'status': 'open',
                 'share_token': 'review-token', 'close_at': '2099-01-01T00:00:00+00:00'},
            ],
        })
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY='now-topic-test')
        self.app.add_url_rule('/shared_topics', endpoint='view_shared_topics', view_func=lambda: '')
        init_engagement_routes(self.app, self.fake, lambda **kwargs: lambda function: function,
                               topic_event_lifecycle=self.module._auto_close_topic_events)

    def _cards(self, clock):
        with patch.object(self.module, 'supabase', self.fake), \
                patch.object(self.module, 'datetime', clock), \
                patch('engagement.render_template', side_effect=lambda template, **context: jsonify(cards=context['cards'])):
            response = self.app.test_client().get('/now')
        self.assertEqual(response.status_code, 200)
        return response.get_json()['cards']

    def test_now_applies_shared_cutoff_without_visiting_seminar_page(self):
        cards = self._cards(AfterThursday)
        topics = [card for card in cards if card['kind'] == '발제문']
        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0]['title'], '공유 발제문')
        self.assertEqual(topics[0]['close_at'], '2026-08-17T15:00:00+00:00')
        self.assertIn('shared-token', topics[0]['url'])
        self.assertFalse(self.fake.rows['topic_events'][1]['is_active'])
        selected = next(call[2][0] for call in self.fake.calls
                        if call[0] == 'select' and call[1] == 'topic_events')
        for column in ('is_active', 'seminar_week_id', 'seminar_session_id'):
            self.assertIn(column, selected.split(','))

    def test_now_removes_expired_topics_but_keeps_post_seminar_review(self):
        cards = self._cards(AfterMonday)
        self.assertFalse(any(card['kind'] == '발제문' for card in cards))
        self.assertTrue(any(card['kind'] == '세미나 후기' for card in cards))
        self.assertTrue(all(not row['is_active'] for row in self.fake.rows['topic_events']))

    def test_now_uses_actual_latest_session_date_after_schedule_change(self):
        self.fake.rows['seminar_sessions'][1]['meeting_date'] = '2026-08-24'
        cards = self._cards(AfterMonday)
        topic = next(card for card in cards if card['kind'] == '발제문')
        self.assertEqual(topic['close_at'], '2026-08-24T15:00:00+00:00')
        self.assertTrue(self.fake.rows['topic_events'][0]['is_active'])

    def test_expired_card_stays_hidden_even_when_auto_close_database_sync_fails(self):
        original_execute = FakeQuery.execute

        def fail_update(query):
            if query.table_name == 'topic_events' and query.operation == 'update':
                raise RuntimeError('simulated database write failure')
            return original_execute(query)

        with patch.object(FakeQuery, 'execute', fail_update):
            cards = self._cards(AfterMonday)
        self.assertFalse(any(card['kind'] == '발제문' for card in cards))
        self.assertTrue(self.fake.rows['topic_events'][0]['is_active'])

    def test_production_now_route_is_connected_to_same_lifecycle_callback(self):
        captured = inspect.getclosurevars(self.module.app.view_functions['engagement_now']).nonlocals
        self.assertIs(captured['topic_event_lifecycle'], self.module._auto_close_topic_events)


if __name__ == '__main__':
    unittest.main()
