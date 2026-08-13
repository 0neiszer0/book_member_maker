import unittest
from pathlib import Path

from recruitment_results import (
    normalize_applicant_name,
    parse_applicant_rows,
)


ROOT = Path(__file__).resolve().parents[1]


class RecruitmentResultsTest(unittest.TestCase):
    def read(self, relative_path):
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_excel_rows_are_normalized_and_statuses_are_supported(self):
        rows, errors = parse_applicant_rows(
            "이름\t학번\t결과\t개인 안내\n홍 길동\t2026000000\t합격\t개인 안내\n김호반\t2026000001\t예비\n"
        )
        self.assertEqual(errors, [])
        self.assertEqual(rows[0]["name_key"], "홍길동")
        self.assertEqual(rows[0]["result_status"], "accepted")
        self.assertEqual(rows[1]["result_status"], "waitlisted")
        self.assertTrue(rows[0]["_status_provided"])
        self.assertFalse(rows[1]["_message_provided"])
        self.assertEqual(normalize_applicant_name(" Kim Min Su "), "kimminsu")

    def test_bulk_rows_reject_bad_ids_duplicates_and_unknown_statuses(self):
        rows, errors = parse_applicant_rows(
            "홍길동\t12\t합격\n김호반\t2026000001\t보류\n김다시\t2026000001\t합격\n"
        )
        self.assertEqual(rows, [])
        self.assertEqual(len(errors), 3)

    def test_public_portal_has_no_site_navigation_or_login_link(self):
        portal = self.read("templates/applicant_result_portal.html")
        self.assertNotIn("_header.html", portal)
        self.assertNotIn("url_for('login')", portal)
        self.assertNotIn("url_for('main_index')", portal)
        self.assertIn("이 링크에서는 로그인·회원가입", portal)
        self.assertIn('name="name"', portal)
        self.assertIn('name="student_id"', portal)

    def test_applicant_session_blocks_every_unrelated_endpoint(self):
        app_source = self.read("app.py")
        boundary = app_source[
            app_source.index("def enforce_applicant_portal_boundary"):
            app_source.index("# ==============================================================================")
        ]
        self.assertIn('request.endpoint == "static"', boundary)
        self.assertIn('request.endpoint == "applicant_result_portal"', boundary)
        self.assertIn("다른 기능을 사용할 수 없습니다", boundary)
        self.assertIn("code=303", boundary)
        self.assertIn('session.clear()', app_source)

    def test_lookup_is_exact_rate_limited_and_not_cached(self):
        app_source = self.read("app.py")
        portal_route = app_source[
            app_source.index("def applicant_result_portal"):
            app_source.index("def admin_recruitment_results")
        ]
        self.assertIn('.eq("student_id", student_id)', portal_route)
        self.assertIn('.eq("name_key", name_key)', portal_route)
        self.assertIn(">= 10", portal_route)
        self.assertIn("timedelta(minutes=15)", portal_route)
        self.assertIn('response.headers["Cache-Control"] = "no-store, max-age=0"', app_source)
        self.assertIn('response.headers["X-Robots-Tag"]', app_source)

    def test_schema_is_server_only_and_admin_ui_supports_bulk_management(self):
        migration = self.read("migrations/028_recruitment_results.sql")
        detail = self.read("templates/admin_recruitment_result_detail.html")
        sidebar = self.read("templates/_admin_sidebar.html")
        for table in (
            "recruitment_campaigns",
            "recruitment_applicants",
            "recruitment_lookup_attempts",
        ):
            self.assertIn(f"alter table public.{table} enable row level security", migration)
        self.assertIn("from public, anon, authenticated", migration)
        self.assertIn("엑셀 명단 붙여넣기", detail)
        self.assertIn("결과 발표하기", detail)
        self.assertIn("기존 링크 폐기하고 새로 발급", detail)
        self.assertIn("면접 지원자", sidebar)


if __name__ == "__main__":
    unittest.main()
