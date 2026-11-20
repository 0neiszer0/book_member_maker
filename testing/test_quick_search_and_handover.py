"""Unit tests for LMS quick search (Ctrl+K) and no-login officer handover surveys."""
import importlib.util
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from officer_handover import OFFICER_HANDOVER_ROLES
from testing._fake_supabase import FakeSupabase
from testing.test_home_overview import fixture

os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
os.environ.setdefault("FLASK_SECRET_KEY", "ci-test-only")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:9")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "ci-test-only")

ROOT = Path(__file__).resolve().parents[1]
FORM_TOKEN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
CLOSED_TOKEN = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
MISSING_TOKEN = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


class QuickSearchAndHandoverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeSupabase()
        spec = importlib.util.spec_from_file_location("_quick_search_handover_app", ROOT / "app.py")
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        with patch("supabase.create_client", return_value=cls.fake):
            spec.loader.exec_module(cls.module)

    def setUp(self):
        rows = fixture()
        rows["members"][0].update(gender="F", email="member@example.test", role="member")
        rows["members"][1].update(gender="M", email="admin@example.test", role="admin")
        rows["officer_handover_forms"] = [
            {
                "id": "form-open",
                "share_token": FORM_TOKEN,
                "title": "2026-2학기 임원진 인수인계",
                "term_label": "2026-2학기",
                "status": "open",
                "created_by": 2,
                "created_at": "2026-11-20T01:00:00+00:00",
                "updated_at": "2026-11-20T01:00:00+00:00",
            },
            {
                "id": "form-closed",
                "share_token": CLOSED_TOKEN,
                "title": "2026-1학기 임원진 인수인계",
                "term_label": "2026-1학기",
                "status": "closed",
                "created_by": 2,
                "created_at": "2026-06-20T01:00:00+00:00",
                "updated_at": "2026-06-20T01:00:00+00:00",
            },
        ]
        rows["officer_handover_responses"] = []
        self.fake.rows = rows
        self.fake.calls.clear()
        self.module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = self.module.app.test_client()

    def login(self, role="member", user_id=None, csrf="test-csrf"):
        if user_id is None:
            user_id = 2 if role in ("admin", "officer") else 1
        if role == "officer":
            self.fake.rows["members"][1]["role"] = "officer"
        with self.client.session_transaction() as state:
            state.clear()
            state.update(
                user_id=user_id,
                user_role=role,
                user_name="테스트 회원",
                sensitive_csrf=csrf,
            )

    def _extract_quick_search_items(self, html):
        self.assertIn("data-lms-quick-search", html)
        match = re.search(
            r'<script id="lms-quick-search-items" type="application/json">(.*?)</script>',
            html,
            re.S,
        )
        self.assertIsNotNone(match)
        return json.loads(match.group(1))

    def _public_csrf(self, path):
        html = self.client.get(path).get_data(as_text=True)
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.assertIsNotNone(match)
        return match.group(1), html

    # --- 1. Quick Search Tests ---
    def test_quick_search_guest_only_sees_public_items(self):
        resp = self.client.get("/club-room")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("quick_search.js", html)
        self.assertIn("quick_search.css", html)
        items = self._extract_quick_search_items(html)
        urls = {item["url"] for item in items}
        self.assertIn("/", urls)
        self.assertIn("/club-room", urls)
        self.assertNotIn("/mypage", urls)
        self.assertNotIn("/admin/members", urls)
        self.assertNotIn("/making_team", urls)
        self.assertNotIn("/admin/handover", urls)

    def test_quick_search_member_excludes_staff_items(self):
        self.login("member")
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        items = self._extract_quick_search_items(resp.get_data(as_text=True))
        urls = {item["url"] for item in items}
        self.assertIn("/seminars", urls)
        self.assertIn("/mypage", urls)
        self.assertIn("/my/term_attendance", urls)
        self.assertNotIn("/admin/members", urls)
        self.assertNotIn("/making_team", urls)
        self.assertNotIn("/admin/handover", urls)
        self.assertNotIn("/admin/dashboard", urls)

    def test_quick_search_admin_and_officer_include_staff_items(self):
        for role in ("admin", "officer"):
            with self.subTest(role=role):
                self.login(role)
                resp = self.client.get("/")
                self.assertEqual(resp.status_code, 200)
                items = self._extract_quick_search_items(resp.get_data(as_text=True))
                urls = {item["url"] for item in items}
                for expected_url in (
                    "/admin/dashboard",
                    "/admin/seminars",
                    "/making_team",
                    "/admin/term_attendance",
                    "/admin/members",
                    "/admin/term_members",
                    "/admin/engagement",
                    "/admin/special_events",
                    "/records",
                    "/admin/handover",
                ):
                    self.assertIn(expected_url, urls)

    # --- 2. Public Handover Form Tests ---
    def test_public_handover_renders_exact_9_roles_without_login(self):
        path = f"/handover/{FORM_TOKEN}"
        resp = self.client.get(path)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Cache-Control"), "no-store")
        html = resp.get_data(as_text=True)
        self.assertIn("비밀번호·계좌번호·개인 전화번호는 적지 마세요.", html)
        expected_roles = (
            "회장", "부회장", "총무",
            "기획부장", "홍보부장", "학술지원부장",
            "기획부원", "홍보부원", "학술지원부원",
        )
        self.assertEqual(OFFICER_HANDOVER_ROLES, expected_roles)
        for role in expected_roles:
            self.assertIn(f'value="{role}"', html)
        self.assertEqual(self.client.get(f"/handover/{MISSING_TOKEN}").status_code, 404)

    def test_public_handover_rejects_missing_or_tampered_csrf(self):
        path = f"/handover/{FORM_TOKEN}"
        token, _ = self._public_csrf(path)
        self.assertTrue(token.startswith("h1."))
        version, issued, mac = token.split(".")
        bad_tokens = [
            "",
            "h1.invalid",
            f"{version}.{issued}.{'0' * len(mac)}",
            f"{version}.{int(issued) - 13 * 3600}.{mac}",
        ]
        for bad in bad_tokens:
            with self.subTest(bad=bad):
                resp = self.client.post(
                    path,
                    data={"csrf_token": bad, "role_name": "회장", "core_tasks": "핵심 업무"},
                )
                self.assertEqual(resp.status_code, 403)
        self.assertEqual(self.fake.rows["officer_handover_responses"], [])

    def test_public_handover_rejects_honeypot_and_invalid_inputs(self):
        path = f"/handover/{FORM_TOKEN}"
        token, _ = self._public_csrf(path)

        honeypot = self.client.post(
            path,
            data={
                "csrf_token": token,
                "website": "https://spam.example",
                "role_name": "회장",
                "core_tasks": "업무",
            },
        )
        self.assertEqual(honeypot.status_code, 400)
        self.assertEqual(self.fake.rows["officer_handover_responses"], [])

        invalid_role = self.client.post(
            path,
            data={
                "csrf_token": token,
                "role_name": "외부인",
                "core_tasks": "업무",
            },
        )
        self.assertEqual(invalid_role.status_code, 400)
        self.assertEqual(self.fake.rows["officer_handover_responses"], [])

        empty_tasks = self.client.post(
            path,
            data={
                "csrf_token": token,
                "role_name": "총무",
                "core_tasks": "   ",
            },
        )
        self.assertEqual(empty_tasks.status_code, 400)
        self.assertEqual(self.fake.rows["officer_handover_responses"], [])

    def test_public_handover_accepts_cookie_less_valid_submission(self):
        path = f"/handover/{FORM_TOKEN}"
        token, _ = self._public_csrf(path)
        fresh_client = self.module.app.test_client()
        resp = fresh_client.post(
            path,
            data={
                "csrf_token": token,
                "role_name": "학술지원부장",
                "author_name": "김철수",
                "term_cohort": "26-2학기",
                "core_tasks": "1) 세미나 도서 선정\n2) 발제문 정리\n3) 행사 지원",
                "hardships_and_tips": "초반 일정 조율이 중요합니다.",
                "assets_and_links": "공유 드라이브 /학술지원부 폴더",
                "common_issues": "발제 마감 리마인드 필수",
                "next_officer_note": "파이팅!",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Cache-Control"), "no-store")
        self.assertIn("인수인계 설문을 제출했습니다.", resp.get_data(as_text=True))
        stored = self.fake.rows["officer_handover_responses"]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["role_name"], "학술지원부장")
        self.assertEqual(stored[0]["author_name"], "김철수")
        self.assertEqual(stored[0]["form_id"], "form-open")

    def test_public_handover_rejects_closed_form(self):
        path = f"/handover/{CLOSED_TOKEN}"
        token, html = self._public_csrf(path)
        self.assertIn("현재 설문이 마감되어", html)
        resp = self.client.post(
            path,
            data={"csrf_token": token, "role_name": "회장", "core_tasks": "마감 후 제출"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("마감", resp.get_data(as_text=True))
        self.assertEqual(self.fake.rows["officer_handover_responses"], [])

    # --- 3. Admin Handover Endpoints & Auth/CSRF Tests ---
    def test_admin_handover_endpoints_enforce_auth_and_csrf(self):
        # Guest cannot access admin endpoints
        self.assertEqual(self.client.get("/admin/handover").status_code, 302)
        self.assertEqual(self.client.post("/api/admin/handover/create", json={"title": "x"}).status_code, 401)

        # Member gets 403 on API endpoints and redirect on /admin/handover
        self.login("member")
        self.assertNotEqual(self.client.get("/admin/handover").status_code, 200)
        self.assertEqual(
            self.client.post(
                "/api/admin/handover/create",
                headers={"X-App-CSRF": "test-csrf"},
                json={"title": "테스트"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/admin/handover/form-open/status",
                headers={"X-App-CSRF": "test-csrf"},
                json={"status": "closed"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/admin/handover/responses/resp-1/delete",
                headers={"X-App-CSRF": "test-csrf"},
            ).status_code,
            403,
        )

        # Admin without X-App-CSRF gets 403
        self.login("admin")
        self.assertEqual(
            self.client.post("/api/admin/handover/create", json={"title": "테스트"}).status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/admin/handover/form-open/status", json={"status": "closed"}).status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/admin/handover/responses/resp-1/delete").status_code,
            403,
        )

    def test_admin_handover_create_toggle_export_and_delete(self):
        self.login("admin")
        headers = {"X-App-CSRF": "test-csrf"}

        created = self.client.post(
            "/api/admin/handover/create",
            headers=headers,
            json={"title": "2027-1학기 임원진 인수인계", "term_label": "2027-1학기"},
        )
        self.assertEqual(created.status_code, 200)
        payload = created.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("/handover/", payload["share_url"])
        new_form_id = payload["form"]["id"]

        # Add response to form-open and check /admin/handover rendering + wiki export
        self.fake.rows["officer_handover_responses"].append(
            {
                "id": "resp-1",
                "form_id": "form-open",
                "role_name": "기획부원",
                "author_name": "이영희",
                "term_cohort": "16기",
                "core_tasks": "OT 레크리에이션 기획",
                "hardships_and_tips": "사전 리허설 권장",
                "assets_and_links": "드라이브/기획부",
                "common_issues": "마이크 배터리 점검",
                "next_officer_note": "즐겁게 준비하세요",
                "created_at": "2026-11-20T02:00:00+00:00",
            }
        )
        admin_page = self.client.get("/admin/handover")
        self.assertEqual(admin_page.status_code, 200)
        html = admin_page.get_data(as_text=True)
        self.assertIn("2027-1학기 임원진 인수인계", html)
        self.assertIn("== 기획부원 ==", html)
        self.assertIn("OT 레크리에이션 기획", html)

        # Toggle status
        toggled = self.client.post(
            f"/api/admin/handover/{new_form_id}/status",
            headers=headers,
            json={},
        )
        self.assertEqual(toggled.status_code, 200)
        self.assertEqual(toggled.get_json()["status"], "closed")

        # Delete response
        deleted = self.client.post(
            "/api/admin/handover/responses/resp-1/delete",
            headers=headers,
        )
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(self.fake.rows["officer_handover_responses"], [])

    # --- 4. Migration Contract Test ---
    def test_migration_sql_exists_and_is_idempotent(self):
        sql_path = ROOT / "supabase" / "migrations" / "20261120120500_officer_handover_surveys.sql"
        self.assertTrue(sql_path.exists())
        sql = sql_path.read_text(encoding="utf-8")
        self.assertIn("create table if not exists public.officer_handover_forms", sql.lower())
        self.assertIn("create table if not exists public.officer_handover_responses", sql.lower())
        self.assertIn("create index if not exists", sql.lower())
        self.assertIn("rollback:", sql.lower())


if __name__ == "__main__":
    unittest.main()
