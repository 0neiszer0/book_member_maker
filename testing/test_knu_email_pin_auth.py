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
            if len(same_id) != 1 or target["name"].strip() != p_name or target["role"] != "member" \
                    or target["account_status"] != "active" or not target["is_active"] \
                    or target["member_status"] in ("inactive", "blocked", "pending") or target.get("knu_email") \
                    or any(c["member_id"] == target["id"] for c in self.rows["member_credentials"]):
                return {"result": "conflict"}
            target.update(fields, student_id=p_student_id)
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

    def test_non_knu_email_and_csrf_rejection(self):
        self.assertEqual(self.client.get("/login").headers["Cache-Control"], "no-store")
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
        self.db.rows["member_credentials"].append(dict(member_id=3, login_id="legacy_user", status="active"))
        self.assertEqual(self.enroll(name="이명부", student_id="2022000003").status_code, 409)
        self.assertEqual(self.enroll(name="다른이름", student_id="2022000003").status_code, 409)
        self.assertEqual(len(self.db.rows["members"]), 5)

    def test_pin_lock_reset_revokes_old_sessions_and_restores_login(self):
        self.linked(pin="123456")
        old = self.app.test_client()
        self.assertEqual(self.pin(client=old).status_code, 302)
        for i in range(5):
            self.assertEqual(self.pin(pin="654321").status_code, 429 if i == 4 else 401)
        response = self.pin()
        self.assertEqual(response.status_code, 429)
        self.assertIn("PIN을 잊으셨나요", response.get_data(as_text=True))
        self.assertEqual(local_auth.parse_time(self.member(3)["pin_locked_until"]) - self.now, timedelta(minutes=15))
        self.send(purpose="pin_reset")
        self.assertEqual(self.verify().location, "/account/pin/reset")
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)
        self.assertEqual(self.client.get("/account/pin/reset").status_code, 200)
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
        self.assertEqual(self.client.get("/account/pin/setup").status_code, 200)
        self.assertEqual(self.form("/account/pin/setup", pin="123456", pin_confirm="123456").status_code, 302)
        self.member(3).update(pin_failed_attempts=5, pin_locked_until=local_auth.iso(self.now - timedelta(seconds=1)))
        fresh = self.app.test_client()
        self.assertEqual(self.pin(pin="654321", client=fresh).status_code, 401)
        self.assertEqual(self.member(3)["pin_failed_attempts"], 1)
        self.assertIsNone(self.member(3)["pin_locked_until"])
        self.assertEqual(self.pin(client=fresh).status_code, 302)
        self.assert_session(3, fresh)

    def test_staff_cannot_use_pin_and_staff_promotion_ends_pin_session(self):
        for mid, user in ((1, "admin"), (4, "officer")):
            email = user + "@knu.ac.kr"
            self.linked(mid, "123456", email)
            response = self.pin(identifier=email)
            self.assertEqual(response.status_code, 403)
            self.assertIn(local_auth.PIN_STAFF, response.get_data(as_text=True))
            self.assertEqual(self.send(email).status_code, 200)
            self.assertEqual(self.verify().status_code, 302)
            self.assert_session(mid)
        self.linked(pin="123456")
        old = self.app.test_client()
        self.assertEqual(self.pin(client=old).status_code, 302)
        self.member(3)["role"] = "officer"
        self.assertEqual(old.get("/admin/members").status_code, 302)
        self.member(3)["role"] = "member"
        self.assertEqual(self.pin(client=old).status_code, 302)
        self.db.rows["term_officers"].append(dict(term_id="t-1", member_id=3))
        self.assertEqual(old.get("/mypage").status_code, 303)
        self.assertEqual(self.pin(client=old).status_code, 403)

    def test_provisioned_staff_email_gets_verified_only_after_otp(self):
        staff = self.member(4)
        staff["knu_email"] = "officer@knu.ac.kr"
        self.assertEqual(self.pin(identifier=staff["knu_email"]).status_code, 403)
        self.assertIsNone(staff.get("knu_email_verified_at"))
        self.assertEqual(self.send(staff["knu_email"]).status_code, 200)
        self.assertEqual(self.verify().location, "/admin/dashboard")
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
        for provider, key_name, endpoint in (
            ("resend", "RESEND_API_KEY", "https://api.resend.com/emails"),
            ("brevo", "BREVO_API_KEY", "https://api.brevo.com/v3/smtp/email"),
        ):
            with self.subTest(provider=provider), patch.dict(os.environ, {"MAIL_PROVIDER": provider, key_name: "secret"}), \
                    patch.object(email_auth_mailer.requests, "post") as post:
                email_auth_mailer.send_verification_code("user@knu.ac.kr", "012345", "로그인")

                self.assertEqual(post.call_args.args, (endpoint,))
                self.assertEqual(post.call_args.kwargs["timeout"], 10)
                self.assertIn("012345", str(post.call_args.kwargs["json"]))

    def test_smtp_tls_and_failure_without_credentials_in_error(self):
        env = {"MAIL_PROVIDER": "smtp", "SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587",
               "SMTP_USER": "smtp-user", "SMTP_PASSWORD": "private-password", "SMTP_USE_TLS": "1"}
        with patch.dict(os.environ, env), patch.object(email_auth_mailer.smtplib, "SMTP") as smtp:
            email_auth_mailer.send_verification_code("user@knu.ac.kr", "012345", "로그인")
            smtp.assert_called_once_with("smtp.example.com", 587, timeout=10)
            client = smtp.return_value.__enter__.return_value
            client.starttls.assert_called_once()
            client.login.assert_called_once_with("smtp-user", "private-password")
            self.assertIn("012345", client.send_message.call_args.args[0].get_content())
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
  assert.equal(await value("select has_table_privilege('anon','email_auth_codes','select') as value"), false);
  assert.equal(await value("select has_function_privilege('authenticated','decide_local_signup(bigint,bigint,boolean)','execute') as value"), false);
  assert.equal(await value("select has_function_privilege('service_role','decide_local_signup(bigint,bigint,boolean)','execute') as value"), true);
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
