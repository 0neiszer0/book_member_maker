import importlib
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup
from testing._fake_supabase import FakeSupabase

os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
os.environ.setdefault("FLASK_SECRET_KEY", "wave3-cta-members-test")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:9")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "wave3-cta-members-test")

ROOT = Path(__file__).resolve().parents[1]


class Wave3CtaAndMembersUiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_module = importlib.import_module("app")

    def setUp(self):
        self.db = FakeSupabase({
            "members": [
                {
                    "id": 1,
                    "name": "테스트 관리자",
                    "role": "admin",
                    "is_active": True,
                    "member_status": "active",
                    "account_status": "active",
                    "student_id": "2026000001",
                    "department": "국어국문학과",
                    "recruiting_class": 10,
                    "gender": "W",
                    "knu_email": "admin@knu.ac.kr",
                    "auth_provider": "local",
                },
                {
                    "id": 2,
                    "name": "테스트 운영진",
                    "role": "officer",
                    "is_active": True,
                    "member_status": "active",
                    "account_status": "active",
                    "student_id": "2026000002",
                    "department": "철학과",
                    "recruiting_class": 11,
                    "gender": "M",
                    "auth_provider": "kakao",
                },
                {
                    "id": 3,
                    "name": "대기 신청자",
                    "role": "member",
                    "is_active": False,
                    "member_status": "active",
                    "account_status": "pending",
                    "student_id": "2026000003",
                    "department": "사학과",
                    "created_at": "2026-11-20T10:00:00Z",
                },
            ],
            "member_credentials": [
                {
                    "member_id": 3,
                    "login_id": "pending01",
                    "status": "pending",
                    "signup_name": "대기 신청자",
                    "signup_student_id": "2026000003",
                    "signup_department": "사학과",
                    "created_at": "2026-11-20T10:00:00Z",
                }
            ],
            "signup_codes": [
                {
                    "id": 1,
                    "code": "BOOK2026",
                    "is_open": False,
                    "revoked_at": None,
                    "expires_at": None,
                    "auto_approve_until": "2099-12-31T12:00:00Z",
                }
            ],
            "history": [
                {
                    "id": "h1",
                    "date": "2026-11-19",
                    "book_title": "겨울 책",
                    "groups": [["테스트 관리자", "테스트 운영진"]],
                    "present": ["테스트 관리자", "테스트 운영진"],
                    "facilitators": ["테스트 관리자"],
                }
            ],
            "seminar_terms": [
                {
                    "id": "term-1",
                    "name": "2026-2학기",
                    "start_date": "2026-09-01",
                    "end_date": "2026-12-20",
                    "is_active": True,
                    "share_token": "term-share-1",
                }
            ],
            "seminar_weeks": [
                {
                    "id": "week-1",
                    "term_id": "term-1",
                    "week_start": "2099-11-16",
                    "book_title": "테스트 도서",
                }
            ],
            "seminar_sessions": [
                {
                    "id": "sess-1",
                    "term_id": "term-1",
                    "seminar_week_id": "week-1",
                    "day_type": "thu",
                    "meeting_date": "2099-11-19",
                    "is_active": True,
                    "planned_member_ids": [1, 2],
                    "actual_member_ids": [],
                }
            ],
            "topic_events": [],
            "brick_books": [],
            "brick_book_sessions": [],
            "brick_session_members": [],
            "study_groups": [],
            "study_group_sessions": [],
            "study_session_members": [],
            "special_events": [],
            "special_event_attendees": [],
            "genres": [],
            "group_pair_restrictions": [],
        })
        patcher = patch.object(self.app_module, "supabase", self.db)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app_module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = self.app_module.app.test_client()

    def login(self, user_id, role):
        with self.client.session_transaction() as state:
            state.clear()
            state.update(user_id=user_id, user_role=role, user_name=f"user-{user_id}")

    def test_public_landing_minimalism(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        dom = BeautifulSoup(html, "html.parser")

        header_nav = dom.select_one("header.mast nav")
        self.assertIsNotNone(header_nav)
        nav_links = [(a.get_text(strip=True), a.get("href")) for a in header_nav.select("a")]
        self.assertEqual(nav_links, [
            ("역대 아카이브", "/archive"),
            ("세미나 전 자료", "/pre-seminar"),
            ("로그인", "/login"),
        ])

        self.assertIsNone(dom.select_one("header.mast [data-lms-quick-search]"))
        self.assertIsNone(dom.select_one("#lms-quick-search-items"))
        self.assertIsNotNone(dom.select_one(".actions a[href='/archive']"))
        self.assertIsNone(dom.select_one(".actions a[href='/login']"))

        for removed in ("공개 캘린더", "동아리방", "이용안내"):
            self.assertNotIn(removed, html)

    def test_global_cta_hierarchy_css_and_pages(self):
        lms_css = (ROOT / "static" / "lms.css").read_text(encoding="utf-8")
        self.assertIn(".lms-button-primary:hover", lms_css)
        self.assertIn(".lms-button-cta", lms_css)

        groups_css = (ROOT / "static" / "lms_groups.css").read_text(encoding="utf-8")
        self.assertIn(".groups-cta-box", groups_css)
        self.assertIn("@media(max-width:960px)", groups_css)

        self.login(1, "admin")

        # Group generator page
        group_page = BeautifulSoup(self.client.get("/making_team").data, "html.parser")
        gen_btn = group_page.select_one("#generate-btn")
        self.assertIsNotNone(gen_btn)
        self.assertIn("lms-button-primary", gen_btn.get("class", []))
        self.assertIn("lms-button-cta", gen_btn.get("class", []))
        self.assertIsNotNone(group_page.select_one(".groups-cta-box #cta-summary-badge"))
        self.assertIsNotNone(group_page.select_one(".groups-cta-box #group-size-preview"))
        self.assertEqual(len(group_page.select(".lms-button-cta")), 1)

        # Seminar roster page
        roster_page = BeautifulSoup(
            self.client.get("/admin/seminar_sessions/sess-1/roster").data, "html.parser"
        )
        confirm_btn = roster_page.select_one("#confirm-attendance")
        self.assertIsNotNone(confirm_btn)
        self.assertIn("lms-button-cta", confirm_btn.get("class", []))
        self.assertEqual(len(roster_page.select(".lms-button-cta")), 1)

        # Admin seminars overview page
        seminars_page = BeautifulSoup(
            self.client.get("/admin/seminars?term_id=term-1").data, "html.parser"
        )
        self.assertEqual(len(seminars_page.select(".lms-button-cta")), 1)

        # Seminar record detail page
        detail_page = BeautifulSoup(self.client.get("/records/seminars/h1").data, "html.parser")
        save_btn = detail_page.select_one("#save-groups")
        self.assertIsNotNone(save_btn)
        self.assertIn("lms-button-cta", save_btn.get("class", []))
        self.assertEqual(len(detail_page.select(".lms-button-cta")), 1)

        # Group GA results template contract
        ga_results = (ROOT / "templates" / "bookclub_ga_results.html").read_text(encoding="utf-8")
        self.assertIn("save-groups-btn lms-button lms-button-primary lms-button-cta", ga_results)
        self.assertEqual(ga_results.count("lms-button-cta"), 1)

    def test_records_members_and_profile_redesign_preserve_hooks_without_subbar(self):
        required_ids = (
            "login-admin",
            "signup-code-value",
            "signup-code-input",
            "signup-code-set",
            "signup-code-open",
            "signup-code-revoke",
            "ot-duration",
            "ot-open",
            "ot-close",
            "ot-expiry",
            "ot-remaining",
            "incomplete-filter",
            "duplicate-filter",
            "merge-open",
            "merge-panel",
            "merge-close",
            "source-member",
            "target-member",
            "merge-run",
            "member-search",
            "show-all",
            "member-list",
            "member-add",
            "member-dialog",
            "member-form",
            "dialog-title",
            "m-name",
            "m-student-id",
            "m-department",
            "m-email",
            "m-class",
            "m-gender",
            "m-role",
            "member-save",
        )
        required_classes = (
            "status-filter",
            "member-row",
            "status-control",
            "status-choice",
            "signup-decision",
            "school-email",
            "login-link",
            "edit-member",
        )

        for user_id, role in ((1, "admin"), (2, "officer")):
            self.login(user_id, role)
            with self.subTest(role=role, page="members"):
                resp = self.client.get("/admin/members")
                self.assertEqual(resp.status_code, 200)
                dom = BeautifulSoup(resp.data, "html.parser")
                self.assertIsNone(dom.select_one(".records-subbar"))
                self.assertIsNotNone(dom.select_one(".records-header h1"))
                self.assertIsNotNone(dom.select_one(".members-auth-grid"))
                self.assertIsNotNone(dom.select_one(".members-kpi-strip"))
                for element_id in required_ids:
                    if element_id == "m-role" and role == "officer":
                        self.assertIsNotNone(dom.select_one("input#m-role[type='hidden']"), element_id)
                    else:
                        self.assertIsNotNone(dom.select_one(f"#{element_id}"), element_id)
                for cls_name in required_classes:
                    self.assertTrue(dom.select(f".{cls_name}"), cls_name)

            with self.subTest(role=role, page="member_profile"):
                prof_resp = self.client.get(f"/records/members/{user_id}")
                self.assertEqual(prof_resp.status_code, 200)
                prof_dom = BeautifulSoup(prof_resp.data, "html.parser")
                self.assertIsNone(prof_dom.select_one(".records-subbar"))
                self.assertIsNotNone(prof_dom.select_one(".profile-hero"))
                self.assertIsNotNone(prof_dom.select_one(".records-stats"))
                self.assertIsNotNone(prof_dom.select_one("#seminar-activity"))


if __name__ == "__main__":
    unittest.main()
