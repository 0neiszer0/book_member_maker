import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RecordsAnalyticsAttendanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        cls.analytics = (ROOT / "templates" / "records_analytics.html").read_text(encoding="utf-8")
        cls.records_base = (ROOT / "templates" / "_records_base.html").read_text(encoding="utf-8")
        cls.matrix_template = (ROOT / "templates" / "admin_attendance_matrix.html").read_text(encoding="utf-8")

    def test_compact_admin_and_records_menus_do_not_overlap(self):
        self.assertIn(".records-subbar {", self.records_base)
        self.assertIn("position: static;", self.records_base)
        self.assertNotIn("mb-6 -mt-4 sm:-mt-6 lg:-mt-8", self.records_base)

    def test_records_subbar_does_not_duplicate_member_management_navigation(self):
        nav = self.records_base[
            self.records_base.index("{% macro records_nav(active) %}"):
            self.records_base.index("{% endmacro %}", self.records_base.index("{% macro records_nav(active) %}"))
        ]
        self.assertNotIn("url_for('records_members')", nav)
        self.assertNotIn('> 회원</a>', nav)

    def test_attendance_matrix_keeps_each_seminar_date_separate(self):
        helper = self.app_source[
            self.app_source.index("def _build_attendance_matrix"):
            self.app_source.index("def admin_attendance_matrix")
        ]
        self.assertIn("session_key = str(h.get('id')", helper)
        self.assertIn("weekday_labels", helper)
        self.assertNotIn("isocalendar", helper)
        self.assertIn("같은 주의 월·목 회차도 각각", self.matrix_template)

    def test_analytics_uses_present_roster_and_exposes_adjustable_minimum(self):
        route = self.app_source[
            self.app_source.index("def records_analytics"):
            self.app_source.index("from boards import init_board_routes")
        ]
        self.assertIn("select('id, date, genre, present, book_title')", route)
        self.assertIn("min_attendance = max(1, min(", route)
        self.assertIn("below_minimum", route)
        self.assertIn("member.get('is_active')", route)

    def test_analytics_renders_spreadsheet_export_and_shortfall_list(self):
        self.assertIn("날짜별 세미나 출석표", self.analytics)
        self.assertIn('name="min_attendance"', self.analytics)
        self.assertIn("최소 {{ min_attendance }}회 미달", self.analytics)
        self.assertIn("member.shortage", self.analytics)
        self.assertIn("attendance-sheet", self.analytics)
        self.assertIn("admin_attendance_matrix_export", self.analytics)


if __name__ == "__main__":
    unittest.main()
