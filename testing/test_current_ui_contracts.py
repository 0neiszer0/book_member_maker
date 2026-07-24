import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CurrentUiContractsTest(unittest.TestCase):
    def read(self, relative_path):
        return (ROOT / relative_path).read_text(encoding="utf-8")

    def test_login_and_identity_pages_use_current_theme(self):
        login = self.read("templates/login.html")
        identity = self.read("templates/link_account.html")
        self.assertIn("{% extends 'auth_base.html' %}", login)
        self.assertIn("{% extends 'auth_base.html' %}", identity)
        self.assertNotIn("eva-", login.lower())
        self.assertNotIn("eva-", identity.lower())
        self.assertIn("카카오로 로그인", login)
        self.assertIn("회원가입", login)

    def test_unlinked_kakao_flow_leads_with_signup(self):
        identity = self.read("templates/link_account.html")
        self.assertIn("회원가입을<br>진행할게요", identity)
        self.assertIn('name="action" value="create"', identity)
        self.assertIn("이미 동아리 명부에 등록되어 있어요", identity)

    def test_seminar_reviews_are_managed_in_seminar_screen(self):
        seminars = self.read("templates/admin_seminars.html")
        engagement = self.read("templates/admin_engagement.html")
        self.assertIn("macro review_panel(seminar_session)", seminars)
        self.assertIn("{{ review_panel(mon) }}", seminars)
        self.assertIn("{{ review_panel(thu) }}", seminars)
        self.assertIn("review-form-status", seminars)
        self.assertNotIn("후기 모아보기", seminars)
        self.assertNotIn("세미나 후기 링크 열기", engagement)

    def test_html_response_gets_a_light_first_paint(self):
        app_source = self.read("app.py")
        self.assertIn('data-critical-theme="wood"', app_source)
        self.assertIn('<meta name="color-scheme" content="light">', app_source)
        self.assertIn("body{background-color:#FAF6EC}", app_source)

    def test_book_cards_have_a_clear_action(self):
        books = self.read("templates/book_suggestions.html")
        self.assertIn("eg-card-action", books)
        self.assertIn("도서 보기 · 같이 읽고 싶어요", books)


if __name__ == "__main__":
    unittest.main()
