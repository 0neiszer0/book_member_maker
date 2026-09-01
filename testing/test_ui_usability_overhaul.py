import subprocess
import unittest
from pathlib import Path

from jinja2 import Environment


ROOT = Path(__file__).resolve().parents[1]


class UiUsabilityOverhaulTest(unittest.TestCase):
    def read(self, path: str) -> str:
        return (ROOT / path).read_text(encoding="utf-8")

    def test_shared_head_loads_progressive_ui_assets(self):
        head = self.read("templates/_app_theme_head.html")
        self.assertIn('name="app-user-role"', head)
        self.assertIn("filename='app_ui.css'", head)
        self.assertIn("filename='app_ui.js'", head)
        self.assertIn("defer", head)

    def test_home_is_role_aware_and_has_direct_actions(self):
        home = self.read("templates/main_index.html")
        self.assertIn("session.user_role == 'admin'", home)
        self.assertIn("운영 개요 열기", home)
        self.assertIn("지금 참여하기", home)
        self.assertIn("세미나 일정 보기", home)
        self.assertIn("내 활동 기록", home)
        self.assertNotIn("text-7xl", home)

    def test_admin_overview_follows_five_step_workflow(self):
        overview = self.read("templates/admin_overview.html")
        for label in (
            "도서·일정 확인",
            "발제문 수집",
            "참석자 확인",
            "조 편성",
            "기록 확인",
        ):
            self.assertIn(label, overview)
        self.assertEqual(overview.count('class="workflow-card"'), 5)
        self.assertIn("업무별 도구", overview)

    def test_seminars_prioritize_upcoming_and_collapse_past(self):
        seminars = self.read("templates/seminars.html")
        self.assertIn("macro seminar_card", seminars)
        self.assertIn("가장 가까운 세미나", seminars)
        self.assertIn('class="seminar-past"', seminars)
        self.assertIn("발제문 작성하기", seminars)
        self.assertIn("월요일 신청 확인", seminars)

    def test_engagement_page_has_priority_and_empty_states(self):
        engagement = self.read("templates/engagement_now.html")
        self.assertIn("먼저 확인할 활동", engagement)
        self.assertIn("engagement-priority-card", engagement)
        self.assertIn("지금 바로 제출하거나 신청할 활동이 없습니다", engagement)
        self.assertIn("상시 참여", engagement)
        self.assertIn("session.user_role == 'admin'", engagement)
        self.assertNotIn("session.user_role in ['admin','officer']", engagement)

    def test_progressive_script_covers_complex_legacy_screens(self):
        script = self.read("static/app_ui.js")
        for function_name in (
            "alignRoleNavigation",
            "enhanceAdminSidebar",
            "enhanceAdminSeminars",
            "enhanceGroupingInput",
            "enhanceGroupingResults",
            "enhanceMemberManagement",
            "enhanceRecruitmentTabs",
            "enhanceSeminarVote",
            "enhanceMyPage",
            "enhanceProfilePages",
        ):
            self.assertIn(f"function {function_name}", script)
        self.assertIn("window.wdToastUndo", script)
        self.assertIn("신청자 명단 적용", script)
        self.assertIn("조 편성 추천안 만들기", script)
        self.assertIn("이 추천안으로 확정", script)
        self.assertIn("공지 이미지 만들기", script)
        self.assertIn("발표 전 점검", script)
        self.assertIn("/help/admin", script)
        self.assertIn("bootstrapEnhancements", script)
        self.assertIn("UI enhancement failed", script)
        self.assertIn("document.readyState === 'loading'", script)
        self.assertIn("reconcileFacilitators", script)
        self.assertIn("아직 선택을 변경하지 않았습니다", script)
        self.assertIn("wd-link-current", script)
        self.assertNotIn("innerHTML = changes", script)

    def test_progressive_script_adds_no_new_server_contract(self):
        script = self.read("static/app_ui.js")
        self.assertEqual(script.count("fetch("), 1)
        self.assertIn("/api/admin/members/${memberId}/set_status", script)
        self.assertNotIn("/api/ui/", script)
        self.assertNotIn("/api/navigation/", script)

    def test_mobile_overlays_do_not_stack_over_primary_controls(self):
        script = self.read("static/app_ui.js")
        css = self.read("static/app_ui.css")
        self.assertIn("function makeRoomForToast", script)
        self.assertIn("const maxVisible = mobile ? 1 : 3", script)
        self.assertIn(".wd-bulk-selection-panel { position: static", css)
        self.assertIn("#applicantSearch, .wd-tab-panel #statusFilter", css)

    def test_css_styles_actual_templates_and_mobile_states(self):
        css = self.read("static/app_ui.css")
        for selector in (
            ".home-shell",
            ".admin-overview-shell",
            ".overview-workflow",
            ".seminar-shell",
            ".engagement-priority-card",
            ".wd-group-stepper",
            ".wd-solution-switcher",
            ".member-admin-table",
            ".wd-tabs-nav",
            ".wd-admin-menu-trigger",
            ".wd-admin-seminar-summary",
            ".wd-link-current",
        ):
            self.assertIn(selector, css)
        self.assertIn("@media (max-width: 767px)", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)
        self.assertIn("min-height: 44px", css)

    def test_modified_templates_parse_as_jinja(self):
        environment = Environment()
        for path in (
            "templates/_app_theme_head.html",
            "templates/main_index.html",
            "templates/admin_overview.html",
            "templates/seminars.html",
            "templates/engagement_now.html",
        ):
            with self.subTest(path=path):
                environment.parse(self.read(path))

    def test_javascript_syntax(self):
        completed = subprocess.run(
            ["node", "--check", str(ROOT / "static/app_ui.js")],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_no_backend_database_or_render_files_are_part_of_patch(self):
        completed = subprocess.run(
            ["git", "status", "--short"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        changed = completed.stdout
        self.assertNotIn("app.py", changed)
        self.assertNotIn("migrations/", changed)
        self.assertNotIn("render.yaml", changed)
        self.assertNotIn("Dockerfile", changed)


if __name__ == "__main__":
    unittest.main()
