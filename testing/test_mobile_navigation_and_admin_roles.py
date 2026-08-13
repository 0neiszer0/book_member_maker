import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MobileNavigationAndAdminRoleContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.header = (ROOT / "templates" / "_header.html").read_text(encoding="utf-8")
        cls.members = (ROOT / "templates" / "records_members.html").read_text(encoding="utf-8")
        cls.app_source = (ROOT / "app.py").read_text(encoding="utf-8")

    def test_mobile_tabbar_has_tappable_targets(self):
        self.assertIn("min-height:48px;pointer-events:auto;touch-action:manipulation", self.header)
        self.assertIn("-webkit-tap-highlight-color", self.header)

    def test_mobile_tabbar_hides_only_at_end_of_scrollable_page(self):
        self.assertIn("root.scrollHeight > window.innerHeight + 24", self.header)
        self.assertIn("root.scrollHeight - 12", self.header)
        self.assertIn("wd-tabbar-hidden", self.header)
        self.assertIn("pointer-events:none", self.header)
        self.assertIn("window.addEventListener('pageshow', queueTabbarUpdate)", self.header)

    def test_only_primary_admin_can_assign_admin_role(self):
        self.assertIn("requested_role == 'admin' and not _current_user_is_primary_admin()", self.app_source)
        self.assertIn("requested_role != current_role and not _current_user_is_primary_admin()", self.app_source)
        self.assertIn("자신의 관리자 권한은 직접 해제할 수 없습니다.", self.app_source)
        self.assertIn("최소 한 명의 활성 관리자가 필요합니다.", self.app_source)
        self.assertIn('session["user_role"] = member["role"]', self.app_source)

    def test_role_control_is_only_rendered_for_primary_admin(self):
        self.assertIn("{% if can_manage_roles %}", self.members)
        self.assertIn("다시 로그인한 뒤 관리자 기능을 사용할 수 있습니다.", self.members)
        self.assertIn("can_manage_roles=_current_user_is_primary_admin()", self.app_source)


if __name__ == "__main__":
    unittest.main()
