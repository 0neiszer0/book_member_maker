import importlib
import json
import os
import unittest
from io import BytesIO
from unittest.mock import patch
from openpyxl import load_workbook
from testing._fake_supabase import FakeSupabase
from recruitment_results import DEFAULT_APPLICATION_QUESTIONS, normalize_application_questions, normalize_interview_slot_options, validate_application_submission

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
        self.form = dict(action='apply', csrf_token=self.csrf, name='홍길동', student_id='20261234', department='국문학과', phone='010-1234-5678', knu_email='BookUser', interview_availability='Saturday', answer_motivation='읽' * 200, answer_favorite_book='소' * 200)

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
        self.assertEqual(row['answers']['motivation']['answer'], '읽' * 200)
        row.update(id=APPLICANT, interview_slot='Sunday 14:00', reviewer_note='PRIVATE SECRET')
        duplicate = self.client.post(self.url, data={**self.form, 'name': '다른이름'}).get_data(as_text=True)
        self.assertIn('이미 해당 학번', duplicate)
        self.assertNotIn('value="홍길동"', duplicate)  # placeholder 예시에는 홍길동이 포함됨
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

    def test_invalid_links_render_the_isolated_portal(self):
        token = "00000000-0000-0000-0000-000000000000"
        for route, status in (("apply", 200), ("recruitment-results", 200), ("applicant-result", 404)):
            with self.subTest(route=route):
                response = self.client.get(f"/{route}/{token}")
                body = response.get_data(as_text=True)
                self.assertEqual(response.status_code, status)
                self.assertIn("사용할 수 없는 링크입니다", body)
                self.assertNotIn("lms-global", body)
                self.assertIn("no-store", response.headers["Cache-Control"])

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

    def test_min_max_length_normalization(self):
        legacy = normalize_application_questions('[최소200자] 동기\n[선택] [최소 100자] 소개\n일반')
        self.assertEqual([q['min_length'] for q in legacy], [200, 100, 0])
        self.assertFalse(legacy[1]['required']); self.assertEqual(legacy[2]['max_length'], 3000)
        built = normalize_application_questions(json.dumps([{'id': 'a', 'label': 'A', 'placeholder': 'p', 'required': True, 'min_length': 200, 'max_length': 1500}]))
        self.assertEqual((built[0]['min_length'], built[0]['max_length'], built[0]['placeholder']), (200, 1500, 'p'))
        old = normalize_application_questions([{'id': 'a', 'label': 'A', 'required': True}])
        self.assertEqual((old[0]['min_length'], old[0]['max_length']), (0, 3000))
        for bad in ({'min_length': 300, 'max_length': 100}, {'min_length': 2001}, {'max_length': 10}):
            with self.assertRaises(ValueError): normalize_application_questions([{'id': 'a', 'label': 'A', 'required': True, **bad}])

    def test_submission_min_length_and_phone_normalization(self):
        from werkzeug.datastructures import MultiDict
        campaign = dict(application_questions=DEFAULT_APPLICATION_QUESTIONS, interview_slot_options=[])
        def form(**kw): return MultiDict({**{k: v for k, v in self.form.items() if k not in ('action', 'csrf_token', 'interview_availability')}, **kw})
        with self.assertRaises(ValueError) as ctx: validate_application_submission(campaign, form(answer_motivation='가' * 199))
        self.assertIn('최소 200자 이상', str(ctx.exception)); self.assertIn('현재 199자', str(ctx.exception))
        with self.assertRaises(ValueError): validate_application_submission(campaign, form(answer_motivation='가' * 1501))
        data = validate_application_submission(campaign, form(phone='01012345678', knu_email='BookUser@knu.ac.kr'))
        self.assertEqual(data['phone'], '010-1234-5678'); self.assertEqual(data['knu_email'], 'bookuser@knu.ac.kr')
        self.assertEqual(validate_application_submission(campaign, form(phone='010 1234 5678'))['phone'], '010-1234-5678')
        self.assertEqual(validate_application_submission(campaign, form(answer_motivation='가' * 200))['answers']['motivation']['answer'], '가' * 200)

    def test_apply_page_guided_ui(self):
        body = self.client.get(self.url).get_data(as_text=True)
        for needle in ('knu-email-group', '@knu.ac.kr', 'data-min-length="200"', 'portal-char-counter', '010-1234-5678', 'id="applicant-phone"', 'apply-confirm-dialog', '최종 지원 전 확인해주세요', '이대로 최종 지원을 완료하시겠습니까?', '네, 최종 지원 완료하기'):
            self.assertIn(needle, body)

    def test_settings_preserve_structured_questions(self):
        self.login_admin()
        questions = [{'id': 'essay', 'label': '지원 동기', 'placeholder': '구체적으로 적어주세요', 'required': True, 'min_length': 200, 'max_length': 1200}]
        settings = dict(title='Test', intro_text='Intro', pending_message='Pending', accepted_message='Accepted', waitlisted_message='Wait', rejected_message='Rejected', application_questions=json.dumps(questions, ensure_ascii=False), interview_slot_options='Saturday')
        self.client.post('/admin/recruitment-results/' + CAMPAIGN + '/settings', data=settings)
        self.assertEqual(self.db.rows['recruitment_campaigns'][0]['application_questions'], questions)

if __name__ == '__main__': unittest.main()
