import importlib
import os
from pathlib import Path
import unittest

from testing._fake_supabase import FakeSupabase

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'records-activity-test')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'records-activity-test')

ROOT = Path(__file__).resolve().parents[1]

SAFE_API_ERROR = '요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.'
INVALID_MEMBER_IDS = '참여자 ID 형식이 올바르지 않습니다.'


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
            raise Exception('SECRET_PG_INTERNAL_ERR')
        return self.inner.table(name)


class RecordsActivityRouteRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')
        cls.module.app.config['TESTING'] = True

    def test_all_12_endpoints_are_registered_with_exact_urls(self):
        rules = {}
        for rule in self.module.app.url_map.iter_rules():
            rules.setdefault(rule.endpoint, []).append(rule)

        expected = {
            'records_brick_books': ('/records/brick_books', {'GET'}),
            'records_brick_book_detail': ('/records/brick_books/<book_id>', {'GET'}),
            'brick_book_create': ('/api/admin/brick_books/create', {'POST'}),
            'brick_book_delete': ('/api/admin/brick_books/<book_id>/delete', {'POST'}),
            'brick_session_add': ('/api/admin/brick_books/<book_id>/sessions/add', {'POST'}),
            'brick_session_delete': ('/api/admin/brick_sessions/<session_id>/delete', {'POST'}),
            'records_study_groups': ('/records/study_groups', {'GET'}),
            'records_study_group_detail': ('/records/study_groups/<group_id>', {'GET'}),
            'study_group_create': ('/api/admin/study_groups/create', {'POST'}),
            'study_group_delete': ('/api/admin/study_groups/<group_id>/delete', {'POST'}),
            'study_session_add': ('/api/admin/study_groups/<group_id>/sessions/add', {'POST'}),
            'study_session_delete': ('/api/admin/study_sessions/<session_id>/delete', {'POST'}),
        }

        self.assertEqual(len(expected), 12)
        for endpoint, (rule_url, methods) in expected.items():
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, rules, f'{endpoint} not in url_map')
                matches = [r for r in rules[endpoint] if r.rule == rule_url]
                self.assertTrue(matches, f'{endpoint} rule {rule_url} missing')
                self.assertTrue(
                    methods.issubset(matches[0].methods),
                    f'{endpoint} methods {matches[0].methods}',
                )

    def test_systemd_templates_are_hardened(self):
        service = (ROOT / 'infra' / 'minipc' / 'bookmembers.service').read_text(encoding='utf-8')
        cloudflared = (ROOT / 'infra' / 'minipc' / 'bookmembers-cloudflared.service').read_text(encoding='utf-8')
        self.assertIn('--no-control-socket', service)
        self.assertIn('--edge-ip-version 4', cloudflared)


class RecordsActivityRouteErrorSafetyTests(unittest.TestCase):
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

    def test_api_errors_are_generic_and_never_leak_exception_text(self):
        cases = [
            ('brick_book_create', '/api/admin/brick_books/create', 'brick_books',
             {'title': '책'}),
            ('brick_session_add', '/api/admin/brick_books/b1/sessions/add', 'brick_book_sessions',
             {'meeting_date': '2026-08-13', 'member_ids': [1, 2]}),
            ('study_group_create', '/api/admin/study_groups/create', 'study_groups',
             {'name': '모임'}),
            ('study_session_add', '/api/admin/study_groups/g1/sessions/add', 'study_group_sessions',
             {'meeting_date': '2026-08-13', 'member_ids': [1, 2]}),
        ]
        for endpoint, url, raise_table, payload in cases:
            with self.subTest(endpoint=endpoint):
                self.module.supabase = TableRaisingSupabase(self.fake, {raise_table})
                response = self.client.post(url, json=payload)
                self.assertEqual(response.status_code, 500, endpoint)
                data = response.get_json()
                self.assertEqual(data['status'], 'error', endpoint)
                self.assertEqual(data['message'], SAFE_API_ERROR, endpoint)
                self.assertNotIn('SECRET_PG_INTERNAL_ERR', response.get_data(as_text=True))

    def test_session_add_rejects_non_integer_member_ids(self):
        urls = [
            '/api/admin/brick_books/b1/sessions/add',
            '/api/admin/study_groups/g1/sessions/add',
        ]
        for url in urls:
            with self.subTest(url=url):
                self.module.supabase = self.fake
                response = self.client.post(url, json={'meeting_date': '2026-08-13', 'member_ids': ['abc']})
                self.assertEqual(response.status_code, 400, url)
                self.assertEqual(response.get_json()['message'], INVALID_MEMBER_IDS, url)
                self.assertNotIn('abc', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
