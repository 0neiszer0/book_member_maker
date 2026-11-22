import importlib
import os
import unittest
from io import BytesIO
from unittest.mock import patch
from openpyxl import load_workbook
from testing._fake_supabase import FakeSupabase
from recruitment_results import DEFAULT_APPLICATION_QUESTIONS, normalize_application_questions, normalize_interview_slot_options

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'application-tests')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'application-tests')
CAMPAIGN = '10000000-0000-0000-0000-000000000001'
TOKEN = '20000000-0000-0000-0000-000000000001'
APPLICANT = '30000000-0000-0000-0000-000000000001'

class ApplicationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')

    def setUp(self):
        self.db = FakeSupabase({'recruitment_campaigns': [dict(id=CAMPAIGN, share_token=TOKEN, title='Test', is_active=True, is_published=False, is_accepting_applications=True, application_questions=DEFAULT_APPLICATION_QUESTIONS, interview_slot_options=['Saturday'], pending_message='Pending', intro_text='Intro', accepted_message='Accepted', waitlisted_message='Wait', rejected_message='Rejected', dues_account_info='Bank 123', dues_contact_phone='123')], 'recruitment_applicants': [], 'recruitment_lookup_attempts': [], 'members': [dict(id=1, name='Admin', role='admin', is_active=True, account_status='active', member_status='active', auth_provider='kakao', social_id='test')]})
        self.app = self.module.app
        for patcher in (patch.object(self.module, 'supabase', self.db), patch.dict(self.app.config, TESTING=True, REQUIRE_ORIGIN_AUTH=False)):
            patcher.start(); self.addCleanup(patcher.stop)
        self.client = self.app.test_client()
        self.url = '/apply/' + TOKEN
        self.client.get(self.url)
        with self.client.session_transaction() as sess: self.csrf = sess['sensitive_csrf']
        self.form = dict(action='apply', csrf_token=self.csrf, name='홍길동', student_id='20261234', department='국문학과', phone='010-1234-5678', knu_email='BookUser', interview_availability='Saturday', answer_motivation='읽고 싶어요', answer_favorite_book='소설')

    def login_admin(self):
        with self.client.session_transaction() as sess:
            sess.clear(); sess.update(user_id=1, user_role='admin', auth_provider='kakao', sensitive_csrf='staff')

    def test_parsers(self):
        self.assertFalse(normalize_application_questions('[선택] 질문')[0]['required'])
        self.assertEqual(normalize_interview_slot_options('A\nB\nA'), ['A', 'B'])
        with self.assertRaises(ValueError): normalize_interview_slot_options(['x' * 101])
        with self.assertRaises(ValueError): normalize_application_questions([{'id': 'x', 'label': '', 'required': True}])

    def test_aliases_isolation_and_submission_stages(self):
        for path in (self.url, '/recruitment-results/' + TOKEN):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('class="lms-global', response.get_data(as_text=True))
            self.assertIn('no-store', response.headers['Cache-Control'])
            self.assertEqual(self.client.get('/login').status_code, 303)
            self.assertEqual(self.client.get('/mypage').status_code, 303)
        response = self.client.post(self.url, data=self.form)
        self.assertIn('지원서 제출 완료', response.get_data(as_text=True))
        row = self.db.rows['recruitment_applicants'][0]
        self.assertEqual(row['knu_email'], 'bookuser@knu.ac.kr')
        self.assertEqual(row['interview_availability'], ['Saturday'])
        self.assertEqual(row['answers']['motivation']['answer'], '읽고 싶어요')
        row.update(id=APPLICANT, interview_slot='Sunday 14:00', reviewer_note='PRIVATE SECRET')
        duplicate = self.client.post(self.url, data={**self.form, 'name': '다른이름'}).get_data(as_text=True)
        self.assertIn('이미 해당 학번', duplicate)
        self.assertNotIn('홍길동', duplicate)
        self.db.rows['recruitment_campaigns'][0]['is_accepting_applications'] = False
        body = self.client.post(self.url, data={'action':'lookup', 'name':'홍길동', 'student_id':'20261234'}).get_data(as_text=True)
        self.assertIn('Sunday 14:00', body); self.assertNotIn('PRIVATE SECRET', body)
        wrong = self.client.post(self.url, data={'action':'lookup', 'name':'다른이름', 'student_id':'20261234'}).get_data(as_text=True)
        self.assertNotIn('Sunday 14:00', wrong)
        self.db.rows['recruitment_campaigns'][0]['is_published'] = True
        row['result_status'] = 'accepted'
        row['dues_paid_at'] = '2026-11-22T00:00:00Z'
        body = self.client.post(self.url, data={'name':'홍길동', 'student_id':'20261234'}).get_data(as_text=True)
        self.assertIn('Bank 123', body); self.assertIn('회비 입금 확인 완료', body); self.assertNotIn('PRIVATE SECRET', body)
        row['result_status'] = 'rejected'
        self.assertNotIn('Bank 123', self.client.post(self.url, data={'name':'홍길동', 'student_id':'20261234'}).get_data(as_text=True))

    def test_rate_limit_and_closed_stage(self):
        from datetime import datetime, timezone
        ip_hash = None
        with self.app.test_request_context(self.url, environ_base={'REMOTE_ADDR': '127.0.0.1'}):
            from flask import g
            g.trusted_app_proxy = False
            ip_hash = self.module._applicant_request_hash()
        self.db.rows['recruitment_lookup_attempts'] = [dict(id=i, campaign_id=CAMPAIGN, ip_hash=ip_hash, created_at=datetime.now(timezone.utc).isoformat()) for i in range(10)]
        self.assertEqual(self.client.post(self.url, data={'name':'x', 'student_id':'1234'}).status_code, 429)
        self.db.rows['recruitment_campaigns'][0]['is_active'] = False
        self.assertIn('종료', self.client.get(self.url).get_data(as_text=True))

    def test_validation_and_csrf(self):
        for overrides in ({'website':'spam'}, {'answer_motivation':''}, {'phone':'bad'}, {'interview_availability':'unknown'}):
            self.client.post(self.url, data={**self.form, **overrides})
        self.assertEqual(self.db.rows['recruitment_applicants'], [])
        self.assertEqual(self.client.post(self.url, data={**self.form, 'csrf_token':'bad'}).status_code, 403)

    def test_officer_settings_review_and_export(self):
        self.db.rows['recruitment_applicants'].append(dict(id=APPLICANT, campaign_id=CAMPAIGN, name='홍길동', name_key='홍길동', student_id='20261234', result_status='pending', answers={}))
        self.login_admin()
        base = '/admin/recruitment-results/' + CAMPAIGN
        settings = dict(title='Test', intro_text='Intro', pending_message='Pending', accepted_message='Accepted', waitlisted_message='Wait', rejected_message='Rejected', is_active='on', is_accepting_applications='on', application_questions='질문 하나\n[선택] 질문 둘', interview_slot_options='Saturday\nSunday')
        self.client.post(base + '/settings', data=settings)
        campaign = self.db.rows['recruitment_campaigns'][0]
        self.assertEqual(len(campaign['application_questions']), 2)
        self.assertEqual(campaign['interview_slot_options'], ['Saturday', 'Sunday'])
        self.client.post(base + '/applicants/' + APPLICANT, data=dict(name='홍길동', student_id='20261234', result_status='accepted', interview_slot='Sunday', reviewer_note='PRIVATE SECRET'))
        self.assertEqual(self.db.rows['recruitment_applicants'][0]['reviewer_note'], 'PRIVATE SECRET')
        response = self.client.get(base + '/export')
        self.assertEqual(response.status_code, 200)
        rows = list(load_workbook(BytesIO(response.data)).active.values)
        self.assertIn('운영진메모', rows[0]); self.assertIn('PRIVATE SECRET', rows[1])

if __name__ == '__main__': unittest.main()
