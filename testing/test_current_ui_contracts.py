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
        self.assertIn('data-wood-theme="1"', app_source)
        self.assertIn('<meta name="color-scheme" content="light">', app_source)
        self.assertIn("body{background-color:#FAF6EC}", app_source)

    def test_topic_submission_has_readable_current_theme(self):
        topic = self.read("templates/topic_submit.html")
        self.assertIn('data-wood-theme="1"', topic)
        self.assertIn("topic-hero", topic)
        self.assertIn(".topic-author { color: #5C5142", topic)
        self.assertIn("label { color: #2A241B", topic)
        self.assertNotIn("opacity:0.7", topic)

    def test_legacy_neon_theme_is_gone_from_templates(self):
        legacy_tokens = ("Orbitron", "#00FF7F", "#6A0DAD", "#1A1A1A", "#2D2D2D")
        for template in (ROOT / "templates").glob("*.html"):
            source = template.read_text(encoding="utf-8")
            for token in legacy_tokens:
                self.assertNotIn(token, source, f"{token} remains in {template.name}")

    def test_now_uses_the_registered_monday_vote_endpoint(self):
        engagement = self.read("engagement.py")
        self.assertIn('url_for("seminar_vote_page", token=', engagement)
        self.assertNotIn('url_for("seminar_vote", token=', engagement)

    def test_legacy_genres_are_not_shown_in_seminar_activity(self):
        member = self.read("templates/records_member_profile.html")
        seminars = self.read("templates/records_seminars.html")
        detail = self.read("templates/records_seminar_detail.html")
        self.assertNotIn("s.genre", member)
        self.assertNotIn("genreFilter", seminars)
        self.assertNotIn("genreSelect", detail)

    def test_book_cards_have_a_clear_action(self):
        books = self.read("templates/book_suggestions.html")
        self.assertIn("eg-card-action", books)
        self.assertIn("도서 보기 · 같이 읽고 싶어요", books)


if __name__ == "__main__":
    unittest.main()
