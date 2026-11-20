import importlib
import os
import unittest

from testing._fake_supabase import FakeSupabase

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'special-events-test')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'special-events-test')

SAFE_API_ERROR = '요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.'
SAFE_VIEW_ERROR = '행사 정보를 불러오는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.'
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


class SpecialEventsRouteRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')
        cls.module.app.config['TESTING'] = True

    def test_all_8_endpoints_are_registered_with_exact_urls(self):
        rules = {}
        for rule in self.module.app.url_map.iter_rules():
            rules.setdefault(rule.endpoint, []).append(rule)

        expected = {
            'admin_special_events': ('/admin/special_events', {'GET'}),
            'admin_special_event_detail': ('/admin/special_events/<event_id>', {'GET'}),
            'create_special_event': ('/api/admin/special_events/create', {'POST'}),
            'update_special_event': ('/api/admin/special_events/<event_id>/update', {'POST'}),
            'toggle_special_event': ('/api/admin/special_events/<event_id>/toggle_active', {'POST'}),
            'delete_special_event': ('/api/admin/special_events/<event_id>/delete', {'POST'}),
            'add_special_event_attendee': ('/api/admin/special_events/<event_id>/attendees/add', {'POST'}),
            'remove_special_event_attendee': (
                '/api/admin/special_events/<event_id>/attendees/<int:member_id>/remove', {'POST'}
            ),
        }

        self.assertEqual(len(expected), 8)
        for endpoint, (rule_url, methods) in expected.items():
            with self.subTest(endpoint=endpoint):
                self.assertIn(endpoint, rules, f'{endpoint} not in url_map')
                matches = [r for r in rules[endpoint] if r.rule == rule_url]
                self.assertTrue(matches, f'{endpoint} rule {rule_url} missing')
                self.assertTrue(
                    methods.issubset(matches[0].methods),
                    f'{endpoint} methods {matches[0].methods}',
                )


class SpecialEventsRouteErrorSafetyTests(unittest.TestCase):
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
            ('create_special_event', '/api/admin/special_events/create', 'special_events',
             {'name': 'MT', 'event_date': '2026-08-13'}),
            ('update_special_event', '/api/admin/special_events/e1/update', 'special_events',
             {'name': 'MT'}),
            ('toggle_special_event', '/api/admin/special_events/e1/toggle_active', 'special_events', {}),
            ('delete_special_event', '/api/admin/special_events/e1/delete', 'special_events', {}),
            ('add_special_event_attendee', '/api/admin/special_events/e1/attendees/add',
             'special_event_attendees', {'member_ids': [1, 2]}),
            ('remove_special_event_attendee', '/api/admin/special_events/e1/attendees/1/remove',
             'special_event_attendees', {}),
        ]
        for endpoint, url, raise_table, payload in cases:
            with self.subTest(endpoint=endpoint):
                self.module.supabase = TableRaisingSupabase(self.fake, {raise_table})
                response = self.client.post(url, json=payload)
                self.assertEqual(response.status_code, 500, endpoint)
                data = response.get_json()
                self.assertEqual(data['error'], SAFE_API_ERROR, endpoint)
                self.assertNotIn(SECRET, response.get_data(as_text=True))

    def test_admin_special_events_renders_200_for_admin(self):
        self.module.supabase = self.fake
        response = self.client.get('/admin/special_events')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SECRET, response.get_data(as_text=True))

    def test_admin_special_events_db_failure_flashes_generic_only(self):
        self.module.supabase = TableRaisingSupabase(self.fake, {'special_events'})
        response = self.client.get('/admin/special_events')
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as sess:
            messages = [m for _, m in sess.get('_flashes', [])]
        self.assertIn(SAFE_VIEW_ERROR, messages)
        self.assertNotIn(SECRET, ' '.join(messages))
        self.assertNotIn(SECRET, response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
