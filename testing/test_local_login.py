import importlib
import os
import unittest
from unittest.mock import patch

from testing._fake_supabase import FakeQuery, FakeSupabase

os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
os.environ.setdefault("FLASK_SECRET_KEY", "render-smoke-only")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:9")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "render-smoke-only")

GOOD_PW = "Hobanu-reads-1984"
OFFICER_PW = "Officer-long-pass-77"


class IdFakeSupabase(FakeSupabase):
    """FakeSupabase that assigns identity ids like Postgres does."""

    def table(self, table_name):
        query = super().table(table_name)
        original = query.execute
        client = self

        def execute():
            if query.operation == "insert" and isinstance(query.payload, dict) and "id" not in query.payload \
                    and table_name != "member_credentials":
                existing = [r.get("id") or 0 for r in client.rows.get(table_name, []) if isinstance(r.get("id"), int)]
                query.payload["id"] = max(existing + [100]) + 1
            if query.operation == "insert" and table_name == "member_credentials" and isinstance(query.payload, dict):
                taken = {r["login_id"] for r in client.rows.get(table_name, [])}
                if query.payload.get("login_id") in taken:
                    raise RuntimeError("duplicate key value violates unique constraint")
            return original()

        query.execute = execute
        return query


def member(mid, name, sid, **extra):
    row = dict(id=mid, name=name, student_id=sid, department="국문", role="member", is_active=True,
               member_status="active", account_status="active", social_id=None, auth_provider=None,
               auth_session_version=0, profile_pic="")
    row.update(extra)
    return row


def rows():
    return {
        "members": [
            member(1, "운영자", "2020000001", role="admin", social_id="kakao-1", auth_provider="kakao"),
            member(2, "김카카오", "2021000002", social_id="kakao-2", auth_provider="kakao"),
            member(3, "이명부", "2022000003"),
            member(4, "박운영", "2019000004", role="officer", social_id="kakao-4", auth_provider="kakao"),
            member(5, "최회원", "2023000005"),
        ],
        "seminar_terms": [dict(id="t-1", name="2026-2학기", start_date="2026-09-01", end_date="2099-12-31", is_active=True)],
        "term_officers": [],
        "signup_codes": [],
        "member_credentials": [],
        "account_setup_tokens": [],
        "auth_failures": [],
        "notifications": [],
    }


class LocalLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module("app")
        cls.real = cls.module.supabase

    def setUp(self):
        self.db = IdFakeSupabase(rows())
        self.patch = patch.object(self.real, "table", self.db.table)
        self.patch.start()
        self.module.app.config.update(TESTING=True)
        self.client = self.module.app.test_client()
        self.set_code("BOOK2026")

    def tearDown(self):
        self.patch.stop()

    # helpers
    def set_code(self, code):
        self.db.rows["signup_codes"] = [dict(id=1, code=code, term_id="t-1", created_at="2026-09-01T00:00:00+00:00", revoked_at=None)]

    def csrf(self, client=None):
        client = client or self.client
        with client.session_transaction() as s:
            s["sensitive_csrf"] = "csrf"
        return "csrf"

    def signup(self, **over):
        data = dict(signup_code="book2026", name="정신입", student_id="2026123456", department="철학과",
                    login_id="newbie_01", password=GOOD_PW, password_confirm=GOOD_PW)
        data.update(over)
        data["csrf_token"] = self.csrf()
        return self.client.post("/signup", data=data)

    def login(self, login_id, password, client=None):
        client = client or self.client
        return client.post("/login/password", data=dict(login_id=login_id, password=password, remember="1",
                                                        csrf_token=self.csrf(client)))

    def as_member(self, mid, provider="kakao", client=None, version=0):
        client = client or self.client
        with client.session_transaction() as s:
            s.update(user_id=mid, user_role=next(m["role"] for m in self.db.rows["members"] if m["id"] == mid),
                     user_name="x", auth_provider=provider, auth_session_version=version, sensitive_csrf="csrf")

    def admin_post(self, url, body=None):
        return self.client.post(url, json=body or {}, headers={"X-App-CSRF": "csrf"})

    def cred(self, login_id):
        return next((c for c in self.db.rows["member_credentials"] if c["login_id"] == login_id), None)

    def member(self, mid):
        return next(m for m in self.db.rows["members"] if m["id"] == mid)

    # tests
    def test_login_page_is_id_password_first_with_kakao_for_conversion(self):
        html = self.client.get("/login").get_data(as_text=True)
        self.assertIn('action="/login/password"', html)
        self.assertIn('name="csrf_token"', html)
        self.assertIn("기존 회원 전환용", html)
        self.assertIn('href="/signup', html)
        self.assertLess(html.index("/login/password"), html.index("/login/kakao"))

    def test_signup_requires_current_code_and_waits_for_approval(self):
        self.db.rows["signup_codes"] = []
        self.assertEqual(self.signup().status_code, 403)
        self.set_code("BOOK2026")
        self.assertEqual(self.signup(signup_code="WRONG1").status_code, 400)
        self.assertEqual(len(self.db.rows["auth_failures"]), 1)
        result = self.signup()
        self.assertEqual(result.status_code, 200, result.get_data(as_text=True)[:400])
        cred = self.cred("newbie_01")
        self.assertEqual(cred["status"], "pending")
        self.assertTrue(cred["password_hash"].startswith("$argon2id$"))
        self.assertNotIn(GOOD_PW, str(self.db.rows))
        new = self.member(cred["member_id"])
        self.assertEqual((new["account_status"], new["member_status"], new["is_active"]), ("pending", "inactive", False))
        self.assertNotIn("email", new)
        pending = self.login("newbie_01", GOOD_PW)
        self.assertEqual(pending.status_code, 403)
        self.assertIn("승인 대기", pending.get_data(as_text=True))

    def test_expired_term_code_stops_signup(self):
        self.db.rows["seminar_terms"][0]["end_date"] = "2020-01-01"
        self.assertEqual(self.signup().status_code, 403)

    def test_signup_rejects_common_and_identity_passwords(self):
        for pw in ("password123", "qwer1234", "aaaaaaaaaa", "newbie_01xyz!", "short1!"):
            result = self.signup(password=pw, password_confirm=pw)
            self.assertEqual(result.status_code, 400, pw)
        self.assertEqual(self.db.rows["member_credentials"], [])

    def test_signup_links_roster_row_but_not_kakao_or_officer_rows(self):
        self.signup(name="이명부", student_id="2022000003", login_id="roster_3")
        self.assertEqual(self.cred("roster_3")["member_id"], 3)
        kakao = self.signup(name="김카카오", student_id="2021000002", login_id="kakao_2")
        self.assertEqual(kakao.status_code, 409)
        self.assertIn("기존 회원 전환", kakao.get_data(as_text=True))
        self.member(5)["role"] = "officer"
        self.assertEqual(self.signup(name="최회원", student_id="2023000005", login_id="officer_5").status_code, 409)
        self.assertEqual(self.signup(login_id="roster_3").status_code, 400)  # duplicate id

    def test_officer_approves_then_member_logs_in_and_reaches_wiki_identity(self):
        self.signup()
        cred = self.cred("newbie_01")
        self.as_member(4)
        self.assertEqual(self.admin_post(f"/api/admin/members/{cred['member_id']}/approve-login").status_code, 200)
        approved = self.member(cred["member_id"])
        self.assertEqual((approved["account_status"], approved["member_status"], approved["auth_provider"]), ("active", "active", "local"))
        fresh = self.module.app.test_client()
        result = self.login("newbie_01", GOOD_PW, client=fresh)
        self.assertEqual(result.status_code, 302)
        with fresh.session_transaction() as s:
            self.assertEqual(s["auth_provider"], "local")
            self.assertTrue(s.permanent)
            identity = dict(s)
        from wiki_access import wiki_access
        access = wiki_access(self.real, identity)
        self.assertIsNotNone(access)
        from minipc_security import session_login_current
        self.assertTrue(session_login_current(approved, identity))
        self.assertEqual(self.module.app.permanent_session_lifetime.days, 30)

    def test_reject_removes_new_pending_member(self):
        self.signup()
        mid = self.cred("newbie_01")["member_id"]
        self.as_member(4)
        self.assertEqual(self.admin_post(f"/api/admin/members/{mid}/reject-login").status_code, 200)
        self.assertIsNone(self.cred("newbie_01"))
        self.assertFalse(any(m["id"] == mid for m in self.db.rows["members"]))

    def test_regular_member_cannot_use_officer_tools(self):
        self.signup()
        mid = self.cred("newbie_01")["member_id"]
        self.as_member(3)
        for url in (f"/api/admin/members/{mid}/approve-login", "/api/admin/signup-code", f"/api/admin/members/5/login-link"):
            self.assertIn(self.admin_post(url, {"action": "set"}).status_code, (302, 403), url)
        self.assertEqual(self.cred("newbie_01")["status"], "pending")

    def test_lockout_after_repeated_failures_even_with_right_password(self):
        self.signup()
        mid = self.cred("newbie_01")["member_id"]
        self.as_member(4)
        self.admin_post(f"/api/admin/members/{mid}/approve-login")
        fresh = self.module.app.test_client()
        for _ in range(5):
            self.assertEqual(self.login("newbie_01", "wrong-password-x", client=fresh).status_code, 401)
        locked = self.login("newbie_01", GOOD_PW, client=fresh)
        self.assertEqual(locked.status_code, 429)
        unknown = self.login("nobody_here", "whatever-123", client=fresh)
        self.assertEqual(unknown.status_code, 401)
        self.assertIn("아이디 또는 비밀번호", unknown.get_data(as_text=True))

    def test_officer_reset_link_is_one_time_and_ends_old_sessions(self):
        self.signup()
        mid = self.cred("newbie_01")["member_id"]
        self.as_member(4)
        self.admin_post(f"/api/admin/members/{mid}/approve-login")
        old_device = self.module.app.test_client()
        self.login("newbie_01", GOOD_PW, client=old_device)
        self.as_member(4)
        issued = self.admin_post(f"/api/admin/members/{mid}/login-link").get_json()
        self.assertEqual(issued["kind"], "reset")
        path = "/account/setup/" + issued["url"].rsplit("/", 1)[1]
        stored = self.db.rows["account_setup_tokens"][-1]
        self.assertNotIn(issued["url"].rsplit("/", 1)[1], str(stored))
        other = self.module.app.test_client()
        page = other.get(path)
        self.assertEqual(page.status_code, 200)
        self.assertIn("newbie_01", page.get_data(as_text=True))
        new_pw = "Second-strong-pass-42"
        done = other.post(path, data=dict(password=new_pw, password_confirm=new_pw, csrf_token=self.csrf(other)))
        self.assertEqual(done.status_code, 302)
        self.assertEqual(other.get(path).status_code, 404)
        self.assertEqual(old_device.get("/mypage").status_code, 302)  # old session ended
        self.assertEqual(self.login("newbie_01", GOOD_PW, client=other).status_code, 401)
        self.assertEqual(self.login("newbie_01", new_pw, client=other).status_code, 302)

    def test_officer_cannot_issue_link_for_admin_but_can_for_member(self):
        self.as_member(4)
        self.assertEqual(self.admin_post("/api/admin/members/1/login-link").status_code, 403)
        result = self.admin_post("/api/admin/members/3/login-link")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.get_json()["kind"], "setup")
        self.assertTrue(result.get_json()["url"].startswith("https://") or "/account/setup/" in result.get_json()["url"])

    def test_kakao_member_converts_and_keeps_row(self):
        self.as_member(2, provider="kakao")
        self.assertEqual(self.client.get("/account/convert").status_code, 200)
        result = self.client.post("/account/convert", data=dict(login_id="kakao_two", password=GOOD_PW,
                                                                password_confirm=GOOD_PW, csrf_token="csrf"))
        self.assertEqual(result.status_code, 302)
        self.assertEqual(self.cred("kakao_two")["member_id"], 2)
        self.assertEqual(self.cred("kakao_two")["status"], "active")
        self.assertEqual(self.member(2)["auth_provider"], "local")
        self.assertEqual(self.member(2)["social_id"], "kakao-2")
        with self.client.session_transaction() as s:
            self.assertEqual(s["auth_provider"], "local")
        from minipc_security import session_login_current
        self.assertFalse(session_login_current(self.member(2), {"auth_provider": "kakao"}))

    def test_officers_need_longer_passwords(self):
        self.as_member(4, provider="kakao")
        short = "Readable-pw9"[:11]
        result = self.client.post("/account/convert", data=dict(login_id="officer_4", password=short,
                                                                password_confirm=short, csrf_token="csrf"))
        self.assertEqual(result.status_code, 400)
        self.assertIn("12자", result.get_data(as_text=True))
        ok = self.client.post("/account/convert", data=dict(login_id="officer_4", password=OFFICER_PW,
                                                            password_confirm=OFFICER_PW, csrf_token="csrf"))
        self.assertEqual(ok.status_code, 302)

    def test_signup_code_rotation_by_officer(self):
        self.as_member(4)
        result = self.admin_post("/api/admin/signup-code", {"action": "set", "code": "new code 2026"})
        self.assertEqual(result.get_json()["code"], "NEWCODE2026")
        active = [c for c in self.db.rows["signup_codes"] if not c.get("revoked_at")]
        self.assertEqual([c["code"] for c in active], ["NEWCODE2026"])
        self.assertEqual(self.signup(signup_code="book2026").status_code, 400)
        self.admin_post("/api/admin/signup-code", {"action": "revoke"})
        self.assertEqual(self.signup(signup_code="newcode2026").status_code, 403)

    def test_member_list_shows_code_pending_and_login_kind(self):
        self.signup()
        self.as_member(1)
        html = self.client.get("/admin/members").get_data(as_text=True)
        self.assertIn("가입 코드 · 가입 승인", html)
        self.assertIn("BOOK2026", html)
        self.assertIn("승인 대기 1명", html)
        self.assertIn("newbie_01", html)
        self.assertIn("카카오 (전환 전)", html)
        self.assertIn("로그인 링크", html)

    def test_csrf_required_on_login_and_signup(self):
        self.assertEqual(self.client.post("/login/password", data=dict(login_id="a", password="b")).status_code, 403)
        self.assertEqual(self.client.post("/signup", data=dict(signup_code="BOOK2026")).status_code, 403)


if __name__ == "__main__":
    unittest.main()
