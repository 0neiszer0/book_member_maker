import importlib
import os
import unittest

from testing._fake_supabase import FakeSupabase

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'records-analytics-test')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'records-analytics-test')

SAFE_VIEW_ERROR = '기록을 불러오는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.'
SECRET = 'SECRET_DB_ERR'


class TableRaisingSupabase:
    """`table(<name>)` 호출이 특정 테이블에 대해서만 예외를 던지는 스텁."""

    def __init__(self, inner, raise_names):
        self.inner = inner
        self.raise_names = set(raise_names)

    def table(self, name):
        if name in self.raise_names:
            raise Exception(SECRET)
        return self.inner.table(name)


class RecordsAnalyticsRouteRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')
        cls.module.app.config['TESTING'] = True

    def test_all_4_endpoints_are_registered_with_exact_urls(self):
        rules = {}
        for rule in self.module.app.url_map.iter_rules():
            rules.setdefault(rule.endpoint, []).append(rule)

        expected = {
            'records_hub': ('/records', {'GET'}),
            'records_seminars': ('/records/seminars', {'GET'}),
            'records_seminar_detail': ('/records/seminars/<history_id>', {'GET'}),
            'records_analytics': ('/records/analytics', {'GET'}),
        }

        self.assertEqual(len(expected), 4)
        for endpoint, (rule_url, methods) in expected.items():
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, rules, f'{endpoint} not in url_map')
                matches = [r for r in rules[endpoint] if r.rule == rule_url]
                self.assertTrue(matches, f'{endpoint} rule {rule_url} missing')
                self.assertTrue(
                    methods.issubset(matches[0].methods),
                    f'{endpoint} methods {matches[0].methods}',
                )


class RecordsAnalyticsRouteErrorSafetyTests(unittest.TestCase):
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
        })
        self.original = self.module.supabase
        self.module.supabase = self.fake
        self.client = self.module.app.test_client()
        with self.client.session_transaction() as state:
            state.update(user_id=1, user_role='admin', user_name='운영')

    def tearDown(self):
        self.module.supabase = self.original

    def test_records_hub_db_failure_is_graceful(self):
        self.module.supabase = TableRaisingSupabase(self.fake, {'history'})
        response = self.client.get('/records')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SECRET, response.get_data(as_text=True))

    def test_records_analytics_db_failure_flashes_generic_only(self):
        self.module.supabase = TableRaisingSupabase(self.fake, {'history'})
        response = self.client.get('/records/analytics')
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            messages = [m for _, m in sess.get('_flashes', [])]
        self.assertIn(SAFE_VIEW_ERROR, messages)
        self.assertNotIn(SECRET, ' '.join(messages))
        self.assertNotIn(SECRET, response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
