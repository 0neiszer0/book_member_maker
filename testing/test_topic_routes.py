import importlib
import os
import unittest

from testing._fake_supabase import FakeSupabase

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'topic-routes-test')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'topic-routes-test')

SAFE_API_ERROR = '요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.'
SAFE_VIEW_ERROR = '발제문 정보를 불러오는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.'
SECRET = 'SECRET_DB_ERR'


class TableRaisingSupabase:
    """`table(<name>)` 호출이 특정 테이블에 대해서만 예외를 던지는 스텁.

    `login_required` 데코레이터는 항상 `members` 테이블을 읽으므로, 그 조회는
    내부 FakeSupabase로 위임하고 대상 테이블에 대해서만 예외를 흉내낸다.
    """

    def __init__(self, inner, raise_names):
        self.inner = inner
        self.raise_names = set(raise_names)

    def table(self, name):
        if name in self.raise_names:
            raise Exception(SECRET)
        return self.inner.table(name)


class TopicRouteRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')
        cls.module.app.config['TESTING'] = True

    def test_all_topic_endpoints_are_registered_with_exact_urls(self):
        rules = {}
        for rule in self.module.app.url_map.iter_rules():
            rules.setdefault(rule.endpoint, []).append(rule)

        expected = {
            'view_shared_topics': ('/shared_topics', {'GET'}),
            'submit_topics': ('/api/topics/submit', {'POST'}),
            'load_topics': ('/api/topics/load', {'POST'}),
            'create_topic_event': ('/api/admin/topic_events/create', {'POST'}),
            'seminar_session_open_topics': ('/api/admin/seminar_sessions/<session_id>/open_topics', {'POST'}),
            'seminar_week_open_topics': ('/api/admin/seminar_weeks/<week_id>/open_topics', {'POST'}),
            'delete_topic_event': ('/api/admin/topic_events/<event_id>/delete', {'POST'}),
            'toggle_topic_event': ('/api/admin/topic_events/<event_id>/toggle_active', {'POST'}),
            'topic_event_late_window': ('/api/admin/topic_events/<event_id>/late_window', {'POST'}),
            'admin_delete_topic_submission': ('/api/admin/topic_submissions/<submission_id>/delete', {'POST'}),
            'admin_update_topic_submission': ('/api/admin/topic_submissions/<submission_id>/update', {'POST'}),
            'admin_set_topic_limit': ('/api/admin/topic_submissions/<submission_id>/set_limit', {'POST'}),
            'view_admin_topics': ('/admin/topics/<event_id>/view', {'GET'}),
            'seminar_session_moderator': ('/admin/seminar_sessions/<session_id>/moderator', {'GET', 'POST'}),
            'topic_document_setup': ('/admin/topics/<event_id>/document_setup', {'GET', 'POST'}),
            'download_topics_word': ('/admin/topics/<event_id>/download_word', {'GET'}),
            'member_topic_reader': ('/seminars/topics/<event_id>', {'GET'}),
        }

        self.assertEqual(len(expected), 17)
        for endpoint, (rule_url, methods) in expected.items():
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, rules, f'{endpoint} not in url_map')
                matches = [r for r in rules[endpoint] if r.rule == rule_url]
                self.assertTrue(matches, f'{endpoint} rule {rule_url} missing')
                self.assertTrue(
                    methods.issubset(matches[0].methods),
                    f'{endpoint} methods {matches[0].methods}',
                )

    def test_shared_helpers_are_re_exported_on_app_module(self):
        self.assertTrue(callable(self.module._auto_close_topic_events))
        self.assertTrue(callable(self.module._authenticated_topic_member))


class TopicRouteErrorSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')
        cls.module.app.config['TESTING'] = True

    def setUp(self):
        self.fake = FakeSupabase({
            'members': [
                {'id': 1, 'name': '운영', 'role': 'admin', 'is_active': True,
                 'account_status': 'active', 'member_status': 'active',
                 'profile_pic': None, 'auth_provider': None, 'auth_session_version': None},
            ],
            'topic_events': [
                {'id': 'event-1', 'share_token': 'shared-token', 'book_title': '도서',
                 'meeting_date': '2099-09-08', 'is_active': True},
            ],
        })
        self.original = self.module.supabase
        self.module.supabase = self.fake
        self.client = self.module.app.test_client()
        with self.client.session_transaction() as state:
            state.update(user_id=1, user_role='admin', user_name='운영')

    def tearDown(self):
        self.module.supabase = self.original

    def test_api_errors_are_generic_and_never_leak_exception_text(self):
        cases = [
            ('create_topic_event', '/api/admin/topic_events/create', 'topic_events', {}),
            ('seminar_session_open_topics', '/api/admin/seminar_sessions/s1/open_topics', 'seminar_sessions', {}),
            ('seminar_week_open_topics', '/api/admin/seminar_weeks/w1/open_topics', 'seminar_sessions', {}),
        ]
        for endpoint, url, raise_table, payload in cases:
            with self.subTest(endpoint=endpoint):
                self.module.supabase = TableRaisingSupabase(self.fake, {raise_table})
                response = self.client.post(url, json=payload)
                self.assertEqual(response.status_code, 500, endpoint)
                data = response.get_json()
                self.assertEqual(
                    data.get('error') or data.get('message'), SAFE_API_ERROR, endpoint
                )
                self.assertNotIn(SECRET, response.get_data(as_text=True), endpoint)

    def test_view_admin_topics_db_failure_flashes_generic_only(self):
        self.module.supabase = TableRaisingSupabase(self.fake, {'topic_events'})
        response = self.client.get('/admin/topics/event-1/view')
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            messages = [m for _, m in sess.get('_flashes', [])]
        self.assertIn(SAFE_VIEW_ERROR, messages)
        self.assertNotIn(SECRET, ' '.join(messages))
        self.assertNotIn(SECRET, response.get_data(as_text=True))

    def test_shared_topics_renders_for_valid_public_token(self):
        self.module.supabase = self.fake
        response = self.client.get('/shared_topics?token=shared-token')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SECRET, response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
