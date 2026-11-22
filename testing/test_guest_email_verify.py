import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from testing._fake_supabase import FakeSupabase
from guest_email_verify import (normalize_knu_email, is_valid_knu_email,
    request_guest_email_code, verify_guest_email_code, get_verified_guest_email)


class EmailDB(FakeSupabase):
    def rpc(self, name, params):
        assert name == 'reserve_email_auth_code'
        now = datetime.now(timezone.utc)
        self.rows.setdefault('email_auth_codes', []).append({
            'id': params['p_id'], 'email': params['p_email'], 'purpose': params['p_purpose'],
            'code_hash': params['p_code_hash'], 'attempts': 0,
            'expires_at': (now + timedelta(minutes=10)).isoformat(), 'consumed_at': None,
        })
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=True))


class GuestEmailTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.secret_key = 'test secret'
        self.sent = []
        self.app.extensions['email_auth_sender'] = lambda *args: self.sent.append(args)
        self.db = EmailDB()
        self.ctx = self.app.test_request_context('/')
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def request_code(self):
        with patch('guest_email_verify.secrets.randbelow', return_value=123):
            request_guest_email_code(self.app, self.db, 'Test', 'topic_edit', '발제문 수정', 'event')

    def test_normalization(self):
        self.assertEqual(normalize_knu_email(' Test '), 'test@knu.ac.kr')
        self.assertTrue(is_valid_knu_email('Test', 'test@knu.ac.kr'))
        self.assertFalse(is_valid_knu_email('한글', normalize_knu_email('한글')))

    def test_verify_and_scope_grant(self):
        self.request_code()
        self.assertEqual(self.sent[0][1], '000123')
        self.assertTrue(verify_guest_email_code(self.app, self.db, 'topic_edit', 'event', '000123'))
        self.assertEqual(get_verified_guest_email('topic_edit', 'event'), 'test@knu.ac.kr')
        self.assertIsNone(get_verified_guest_email('topic_edit', 'other'))
        self.assertFalse(verify_guest_email_code(self.app, self.db, 'topic_edit', 'event', '000123'))

    def test_lockout(self):
        self.request_code()
        for _ in range(5):
            self.assertFalse(verify_guest_email_code(self.app, self.db, 'topic_edit', 'event', '000124'))
        self.assertFalse(verify_guest_email_code(self.app, self.db, 'topic_edit', 'event', '000123'))
        self.assertEqual(self.db.rows['email_auth_codes'][0]['attempts'], 5)

    def test_expiry(self):
        self.request_code()
        self.db.rows['email_auth_codes'][0]['expires_at'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        self.assertFalse(verify_guest_email_code(self.app, self.db, 'topic_edit', 'event', '000123'))
