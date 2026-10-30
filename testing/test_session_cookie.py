import importlib
import os
import unittest
from unittest.mock import patch
from testing._fake_supabase import FakeSupabase

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'session-cookie-test-only')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'session-cookie-test-only')

TO_MEMBER = '회원 화면으로 전환했습니다.'
TO_ADMIN = '관리자 화면으로 돌아왔습니다.'


class SessionCookieRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')

    def setUp(self):
        member = {'id': 1, 'name': '등록실명', 'social_id': '123', 'role': 'admin',
                  'is_active': True, 'member_status': 'active', 'account_status': 'active'}
        self.fake = FakeSupabase({'members': [member]})
        self.original = self.module.supabase
        self.module.supabase = self.fake
        self.client = self.module.app.test_client()
        self.client.get('/login/kakao?remember=1&next=/mypage')
        with self.client.session_transaction() as state:
            oauth_state = state['oauth_state']
        with patch.object(self.module.KakaoOauth, 'get_token', return_value={'access_token': 'test'}), \
             patch.object(self.module.KakaoOauth, 'get_user_info', return_value={'id': 123, 'kakao_account': {'profile': {'nickname': 'x'}}}):
            self.client.get('/login/kakao/callback?code=test&state=' + oauth_state)

    def tearDown(self):
        self.module.supabase = self.original

    def sets_cookie(self, response):
        return any(v.startswith('session=') for v in response.headers.getlist('Set-Cookie'))

    def test_background_requests_do_not_resend_unchanged_session(self):
        for path in ('/static/lms.css', '/push-worker.js', '/manifest.webmanifest'):
            with self.subTest(path=path):
                self.assertFalse(self.sets_cookie(self.client.get(path)))
        api = self.client.get('/api/member-notifications', headers={'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Dest': 'empty'})
        self.assertFalse(self.sets_cookie(api))

    def test_page_navigation_still_rolls_remembered_login(self):
        response = self.client.get('/mypage', headers={'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.sets_cookie(response))
        self.assertIn('Expires=', ' '.join(response.headers.getlist('Set-Cookie')))

    def test_stale_background_response_cannot_bring_back_shown_flash(self):
        self.client.post('/toggle-member-preview')
        stale = self.client.get_cookie('session').value  # still holds the flash
        page = self.client.get('/mypage').get_data(as_text=True)
        self.assertEqual(page.count(TO_MEMBER), 1)
        fresh = self.client.get_cookie('session').value
        # A static/service-worker request that started with the stale cookie answers late.
        self.client.set_cookie('session', stale)
        late = self.client.get('/push-worker.js')
        self.assertFalse(self.sets_cookie(late))
        self.client.set_cookie('session', fresh)
        self.assertNotIn(TO_MEMBER, self.client.get('/mypage').get_data(as_text=True))

    def test_view_switch_notices_are_one_shot_toasts_with_close_button(self):
        self.client.post('/toggle-member-preview')
        html = self.client.get('/mypage').get_data(as_text=True)
        self.assertIn(TO_MEMBER, html)
        self.assertIn('data-autohide="4000"', html)
        self.assertIn('data-lms-flash-close', html)
        self.assertIn('lms_flash.js', html)
        self.client.post('/toggle-member-preview')
        admin = self.client.get('/admin/seminars').get_data(as_text=True)
        self.assertIn(TO_ADMIN, admin)
        self.assertNotIn(TO_MEMBER, admin)
        self.assertNotIn(TO_ADMIN, self.client.get('/admin/seminars').get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()