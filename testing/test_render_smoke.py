import importlib
import os
import unittest

from testing._fake_supabase import FakeSupabase


os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
os.environ.setdefault("FLASK_SECRET_KEY", "render-smoke-only")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:9")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "render-smoke-only")


class FlaskRenderSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_module = importlib.import_module("app")
        cls.original_supabase = cls.app_module.supabase
        cls.fake = FakeSupabase({
            "members": [{
                "id": 1,
                "name": "테스트 관리자",
                "gender": "F",
                "department": "테스트학과",
                "student_id": "2026000000",
                "recruiting_class": "테스트",
                "member_status": "active",
                "account_status": "active",
                "role": "admin",
                "is_active": True,
                "email": "admin@example.test",
            }],
            "history": [{
                "id": "history-smoke-1",
                "date": "2026-03-02",
                "book_title": "렌더 스모크 도서",
                "groups": [["테스트 관리자"]],
                "facilitators": ["테스트 관리자"],
            }],
            "brick_session_members": [],
            "study_session_members": [],
            "brick_books": [],
            "study_groups": [],
            "genres": [],
            "seminar_terms": [],
        })
        cls.app_module.supabase = cls.fake
        cls.app_module.app.config.update(
            TESTING=True,
            SECRET_KEY="render-smoke-only",
        )

    @classmethod
    def tearDownClass(cls):
        cls.app_module.supabase = cls.original_supabase

    def assert_common_head(self, html, expect_tailwind=True):
        self.assertIn('/static/theme.css', html)
        if expect_tailwind:
            self.assertIn('/static/tailwind.css', html)
        self.assertNotIn('cdn.tailwindcss.com', html)

    def authenticated_client(self):
        client = self.app_module.app.test_client()
        with client.session_transaction() as session:
            session["user_role"] = "admin"
            session["user_id"] = 1
            session["user_name"] = "테스트 관리자"
        return client

    def test_public_pages_render_with_static_theme_assets(self):
        client = self.app_module.app.test_client()
        home = client.get("/")
        login = client.get("/login")
        self.assertEqual(home.status_code, 200)
        self.assertEqual(login.status_code, 200)
        self.assert_common_head(home.get_data(as_text=True))
        self.assert_common_head(login.get_data(as_text=True), expect_tailwind=False)

    def test_admin_record_pages_render_with_one_feedback_widget(self):
        client = self.authenticated_client()
        for path in ("/records", "/admin/members", "/records/seminars"):
            with self.subTest(path=path):
                response = client.get(path)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assert_common_head(html)
                self.assertEqual(
                    html.count('<dialog id="wd-bug-report-dialog"'),
                    1,
                )

        self.assertIn(
            ("range", "history", (0, 99), {}),
            self.fake.calls,
        )
        self.assertTrue(any(
            call[0] == "select"
            and call[1] == "history"
            and call[3].get("count") == "exact"
            for call in self.fake.calls
        ))


if __name__ == "__main__":
    unittest.main()
