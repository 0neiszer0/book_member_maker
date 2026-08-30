import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class QueryEfficiencyContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        cls.engagement_source = (ROOT / "engagement.py").read_text(encoding="utf-8")

    @staticmethod
    def section(source, start, end):
        return source[source.index(start):source.index(end, source.index(start))]

    def test_engagement_hub_uses_batch_lookups(self):
        now = self.section(
            self.engagement_source,
            "    def engagement_now():",
            '    @app.route("/books/suggest"',
        )
        self.assertIn('.in_("session_id", session_ids)', now)
        self.assertIn('.in_("id", seminar_ids)', now)
        self.assertIn('.in_("id", project_ids)', now)
        self.assertNotIn('.single().execute()', now)

    def test_book_suggestion_counts_and_targets_are_batched(self):
        suggestions = self.section(
            self.engagement_source,
            "    def book_suggestions():",
            '    @app.get("/books/suggestions/<uuid:suggestion_id>")',
        )
        self.assertIn('.in_("suggestion_id", suggestion_ids)', suggestions)
        self.assertIn('support_counts[sid] = support_counts.get(sid, 0) + 1', suggestions)
        self.assertIn('targets_by_suggestion.setdefault', suggestions)
        self.assertNotIn('.eq("suggestion_id", row["id"])', suggestions)

    def test_member_legacy_name_counts_do_not_guess_for_duplicates(self):
        route = self.section(
            self.app_source,
            "def records_members():",
            "def records_members_legacy():",
        )
        template = (ROOT / "templates" / "records_members.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("ambiguous_names", route)
        self.assertIn("None if is_ambiguous", route)
        self.assertIn("activity_count_ambiguous", template)
        self.assertIn("&mdash;", template)

    def test_seminar_records_use_exact_count_and_server_range(self):
        route = self.section(
            self.app_source,
            "def records_seminars():",
            "def records_seminar_detail(",
        )
        template = (ROOT / "templates" / "records_seminars.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("select('*', count='exact')", route)
        self.assertIn(".range((page - 1) * page_size, page * page_size - 1)", route)
        self.assertIn("total_history", route)
        self.assertIn("이전 100개", template)
        self.assertIn("다음 100개", template)
        self.assertIn("현재 페이지 도서명·날짜 검색", template)

    def test_admin_engagement_reuses_loaded_applications(self):
        admin = self.section(
            self.engagement_source,
            "    def admin_engagement():",
            '    @app.post("/api/admin/seminar_sessions/<uuid:session_id>/review-form")',
        )
        self.assertIn('row["application_count"] = len(row["applications"])', admin)
        self.assertNotIn('count="exact"', admin)


if __name__ == "__main__":
    unittest.main()
