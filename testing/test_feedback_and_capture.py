import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class ResultEditingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'templates' / 'bookclub_ga_results.html').read_text(
            encoding='utf-8'
        )

    def test_inline_edit_recalculates_gender_badge(self):
        self.assertIn('const memberGenders = JSON.parse', self.source)
        self.assertIn('function updateGenderBadge', self.source)
        self.assertIn(
            "updateGenderBadge(row.querySelector('.gender-balance-badge'), groupMembers)",
            self.source,
        )

    def test_capture_uses_current_wood_theme(self):
        self.assertIn("backgroundColor: '#FAF6EC'", self.source)
        self.assertIn('책 먹는 호반우', self.source)
        self.assertIn('세미나 조 편성', self.source)
        self.assertNotIn("color: #00FF7F", self.source)


class BugReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_source = (ROOT / 'app.py').read_text(encoding='utf-8')
        cls.widget = (ROOT / 'templates' / '_bug_report_widget.html').read_text(
            encoding='utf-8'
        )
        cls.migration = (ROOT / 'migrations' / '018_bug_reports.sql').read_text(
            encoding='utf-8'
        )

    def test_logged_in_report_endpoint_validates_and_saves(self):
        self.assertIn("@app.route('/api/bug-reports', methods=['POST'])", self.app_source)
        self.assertIn('@login_required(role="ANY")', self.app_source)
        self.assertIn("supabase.table('bug_reports').insert", self.app_source)

    def test_admin_can_review_reports(self):
        self.assertIn("@app.route('/admin/bug-reports')", self.app_source)
        self.assertIn("@app.route('/api/admin/bug-reports/<report_id>'", self.app_source)
        self.assertIn("('new', 'reviewing', 'resolved')", self.app_source)

    def test_table_is_server_only_and_rls_enabled(self):
        self.assertIn('ALTER TABLE public.bug_reports ENABLE ROW LEVEL SECURITY', self.migration)
        self.assertIn('REVOKE ALL ON public.bug_reports FROM anon, authenticated', self.migration)
        self.assertIn('GRANT ALL ON public.bug_reports TO service_role', self.migration)

    def test_widget_is_visible_and_does_not_send_path_tokens(self):
        self.assertIn('버그 제보', self.widget)
        self.assertIn("fetch('/api/bug-reports'", self.widget)
        self.assertIn("request.endpoint", self.widget)
        self.assertNotIn('window.location.href', self.widget)
if __name__ == '__main__':
    unittest.main()
