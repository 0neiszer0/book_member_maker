import importlib
import os
import subprocess
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import email_auth_mailer
import local_auth
from testing import test_local_login as legacy


class EmailTestDB(legacy.IdFakeSupabase):
    def reserve_email_auth_code(self, p_id, p_email, p_purpose, p_code_hash, p_client_ip):
        now = local_auth.now_utc()
        recent = [r for r in self.rows["email_auth_codes"]
                  if local_auth.parse_time(r["created_at"]) > now - timedelta(hours=1)]
        email_rows = [r for r in recent if r["email"] == p_email]
        if len(email_rows) >= 5 or any(local_auth.parse_time(r["created_at"]) > now - timedelta(seconds=60)
                                      for r in email_rows) or sum(r["client_ip"] == p_client_ip for r in recent) >= 20:
            return False
        self.rows["email_auth_codes"].append(dict(
            id=p_id, email=p_email, purpose=p_purpose, code_hash=p_code_hash, client_ip=p_client_ip, attempts=0,
            created_at=local_auth.iso(now), expires_at=local_auth.iso(now + timedelta(minutes=10))))
        return True

    def complete_email_signup(self, p_code_id, p_email, p_name, p_student_id, p_department, p_pin_hash, p_signup_code):
        now = local_auth.now_utc()
        proof = next((r for r in self.rows["email_auth_codes"] if r["id"] == p_code_id), {})
        if not proof.get("consumed_at") or proof.get("finalized_at") or proof["email"] != p_email:
            return {"result": "expired"}
        fields = dict(knu_email=p_email, knu_email_verified_at=proof["consumed_at"], auth_provider="local",
                      pin_hash=p_pin_hash, pin_failed_attempts=0, pin_locked_until=None)
        same_id = [m for m in self.rows["members"]
                   if local_auth.normalize_member_student_id(m.get("student_id")) == p_student_id]
        if any(m.get("knu_email") == p_email for m in self.rows["members"]):
            return {"result": "conflict"}
        if same_id:
            target = same_id[0]
            credential = next((c for c in self.rows["member_credentials"] if c["member_id"] == target["id"]), None)
            if len(same_id) != 1 or target["name"].strip() != p_name or target["role"] != "member" \
                    or target["account_status"] != "active" or not target["is_active"] \
                    or target["member_status"] in ("inactive", "blocked", "pending") or target.get("knu_email") \
                    or str(target.get("social_id") or "").startswith("system:") \
                    or any(o["member_id"] == target["id"] for o in self.rows["term_officers"]) \
                    or ((credential or target.get("auth_provider") == "local")
                        and (credential or {}).get("status") != "active"):
                return {"result": "conflict"}
            target.update(fields, student_id=p_student_id, auth_session_version=target["auth_session_version"] + 1)
        else:
            if not p_department:
                return {"result": "department"}
            setting = next((c for c in self.rows["signup_codes"] if not c.get("revoked_at")), {})
            ot_deadline = local_auth.parse_time(setting.get("auto_approve_until"))
            ot = bool(ot_deadline and ot_deadline > now)
            expiry = local_auth.parse_time(setting.get("expires_at"))
            if not ot:
                if not setting or setting["code"] == local_auth.OT_SIGNUP_MARKER or (expiry and expiry <= now):
                    return {"result": "closed"}
                if setting["code"] not in (p_signup_code, local_auth.OPEN_SIGNUP_MARKER):
                    return {"result": "code"}
            target = self.table("members").insert(dict(
                name=p_name, student_id=p_student_id, department=p_department, role="member",
                account_status="active" if ot else "pending", member_status="active" if ot else "inactive",
                is_active=ot, **fields)).execute().data[0]
            if ot:
                self.ensure_signup_term_member(target["id"])
        proof["finalized_at"] = local_auth.iso(now)
        return {"result": target["account_status"], "member_id": target["id"]}


class KnuEmailPinTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("app")
        self.app = self.module.app
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        self.db = EmailTestDB(legacy.rows())
        self.db.rows["email_auth_codes"] = []
        self.now = datetime(2026, 11, 21, 10, tzinfo=timezone.utc)
        self.sent = []
        clients = patch.multiple(self.module.supabase, table=self.db.table, rpc=self.db.rpc)
        sender = patch.dict(self.app.extensions, {"email_auth_sender": lambda *args: self.sent.append(args)})
        for context in (clients, sender, patch.object(local_auth, "now_utc", lambda: self.now),
                        patch.object(local_auth.secrets, "randbelow", return_value=12345),
                        patch.object(local_auth.signup_notify, "notify_signup")):
            context.start()
            self.addCleanup(context.stop)

    def form(self, url, client=None, **data):
        client = client or self.client
        with client.session_transaction() as session:
            csrf = session.setdefault("sensitive_csrf", "csrf")
        return client.post(url, data={"csrf_token": csrf, **data})

    def send(self, email="student@knu.ac.kr", purpose="login", client=None):
        return self.form("/auth/email/request", client, email=email, purpose=purpose)

    def verify(self, code="012345", client=None, **extra):
        return self.form("/auth/email/verify", client, code=code, **extra)

    def enroll(self, **extra):
        data = dict(name="신규회원", student_id="2026123456", department="철학과")
        return self.form("/auth/email/enroll", **(data | extra))

    def pin(self, pin="123456", identifier="student@knu.ac.kr", client=None):
        return self.form("/login/pin", client, identifier=identifier, pin=pin)

    def member(self, mid):
        return next(m for m in self.db.rows["members"] if m["id"] == mid)

    def linked(self, mid=3, pin=None, email="student@knu.ac.kr"):
        self.member(mid).update(knu_email=email, knu_email_verified_at=local_auth.iso(self.now),
                                auth_provider="local", pin_hash=local_auth.hash_password(pin) if pin else None,
                                pin_failed_attempts=0, pin_locked_until=None)

    def admin(self):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session.update(user_id=1, user_role="admin", auth_provider="kakao", sensitive_csrf="csrf")
        return client

    def configure(self, action, **extra):
        return self.admin().post("/api/admin/signup-code", json={"action": action, **extra},
                                 headers={"X-App-CSRF": "csrf"})

    def assert_session(self, mid, client=None):
        with (client or self.client).session_transaction() as session:
            self.assertEqual(session["user_id"], mid)
            self.assertEqual(session["auth_provider"], "local")
            self.assertTrue(session.permanent)

    def assert_digit_widget(self, html, field_id, name, *, masked=True, required=True):
        field = html.split(f'id="{field_id}-label"', 1)[1].split('</div>\n</div>', 1)[0]
        original = field.split('data-auth-code-value', 1)[1].split('>', 1)[0]
        self.assertIn(f'id="{field_id}" name="{name}" data-auth-code-value', field)
        self.assertEqual(field.count('data-auth-code-digit'), 6)
        self.assertIn('pattern="[0-9]{6}"', original)
        self.assertEqual(' required' in original, required)
        self.assertEqual('type="password"' in original, masked)
        self.assertEqual('data-auth-code-toggle aria-pressed="false"' in field, masked)
        self.assertEqual('PIN 보기' in field, masked)
        self.assertIn('data-auth-code-controls hidden', field)
        if not masked:
            self.assertIn('autocomplete="one-time-code"', original)
            self.assertEqual(field.count('autocomplete="one-time-code"'), 2)

    def test_login_response_headers(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Referrer-Policy"], "same-origin")

    def test_account_setup_response_headers(self):
        token = "test-account-setup-token"
        self.db.rows["account_setup_tokens"].append({
            "member_id": 3,
            "token_hash": local_auth.token_digest(token),
            "expires_at": local_auth.iso(self.now + timedelta(minutes=10)),
        })
        response = self.client.get(f"/account/setup/{token}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Referrer-Policy"], "same-origin")

    def test_email_request_requires_an_allowed_origin_when_present(self):
        base_url = self.module.PUBLIC_BASE_URL
        self.assertEqual(self.client.get("/login", base_url=base_url).status_code, 200)
        with self.client.session_transaction(base_url=base_url) as session:
            csrf = session["sensitive_csrf"]
        data = {"email": "probe@example.invalid", "csrf_token": csrf}
        response = self.client.post("/auth/email/request", base_url=base_url, data=data,
                                    headers={"Origin": base_url, "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(response.status_code, 400)
        self.assertIn(local_auth.EMAIL_ERROR, response.get_data(as_text=True))
        response = self.client.post("/auth/email/request", base_url=base_url, data=data,
                                    headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.sent, [])

    def test_applicant_result_form_accepts_same_origin_and_blocks_null_origin(self):
        token = "11111111-1111-4111-8111-111111111111"
        path = f"/applicant-result/{token}"
        base_url = self.module.PUBLIC_BASE_URL
        self.db.rows["recruitment_campaigns"] = [{
            "id": "test-campaign", "share_token": token, "title": "지원 결과", "is_active": True, "is_published": True,
        }]
        self.db.rows["recruitment_applicants"] = [{
            "id": 1, "campaign_id": "test-campaign", "name": "테스트 지원자",
            "name_key": "테스트지원자", "student_id": "2026000000", "result_status": "waitlisted",
        }]

        page = self.client.get(path, base_url=base_url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers["Referrer-Policy"], "same-origin")
        with self.client.session_transaction(base_url=base_url) as session:
            self.assertEqual(session["applicant_portal_token"], token)
            data = {"name": "테스트 지원자", "student_id": "2026000000", "csrf_token": session["sensitive_csrf"]}

        accepted = self.client.post(path, base_url=base_url, data=data,
                                    headers={"Origin": base_url, "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(accepted.status_code, 200)
        self.assertIn("테스트 지원자님의 결과", accepted.get_data(as_text=True))
        rejected = self.client.post(path, base_url=base_url, data=data,
                                    headers={"Origin": "null", "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(rejected.status_code, 403)
        self.assertNotIn("테스트 지원자님의 결과", rejected.get_data(as_text=True))

    def test_forbidden_html_has_korean_guidance_and_navigation(self):
        response = self.client.post("/auth/email/request", headers={"Accept": "text/html"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.mimetype, "text/html")
        page = response.get_data(as_text=True)
        self.assertIn("요청을 처리할 수 없습니다 (403)", page)
        self.assertIn("페이지가 오래되었거나 권한이 없는 요청입니다. 새로고침 후 다시 시도하거나 로그인 화면으로 돌아가 주세요.", page)
        self.assertIn('href="/login"', page)
        self.assertIn('href="/"', page)
        self.assertNotIn("You don't have the permission", page)

    def test_forbidden_json_and_existing_api_error(self):
        response = self.client.post("/api/admin/signup-code", headers={"Accept": "text/html"})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.is_json)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

        response = self.client.post("/auth/email/request", headers={"Accept": "application/json"})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(response.is_json)

        response = self.admin().post("/api/admin/signup-code",
                                     headers={"X-App-CSRF": "csrf", "Origin": "null"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json(), {"error": "허용되지 않은 요청 출처입니다."})

    def test_origin_auth_forbidden_renders_without_template_context(self):
        with patch.dict(self.app.config, {"REQUIRE_ORIGIN_AUTH": True}), \
                patch.object(self.app, "update_template_context", side_effect=RuntimeError):
            response = self.client.get("/login")
        self.assertEqual(response.status_code, 403)
        self.assertIn("요청을 처리할 수 없습니다 (403)", response.get_data(as_text=True))

    def test_non_knu_email_and_csrf_rejection(self):
        for path in ("/auth/email/request", "/auth/email/verify", "/auth/email/enroll", "/login/pin",
                     "/account/pin/setup", "/account/pin/reset"):
            self.assertEqual(self.client.post(path).status_code, 403, path)
        for address in ("user@gmail.com", "user@sub.knu.ac.kr", "user@knu.ac.kr.example.com", "a b@knu.ac.kr"):
            response = self.send(address)
            self.assertEqual(response.status_code, 400, address)
            self.assertIn(local_auth.EMAIL_ERROR, response.get_data(as_text=True))
        self.assertEqual(self.db.rows["email_auth_codes"], [])
        self.assertEqual(self.sent, [])

    def test_email_code_normalization_hmac_redirect_and_replay(self):
        self.linked(pin="123456")
        response = self.send("  STUDENT@KNU.AC.KR ")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.sent, [("student@knu.ac.kr", "012345", "로그인")])
        record = self.db.rows["email_auth_codes"][0]
        self.assertRegex(record["code_hash"], r"^[0-9a-f]{64}$")
        self.assertNotIn("012345", response.get_data(as_text=True))
        self.assertEqual(local_auth.parse_time(record["expires_at"]) - self.now, timedelta(minutes=10))
        with self.client.session_transaction() as session:
            challenge = session["email_challenge"]
        response = self.verify(next="/mypage")
        self.assertEqual(response.location, "/mypage")
        self.assert_session(3)
        self.assertIsNotNone(record.get("consumed_at"))
        replay = self.app.test_client()
        with replay.session_transaction() as session:
            session["email_challenge"] = challenge
        self.assertEqual(self.verify(client=replay).status_code, 400)

    def test_code_entry_comes_before_resend_and_pin(self):
        response = self.send()
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("메일이 보이지 않으면 스팸메일함도 확인해 주세요.", html)
        self.assertIn('placeholder="예: 123456"', html)
        self.assertIn('name="email" value="student@knu.ac.kr"', html)
        self.assertNotIn('name="email" type="email"', html)
        self.assertLess(html.index('action="/auth/email/verify"'), html.index("인증코드 다시 받기"))
        self.assertIn("다른 메일 입력", html)
        self.assertIn('<section id="school-email"', html)
        self.assertIn('class="auth-title">이메일 인증코드 로그인</h1>', html)
        self.assertNotIn('id="pin-login"', html)
        self.assertNotIn('<details id="pin-login"', html)
        self.assertIn("6자리 PIN으로 로그인", html)
        self.assertIn('auth_code_boxes.js', html)
        self.assert_digit_widget(html, 'login-code', 'code', masked=False)
        self.assertRegex(html, r'data-auth-code data-digit-mask="false" data-auto-submit="true">\s*<label id="login-code-label"')
        reset = self.client.get("/login?mode=pin_reset").get_data(as_text=True)
        self.assertIn('class="auth-title">PIN 재설정</h1>', reset)
        self.assertIn('name="purpose" value="pin_reset"', reset)
        self.assertIn('<section id="school-email"', reset)
        self.assertNotIn('id="pin-login"', reset)
        self.assertNotIn('href="/signup', reset)
        failed_pin = self.pin().get_data(as_text=True)
        self.assertIn('<section id="pin-login"', failed_pin)
        self.assertNotIn('id="school-email"', failed_pin)

    def test_default_login_is_pin_first_with_auto_submit(self):
        html = self.client.get("/login").get_data(as_text=True)
        self.assertIn('<section id="pin-login"', html)
        self.assertNotIn('id="school-email"', html)
        self.assertNotIn("<details", html)
        self.assertNotIn("auth-migration-notice", html)
        self.assertRegex(html, r'data-auth-code data-digit-mask="true" data-auto-submit="true">\s*<label id="login-pin-label"')
        self.assertNotIn('id="login-code"', html)
        self.assertEqual(html.count('href="/signup'), 1)
        self.assertIn('>학교 메일로 회원가입</a>', html)
        self.assertIn('href="/login?mode=email"', html)
        self.assertIn("mode=pin_reset", html)
        self.assertNotIn('action="/auth/email/request"', html)
        self.assert_digit_widget(html, 'login-pin', 'pin')

    def test_guest_auth_pages_use_isolated_shell(self):
        for url in ("/login", "/login?mode=email", "/signup"):
            with self.subTest(url=url):
                html = self.app.test_client().get(url).get_data(as_text=True)
                self.assertIn("lms-isolated-auth", html)
                self.assertIn('class="auth-brand"', html)
                self.assertIn("경북대학교 중앙독서동아리", html)
                self.assertNotIn('class="lms-breadcrumb"', html)
                self.assertNotIn("quick_search.js", html)

    def test_signup_page_starts_with_school_email_only(self):
        response = self.client.get("/signup?next=/mypage")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Referrer-Policy"], "same-origin")
        html = response.get_data(as_text=True)
        self.assertIn('class="auth-title">회원가입</h1>', html)
        self.assertIn('class="auth-steps"', html)
        self.assertEqual(html.count("<form"), 1)
        self.assertIn('action="/auth/email/request"', html)
        self.assertIn('name="purpose" value="signup"', html)
        self.assertIn('aria-hidden="true">@knu.ac.kr</span>', html)
        self.assertIn('name="next" value="/mypage"', html)
        for absent in ('name="login_id"', 'name="password"', 'action="/signup"', "<details",
                       'id="pin-login"', 'id="login-pin"', 'action="/login/pin"'):
            self.assertNotIn(absent, html)
        self.assertIn('href="/login?next=/mypage"', html)
        unsafe = self.app.test_client().get("/signup?next=https://example.test").get_data(as_text=True)
        self.assertIn('name="next" value=""', unsafe)
        self.assertNotIn('value="https://example.test"', unsafe)
        self.assertNotIn('next=https', unsafe.split("</head>", 1)[1])

    def test_signup_email_code_stays_in_signup_flow_then_enrolls(self):
        self.client.get("/signup")
        sent = self.send(purpose="signup")
        self.assertEqual(sent.status_code, 200)
        html = sent.get_data(as_text=True)
        self.assertIn('class="auth-title">인증코드 입력</h1>', html)
        self.assertIn('class="auth-steps"', html)
        self.assertIn('action="/auth/email/verify"', html)
        self.assert_digit_widget(html, 'login-code', 'code', masked=False)
        self.assertIn('name="purpose" value="signup"', html)
        self.assertIn("다른 메일 입력", html)
        self.assertNotIn('id="pin-login"', html)
        self.assertNotIn('name="login_id"', html)
        bad = self.send(email="user@gmail.com", purpose="signup")
        self.assertEqual(bad.status_code, 400)
        self.assertIn('class="auth-title">회원가입</h1>', bad.get_data(as_text=True))
        verified = self.verify()
        self.assertEqual(verified.status_code, 303)
        self.assertEqual(verified.location, "/auth/email/enroll")
        enroll = self.client.get("/auth/email/enroll").get_data(as_text=True)
        self.assertIn('class="auth-title">회원 정보 입력</h1>', enroll)
        self.assertIn("student@knu.ac.kr 인증 완료", enroll)
        self.assertIn("가입 완료하기", enroll)

    def test_signup_pin_does_not_auto_submit(self):
        self.send()
        self.verify()
        html = self.client.get("/auth/email/enroll").get_data(as_text=True)
        self.assert_digit_widget(html, 'signup-pin', 'pin', required=False)
        self.assertNotIn('data-auto-submit', html)

    def test_school_email_requests_and_pin_login_accept_bare_school_ids(self):
        response = self.client.get("/login?mode=email")
        self.assertIn('class="knu-email-group"', response.get_data(as_text=True))
        self.assertIn('placeholder="예: hobanu"', response.get_data(as_text=True))
        self.assertEqual(self.send(email=" Hobanu ").status_code, 200)
        self.assertEqual(self.sent[-1][0], "hobanu@knu.ac.kr")
        self.now += timedelta(minutes=2)
        self.assertEqual(self.send(email="HOBANU@KNU.AC.KR").status_code, 200)
        self.assertEqual(self.sent[-1][0], "hobanu@knu.ac.kr")
        self.assertEqual(self.send(email="user@gmail.com").status_code, 400)
        self.assertEqual(self.send(email="K").status_code, 400)

        self.linked(pin="123456", email="hobanu@knu.ac.kr")
        for identifier in (" Hobanu ", "hobanu@knu.ac.kr", "2022 000003"):
            with self.subTest(identifier=identifier):
                self.assertEqual(self.pin(identifier=identifier, client=self.app.test_client()).status_code, 302)
        invalid = self.pin(identifier="user@gmail.com", client=self.app.test_client())
        self.assertEqual(invalid.status_code, 400)
        self.assertIn(local_auth.EMAIL_ERROR, invalid.get_data(as_text=True))

    def test_signup_with_verified_grant_redirects_to_enrollment(self):
        self.send()
        self.verify()
        response = self.client.get("/signup")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.location, "/auth/email/enroll")
        enrolled = self.client.get(response.location)
        self.assertEqual(enrolled.status_code, 200)
        self.assert_digit_widget(enrolled.get_data(as_text=True), 'signup-pin', 'pin', required=False)

    def test_expiry_wrong_code_limit_and_rate_limit(self):
        self.linked(pin="123456")
        self.assertEqual(self.send().status_code, 200)
        self.assertEqual(self.send(purpose="pin_reset").status_code, 429)
        for i in range(5):
            self.assertEqual(self.verify("222222").status_code, 429 if i == 4 else 401)
        self.assertEqual(self.verify().status_code, 429)
        record = self.db.rows["email_auth_codes"][0]
        self.assertEqual(record["attempts"], 5)
        self.assertIsNone(record.get("consumed_at"))
        for _ in range(4):
            self.now += timedelta(seconds=61)
            self.assertEqual(self.send().status_code, 200)
        self.now += timedelta(seconds=61)
        self.assertEqual(self.send().status_code, 429)
        self.now += timedelta(minutes=10)
        self.assertEqual(self.verify().status_code, 400)

    def test_ip_limit_ignores_untrusted_forwarding(self):
        for i in range(20):
            self.assertEqual(self.send(f"mail{i}@knu.ac.kr").status_code, 200)
        response = self.client.post("/auth/email/request", data={"email": "another@knu.ac.kr", "csrf_token": "csrf"},
                                    headers={"X-App-Client-IP": "8.8.8.8", "X-Forwarded-For": "8.8.8.8"})
        self.assertEqual(response.status_code, 429)

    def test_existing_roster_is_linked_in_closed_signup_with_optional_pin(self):
        self.member(3)["student_id"] = "2022 000003"
        self.assertEqual(self.send().status_code, 200)
        self.assertEqual(self.verify().location, "/auth/email/enroll")
        html = self.client.get("/auth/email/enroll").get_data(as_text=True)
        self.assertIn("student@knu.ac.kr", html)
        self.assertIn('action="/auth/email/enroll"', html)
        response = self.enroll(name="이명부", student_id="2022 000003", department="", pin="123456")
        self.assertEqual(response.location, "/mypage")
        self.assert_session(3)
        member = self.member(3)
        self.assertEqual(member["knu_email"], "student@knu.ac.kr")
        self.assertTrue(member["knu_email_verified_at"])
        self.assertTrue(member["pin_hash"].startswith("$argon2id$"))
        fresh = self.app.test_client()
        self.assertEqual(self.pin(identifier="2022 000003", client=fresh).status_code, 302)
        self.assert_session(3, fresh)

    def test_roster_claim_rejects_conflicts_and_inactive_or_privileged_members(self):
        self.member(3).update(member_status="inactive", is_active=False)
        self.member(5)["member_status"] = "blocked"
        self.assertEqual(self.send().status_code, 200)
        self.verify()
        for mid in (1, 3, 4, 5):
            member = self.member(mid)
            self.assertEqual(self.enroll(name=member["name"], student_id=member["student_id"]).status_code, 409)
            self.assertIsNone(member.get("knu_email"))
        self.member(3).update(member_status="active", is_active=True)
        self.db.rows["member_credentials"].append(dict(member_id=3, login_id="legacy_user", status="pending"))
        self.assertEqual(self.enroll(name="이명부", student_id="2022000003").status_code, 409)
        self.assertEqual(self.enroll(name="다른이름", student_id="2022000003").status_code, 409)
        self.assertEqual(len(self.db.rows["members"]), 5)

    def test_active_legacy_login_links_school_email_and_revokes_previous_session(self):
        self.member(3).update(auth_provider="local", auth_session_version=2)
        self.db.rows["member_credentials"].append(
            dict(member_id=3, login_id="legacy_user", status="active", password_hash=local_auth.hash_password(legacy.GOOD_PW))
        )
        old = self.app.test_client()
        response = self.form("/login/password", old, login_id="legacy_user", password=legacy.GOOD_PW, remember="1")
        self.assertEqual(response.status_code, 302)
        self.assert_session(3, old)

        self.send()
        self.verify()
        self.assertEqual(self.enroll(name="이명부", student_id="2022000003", pin="123456").location, "/mypage")
        self.assert_session(3)
        self.assertEqual(self.member(3)["knu_email"], "student@knu.ac.kr")
        self.assertEqual(self.member(3)["auth_session_version"], 3)
        self.assertEqual(len(self.db.rows["members"]), 5)
        self.assertEqual(old.get("/mypage").status_code, 302)
        with old.session_transaction() as session:
            self.assertNotIn("user_id", session)

    def test_pin_lock_reset_revokes_old_sessions_and_restores_login(self):
        self.linked(pin="123456")
        old = self.app.test_client()
        self.assertEqual(self.pin(client=old).status_code, 302)
        for i in range(5):
            self.assertEqual(self.pin(pin="654321").status_code, 429 if i == 4 else 401)
        response = self.pin()
        self.assertEqual(response.status_code, 429)
        self.assertIn('href="/login?mode=pin_reset"', response.get_data(as_text=True))
        self.assertEqual(local_auth.parse_time(self.member(3)["pin_locked_until"]) - self.now, timedelta(minutes=15))
        self.send(purpose="pin_reset")
        self.assertEqual(self.verify().location, "/account/pin/reset")
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)
        page = self.client.get("/account/pin/reset")
        self.assertEqual(page.status_code, 200)
        self.assert_digit_widget(page.get_data(as_text=True), 'new-pin', 'pin')
        self.assert_digit_widget(page.get_data(as_text=True), 'confirm-pin', 'pin_confirm')
        self.assertEqual(self.form("/account/pin/reset", pin="246810", pin_confirm="111111").status_code, 400)
        self.assertEqual(self.form("/account/pin/reset", pin="246810", pin_confirm="246810").location, "/mypage")
        self.assert_session(3)
        self.assertEqual(self.member(3)["auth_session_version"], 1)
        self.assertEqual((self.member(3)["pin_failed_attempts"], self.member(3)["pin_locked_until"]), (0, None))
        self.assertEqual(old.get("/mypage").status_code, 302)
        self.assertEqual(self.pin(client=self.app.test_client()).status_code, 401)
        self.assertEqual(self.pin(pin="246810", client=self.app.test_client()).status_code, 302)

    def test_email_login_prompts_pin_setup_and_expired_pin_lock_resets_counter(self):
        self.linked()
        self.send()
        self.assertEqual(self.verify().location, "/account/pin/setup")
        self.assert_session(3)
        page = self.client.get("/account/pin/setup")
        self.assertEqual(page.status_code, 200)
        self.assert_digit_widget(page.get_data(as_text=True), 'new-pin', 'pin')
        self.assert_digit_widget(page.get_data(as_text=True), 'confirm-pin', 'pin_confirm')
        self.assertEqual(self.form("/account/pin/setup", pin="123456", pin_confirm="123456").status_code, 302)
        self.member(3).update(pin_failed_attempts=5, pin_locked_until=local_auth.iso(self.now - timedelta(seconds=1)))
        fresh = self.app.test_client()
        self.assertEqual(self.pin(pin="654321", client=fresh).status_code, 401)
        self.assertEqual(self.member(3)["pin_failed_attempts"], 1)
        self.assertIsNone(self.member(3)["pin_locked_until"])
        self.assertEqual(self.pin(client=fresh).status_code, 302)
        self.assert_session(3, fresh)

    def test_staff_and_term_officer_pin_setup_login_and_reset(self):
        for mid, user in ((1, "admin"), (4, "officer"), (3, "termofficer")):
            with self.subTest(user=user):
                email = user + "@knu.ac.kr"
                self.linked(mid, email=email)
                if mid == 3:
                    self.db.rows["term_officers"].append(dict(term_id="t-1", member_id=mid))
                client = self.app.test_client()
                self.assertEqual(self.send(email, client=client).status_code, 200)
                self.assertEqual(self.verify(client=client).location, "/account/pin/setup")
                self.assertEqual(self.form("/account/pin/setup", client, pin="123456", pin_confirm="123456").status_code, 302)
                old = self.app.test_client()
                self.assertEqual(self.pin(identifier=email, client=old).status_code, 302)
                self.assert_session(mid, old)
                with old.session_transaction() as session:
                    self.assertEqual(session["login_method"], "pin")
                self.assertEqual(old.get("/mypage").status_code, 200)
                self.now += timedelta(seconds=61)
                reset = self.app.test_client()
                self.assertEqual(self.send(email, purpose="pin_reset", client=reset).status_code, 200)
                self.assertEqual(self.verify(client=reset).location, "/account/pin/reset")
                self.assertEqual(self.form("/account/pin/reset", reset, pin="246810", pin_confirm="246810").status_code, 302)
                self.assertEqual(old.get("/mypage").status_code, 302)
                self.assertEqual(self.pin(identifier=email, client=self.app.test_client()).status_code, 401)
                self.assertEqual(self.pin(pin="246810", identifier=email, client=self.app.test_client()).status_code, 302)

    def test_staff_pin_security_and_concurrent_revocation(self):
        original_verify = local_auth.verify_password
        for mid, user in ((1, "admin"), (4, "officer")):
            with self.subTest(user=user):
                email = user + "@knu.ac.kr"
                self.linked(mid, "123456", email)
                member = self.member(mid)
                for field, value in (("is_active", False), ("account_status", "disabled"),
                                     ("member_status", "inactive"), ("knu_email_verified_at", None)):
                    previous = member[field]
                    member[field] = value
                    self.assertEqual(self.pin(identifier=email, client=self.app.test_client()).status_code, 401)
                    member[field] = previous
                for attempt in range(5):
                    self.assertEqual(self.pin(pin="654321", identifier=email, client=self.app.test_client()).status_code,
                                     429 if attempt == 4 else 401)
                self.assertEqual(self.pin(identifier=email, client=self.app.test_client()).status_code, 429)
                self.assertEqual(local_auth.parse_time(member["pin_locked_until"]) - self.now, timedelta(minutes=15))
                member.update(pin_failed_attempts=0, pin_locked_until=None)
                def revoke_during_verify(pin_hash, pin):
                    result = original_verify(pin_hash, pin)
                    member["auth_session_version"] += 1
                    return result
                with patch.object(local_auth, "verify_password", side_effect=revoke_during_verify):
                    self.assertEqual(self.pin(identifier=email, client=self.app.test_client()).status_code, 401)

    def test_provisioned_staff_email_gets_verified_only_after_otp(self):
        staff = self.member(4)
        staff["knu_email"] = "officer@knu.ac.kr"
        self.assertEqual(self.pin(identifier=staff["knu_email"]).status_code, 401)
        self.assertIsNone(staff.get("knu_email_verified_at"))
        self.assertEqual(self.send(staff["knu_email"]).status_code, 200)
        self.assertEqual(self.verify().location, "/account/pin/setup")
        self.assert_session(4)
        self.assertEqual(staff["knu_email_verified_at"], local_auth.iso(self.now))

    def test_ot_auto_approval_enrolls_and_expires(self):
        from wiki_access import wiki_access

        self.db.rows["seminar_terms"][0]["roster_initialized_at"] = local_auth.iso(self.now)
        self.assertEqual(self.configure("ot_open", hours=2).status_code, 400)
        response = self.configure("ot_open", hours=1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(local_auth.parse_time(response.json["auto_approve_until"]) - self.now, timedelta(hours=1))
        self.assertIn("ot-expiry", self.admin().get("/admin/members").get_data(as_text=True))
        self.send(purpose="signup")
        self.verify()
        self.assertEqual(self.enroll(pin="741852").location, "/mypage")
        member = self.db.rows["members"][-1]
        self.assertEqual((member["account_status"], member["member_status"], member["is_active"]), ("active", "active", True))
        self.assert_session(member["id"])
        self.assertIn(dict(term_id="t-1", member_id=member["id"], status="active", entry_type="new"),
                      self.db.rows["seminar_term_members"])
        with self.client.session_transaction() as session:
            access = wiki_access(self.db, session, today=self.now.date())
        self.assertTrue(access.can_edit)
        self.now += timedelta(hours=1)
        self.client = self.app.test_client()
        self.send("later@knu.ac.kr", purpose="signup")
        self.verify()
        closed = self.enroll(student_id="2026678901")
        self.assertEqual(closed.status_code, 403)
        self.assertIn(local_auth.SIGNUP_CLOSED, closed.get_data(as_text=True))
        self.assertEqual(len(self.db.rows["members"]), 6)

    def test_vacation_code_and_open_mode_remain_live_and_manual_approval_adds_roster(self):
        self.db.rows["seminar_terms"][0]["end_date"] = "2026-11-01"
        response = self.configure("set", code="BOOK2026")
        self.assertGreater(local_auth.parse_time(response.json["expires_at"]), self.now)
        self.send(purpose="signup")
        self.verify()
        self.assertEqual(self.enroll(signup_code="invalid").status_code, 400)
        self.assertEqual(self.enroll(signup_code="book2026").status_code, 200)
        self.assertEqual(self.configure("open").status_code, 200)
        self.send("open@knu.ac.kr", "signup")
        self.verify()
        self.assertEqual(self.enroll(student_id="2026123457").status_code, 200)
        member = self.db.rows["members"][-1]
        self.assertEqual(member["account_status"], "pending")
        admin = self.admin()
        html = admin.get("/admin/members").get_data(as_text=True)
        self.assertIn("승인 대기 2명", html)
        self.assertIn("open@knu.ac.kr", html)
        self.assertEqual(admin.post(f"/api/admin/members/{member['id']}/approve-login",
                                    headers={"X-App-CSRF": "csrf"}).status_code, 200)
        self.assertEqual(self.member(member["id"])["account_status"], "active")
        self.assertIn(dict(term_id="t-1", member_id=member["id"], status="active", entry_type="new"),
                      self.db.rows["seminar_term_members"])

    def test_approval_does_not_reactivate_inactive_member(self):
        self.member(3).update(member_status="inactive", is_active=False)
        self.db.rows["member_credentials"].append(dict(member_id=3, status="pending"))
        self.assertEqual(self.admin().post("/api/admin/members/3/approve-login",
                                           headers={"X-App-CSRF": "csrf"}).status_code, 409)
        self.assertFalse(self.member(3)["is_active"])
        self.assertEqual(self.member(3)["member_status"], "inactive")

    def test_delivery_failure_is_sanitized(self):
        with patch.dict(self.app.extensions, {"email_auth_sender": lambda *_: self.fail_delivery()}):
            response = self.send()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("sensitive-upstream-detail", response.get_data(as_text=True))
        with self.client.session_transaction() as session:
            self.assertNotIn("email_challenge", session)

    @staticmethod
    def fail_delivery():
        raise email_auth_mailer.MailDeliveryError("sensitive-upstream-detail")


class MailerTests(unittest.TestCase):
    def test_resend_and_brevo_payloads(self):
        for provider, key_name, endpoint, text_key, html_key in (
            ("resend", "RESEND_API_KEY", "https://api.resend.com/emails", "text", "html"),
            ("brevo", "BREVO_API_KEY", "https://api.brevo.com/v3/smtp/email", "textContent", "htmlContent"),
        ):
            with self.subTest(provider=provider), patch.dict(os.environ, {"MAIL_PROVIDER": provider, key_name: "secret"}), \
                    patch.object(email_auth_mailer.requests, "post") as post:
                email_auth_mailer.send_verification_code("user@knu.ac.kr", "012345", "로그인")

                self.assertEqual(post.call_args.args, (endpoint,))
                self.assertEqual(post.call_args.kwargs["timeout"], 10)
                payload = post.call_args.kwargs["json"]
                self.assertIn("012345", payload[text_key])
                self.assertIn("책 먹는 호반우", payload["subject"])
                self.assertIn("012345", payload[html_key])
                self.assertIn("경북대학교 중앙 독서동아리 · 책 먹는 호반우", payload[html_key])

    def test_html_verification_email_escapes_code_and_purpose(self):
        env = {"MAIL_PROVIDER": "resend", "RESEND_API_KEY": "secret"}
        with patch.dict(os.environ, env), patch.object(email_auth_mailer.requests, "post") as post:
            email_auth_mailer.send_verification_code("user@knu.ac.kr", "<012345>", "로그인 & 가입")
        html = post.call_args.kwargs["json"]["html"]
        self.assertIn("&lt;012345&gt;", html)
        self.assertIn("로그인 &amp; 가입", html)

    def test_smtp_tls_and_failure_without_credentials_in_error(self):
        env = {"MAIL_PROVIDER": "smtp", "SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587",
               "SMTP_USER": "smtp-user", "SMTP_PASSWORD": "private-password", "SMTP_USE_TLS": "1"}
        with patch.dict(os.environ, env), patch.object(email_auth_mailer.smtplib, "SMTP") as smtp:
            email_auth_mailer.send_verification_code("user@knu.ac.kr", "012345", "로그인")
            smtp.assert_called_once_with("smtp.example.com", 587, timeout=10)
            client = smtp.return_value.__enter__.return_value
            client.starttls.assert_called_once()
            client.login.assert_called_once_with("smtp-user", "private-password")
            message = client.send_message.call_args.args[0]
            self.assertIn("012345", message.get_body(preferencelist=("plain",)).get_content())
            self.assertIn("012345", message.get_body(preferencelist=("html",)).get_content())
            client.login.side_effect = OSError("private-password")
            with self.assertRaisesRegex(email_auth_mailer.MailDeliveryError, "^Verification email delivery failed[.]$"):
                email_auth_mailer.send_verification_code("user@knu.ac.kr", "012345", "로그인")
        with patch.dict(os.environ, {"MAIL_PROVIDER": "disabled"}):
            with self.assertRaisesRegex(email_auth_mailer.MailDeliveryError, "not configured"):
                email_auth_mailer.send_verification_code("user@knu.ac.kr", "012345", "로그인")

class MigrationTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("KNU_TEST_PGLITE_MODULE"), "Set KNU_TEST_PGLITE_MODULE to a local PGlite module")
    def test_migration_reapplies_and_auth_transactions_use_real_postgres(self):
        root = Path(__file__).resolve().parents[1]
        program = """
const { readFileSync } = require('node:fs');
const assert = require('node:assert/strict');
const { PGlite } = require(process.env.KNU_TEST_PGLITE_MODULE);
const db = new PGlite();
const sql = filename => readFileSync('supabase/migrations/' + filename, 'utf8');
const value = async (query, params) => (await db.query(query, params)).rows[0].value;

(async () => {
  await db.exec('create role anon; create role authenticated; create role service_role bypassrls;');
  await db.exec(sql('20260501000000_legacy_schema_baseline.sql'));
  await db.exec(sql('20260905052040_semester_membership.sql'));
  await db.exec(sql('20261101010000_local_password_login.sql'));
  await db.exec('create table public.term_officers (member_id bigint not null); grant select on public.term_officers to service_role');
  const migration = sql('20261120120000_knu_email_pin_auth.sql');
  await db.exec(migration);
  await db.exec(migration);
  const legacyLink = sql('20261121010000_allow_legacy_local_email_link.sql');
  await db.exec(legacyLink);
  await db.exec(legacyLink);
  assert.equal(await value("select has_table_privilege('anon','email_auth_codes','select') as value"), false);
  assert.equal(await value("select has_function_privilege('authenticated','decide_local_signup(bigint,bigint,boolean)','execute') as value"), false);
  assert.equal(await value("select has_function_privilege('service_role','decide_local_signup(bigint,bigint,boolean)','execute') as value"), true);
  for (const [role, allowed] of [['anon', false], ['authenticated', false], ['service_role', true]]) {
    assert.equal(await value("select has_function_privilege($1,'complete_email_signup(uuid,text,text,text,text,text,text)','execute') as value", [role]), allowed);
  }
  await db.exec("insert into seminar_terms (name,start_date,end_date,is_active,roster_initialized_at) values ('Test', current_date - 1, current_date + 1, true, now())");
  await db.exec("insert into members (id,name,student_id,role,account_status) values (101,'Officer','2026123001','officer','active'), (102,'Roster','2026 123002','member','active')");
  await assert.rejects(db.exec("update members set knu_email='a@other.test' where id=102"), { code: '23514' });
  await db.exec('set role service_role');
  const reserve = (id, email, purpose='signup', ip='hashed-ip') => value(
    'select reserve_email_auth_code($1, $2, $3, $4, $5) as value', [id, email, purpose, 'a'.repeat(64), ip]);
  const proof = async (id, email, purpose='signup') => {
    assert.equal(await reserve(id, email, purpose), true);
    assert.equal(await reserve('10000000-0000-0000-0000-000000000001', email, 'login'), false);
    await db.query('update email_auth_codes set consumed_at = now() where id=$1', [id]);
  };
  const enroll = (id, email, name, studentId, department, code) => value(
    'select complete_email_signup($1,$2,$3,$4,$5,null,$6) as value', [id,email,name,studentId,department,code]);
  const roster = '20000000-0000-0000-0000-000000000001';
  await proof(roster, 'roster@knu.ac.kr', 'login');
  assert.equal((await enroll(roster, 'roster@knu.ac.kr', 'Roster', '2026123002', '', '')).result, 'active');
  assert.equal(await value('select student_id as value from members where id=102'), '2026123002');
  assert.equal((await enroll(roster, 'roster@knu.ac.kr', 'Roster', '2026123002', '', '')).result, 'expired');
  await assert.rejects(db.exec("update members set knu_email='roster@knu.ac.kr' where id=101"), { code: '23505' });
  await assert.rejects(db.query("insert into member_credentials(member_id,login_id,password_hash) values (102,'legacy',$1)", ['$argon2id$test']), { code: '23505' });
  await assert.rejects(db.exec("insert into members(name, student_id, auth_provider) values ('Duplicate','2026 123002','local')"), { code: '23505' });

  const officer = '20000000-0000-0000-0000-000000000002';
  await proof(officer, 'officer@knu.ac.kr');
  assert.equal((await enroll(officer, 'officer@knu.ac.kr', 'Officer', '2026123001', '', '')).result, 'conflict');

  await db.exec(`
    insert into members (id,name,student_id,role,auth_provider,account_status,auth_session_version,social_id) values
      (104,'Legacy','2026123006','member','local','active',4,'converted'),
      (105,'Kakao','2026123007','member','kakao','active',2,'kakao_user'),
      (106,'Admin','2026123008','admin','local','active',0,null),
      (107,'Assignment','2026123009','member','local','active',0,null),
      (108,'Pending credential','2026123010','member','kakao','active',0,'pending_user'),
      (109,'System','2026123011','member','kakao','active',0,'system:test'),
      (110,'Blocked','2026123012','member','local','active',0,null);
    update members set member_status='blocked' where id=110;
    insert into member_credentials (member_id,login_id,password_hash,status) values
      (104,'legacy_user','$argon2id$test','active'),
      (106,'legacy_admin','$argon2id$test','active'),
      (107,'legacy_assignment','$argon2id$test','active'),
      (108,'legacy_pending','$argon2id$test','pending'),
      (110,'legacy_blocked','$argon2id$test','active');
    reset role;
    insert into term_officers (member_id) values (107);
    set role service_role;
  `);
  for (const [mid, name, sid, result] of [
    [104, 'Legacy', '2026123006', 'active'],
    [105, 'Kakao', '2026123007', 'active'],
    [106, 'Admin', '2026123008', 'conflict'],
    [107, 'Assignment', '2026123009', 'conflict'],
    [108, 'Pending credential', '2026123010', 'conflict'],
    [109, 'System', '2026123011', 'conflict'],
    [110, 'Blocked', '2026123012', 'conflict'],
    [111, 'Legacy', '2026123006', 'conflict'],
  ]) {
    const codeId = '30000000-0000-0000-0000-' + String(mid).padStart(12, '0');
    const email = 'migration' + mid + '@knu.ac.kr';
    await proof(codeId, email, 'login');
    assert.deepEqual(await enroll(codeId, email, name, sid, '', ''),
      result === 'active' ? { result, member_id: mid } : { result });
  }
  assert.deepEqual((await db.query(
    "select auth_session_version, knu_email from members where id in (104,105) order by id"
  )).rows, [
    { auth_session_version: 5, knu_email: 'migration104@knu.ac.kr' },
    { auth_session_version: 3, knu_email: 'migration105@knu.ac.kr' },
  ]);
  assert.equal(await value('select count(knu_email)::integer as value from members where id between 106 and 110'), 0);
  const ot = '20000000-0000-0000-0000-000000000003';
  await proof(ot, 'ot@knu.ac.kr');
  await value("select update_signup_configuration('ot_open',101,null,null,null,1) as value");
  const activated = await enroll(ot, 'ot@knu.ac.kr', 'OT', '2026123003', 'Dept', '');
  assert.equal(activated.result, 'active');
  assert.equal(await value('select status as value from seminar_term_members where member_id=$1', [activated.member_id]), 'active');
  assert.equal(await value('select roster_revision as value from seminar_terms'), 1);
  await db.exec("update signup_codes set auto_approve_until = now() - interval '1 minute'");
  const pending = '20000000-0000-0000-0000-000000000004';
  await proof(pending, 'pending@knu.ac.kr');
  assert.equal((await enroll(pending, 'pending@knu.ac.kr', 'Pending', '2026123004', 'Dept', '')).result, 'closed');
  const term = await value('select id as value from seminar_terms');
  await value("select update_signup_configuration('replace',101,'OPEN-SIGNUP-NO-CODE',$1,now()+interval '30 days',null) as value", [term]);
  await db.exec("reset role; update seminar_terms set start_date=current_date-6, end_date=current_date-1; set role service_role");
  assert.equal((await enroll(pending, 'pending@knu.ac.kr', 'Pending', '2026123004', 'Dept', '')).result, 'closed');
  await value("select update_signup_configuration('replace',101,'OPEN-SIGNUP-NO-CODE',null,now()+interval '30 days',null) as value");
  const requested = await enroll(pending, 'pending@knu.ac.kr', 'Pending', '2026123004', 'Dept', '');
  assert.equal(requested.result, 'pending');
  const approve = id => value('select decide_local_signup($1,101,true) as value', [id]);
  assert.equal(await approve(requested.member_id), 'success');
  assert.equal(await approve(requested.member_id), 'missing');
  assert.equal(await value('select status as value from seminar_term_members where member_id=$1', [requested.member_id]), 'active');
  assert.equal(await value('select roster_revision as value from seminar_terms'), 2);

  await db.exec("reset role; insert into members(id,name,student_id,member_status,is_active,account_status) values (103,'Inactive','2026123005','inactive',false,'active'); set role service_role");
  await db.query("insert into member_credentials(member_id,login_id,password_hash) values (103,'inactive',$1)", ['$argon2id$test']);
  assert.equal(await approve(103), 'inactive');
  assert.equal(await value('select is_active as value from members where id=103'), false);
  await db.close();
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run(["node", "-e", program], cwd=root, capture_output=True, encoding="utf-8", timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
