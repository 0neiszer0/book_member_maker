import importlib
import os
import unittest
from unittest.mock import patch
from testing._fake_supabase import FakeSupabase

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'login-test-only')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'login-test-only')


class PersistentLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')

    def setUp(self):
        self.member = {'id': 1, 'name': '등록실명', 'social_id': '123', 'role': 'admin',
                       'is_active': True, 'member_status': 'active', 'account_status': 'active'}
        self.fake = FakeSupabase({'members': [self.member]})
        self.original = self.module.supabase
        self.module.supabase = self.fake
        self.client = self.module.app.test_client()

    def tearDown(self):
        self.module.supabase = self.original

    def oauth(self, remember='1'):
        self.client.get('/login/kakao?remember=' + remember + '&next=/my/term_attendance')
        with self.client.session_transaction() as state:
            oauth_state = state['oauth_state']
        with patch.object(self.module.KakaoOauth, 'get_token', return_value={'access_token': 'test'}), \
             patch.object(self.module.KakaoOauth, 'get_user_info', return_value={'id':123, 'kakao_account':{'profile':{'nickname':'실명이 아닌 별명', 'profile_image_url':'https://example.com/avatar.png'}}}):
            return self.client.get('/login/kakao/callback?code=test&state=' + oauth_state)

    def test_persistent_cookie_survives_a_new_client_and_keeps_real_name(self):
        result = self.oauth()
        self.assertTrue(result.location.endswith('/my/term_attendance'))
        cookie = result.headers['Set-Cookie']
        for flag in ('Expires=', 'HttpOnly', 'SameSite=Lax'):
            self.assertIn(flag, cookie)
        self.assertEqual(self.module.app.permanent_session_lifetime.days, 90)
        self.assertEqual(self.fake.rows['members'][0]['name'], '등록실명')
        self.assertEqual(self.fake.rows['members'][0]['profile_pic'], 'https://example.com/avatar.png')
        fresh = self.module.app.test_client()
        fresh.set_cookie('session', self.client.get_cookie('session').value)
        self.assertEqual(fresh.get('/my/term_attendance').status_code, 200)
        with fresh.session_transaction() as state:
            self.assertEqual(state['user_name'], '등록실명')
            self.assertTrue(state.permanent)

    def test_opt_out_uses_session_cookie_and_survives_access_without_upgrading(self):
        result = self.oauth('0')
        self.assertNotIn('Expires=', result.headers['Set-Cookie'])
        self.client.get('/my/term_attendance')
        with self.client.session_transaction() as state:
            self.assertFalse(state.permanent)

    def test_legacy_login_upgrades_but_logout_removes_identity(self):
        with self.client.session_transaction() as state:
            state.update(user_id=1, user_role='admin')
        self.client.get('/my/term_attendance')
        with self.client.session_transaction() as state:
            self.assertTrue(state.permanent)
        self.client.get('/logout')
        with self.client.session_transaction() as state:
            self.assertNotIn('user_id', state)
        self.assertEqual(self.client.post('/api/admin/term_members/t', json={}).status_code, 401)

    def test_inactive_account_is_rejected_even_for_member_only_pages(self):
        self.oauth()
        self.fake.rows['members'][0]['member_status'] = 'inactive'
        self.client.get('/my/term_attendance')
        with self.client.session_transaction() as state:
            self.assertNotIn('user_id', state)

    def test_demotion_applies_without_relogin(self):
        self.oauth()
        self.fake.rows['members'][0]['role'] = 'member'
        self.assertEqual(self.client.post('/api/admin/members/create', json={}).status_code, 403)
        self.assertEqual(self.client.get('/my/term_attendance').status_code, 200)

    def test_unavailable_authorization_never_uses_cached_role(self):
        self.oauth()
        with patch.object(self.fake, 'table', side_effect=RuntimeError('offline')):
            self.assertEqual(self.client.post('/api/admin/members/create', json={}).status_code, 503)

    def test_new_oauth_request_clears_previous_identity(self):
        self.oauth()
        self.client.get('/login/kakao')
        with self.client.session_transaction() as state:
            self.assertNotIn('user_id', state)
            self.assertIn('oauth_state', state)

    def test_bad_oauth_state_never_authenticates(self):
        self.client.get('/login/kakao')
        with patch.object(self.module.KakaoOauth, 'get_token') as token:
            self.client.get('/login/kakao/callback?code=test&state=bad')
            token.assert_not_called()
        with self.client.session_transaction() as state:
            self.assertNotIn('user_id', state)


if __name__ == '__main__':
    unittest.main()
