import importlib
import os
import unittest

from testing._fake_supabase import FakeSupabase


os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
os.environ.setdefault("FLASK_SECRET_KEY", "topic-auth-test")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:9")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "topic-auth-test")


class TopicSubmissionAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app_module = importlib.import_module("app")
        cls.original_supabase = cls.app_module.supabase
        cls.app_module.app.config.update(TESTING=True, SECRET_KEY="topic-auth-test")

    @classmethod
    def tearDownClass(cls):
        cls.app_module.supabase = cls.original_supabase

    def setUp(self):
        self.fake = FakeSupabase({
            "members": [{
                "id": 7,
                "name": "인증회원",
                "department": "국문학과",
                "student_id": "2026123456",
                "account_status": "active",
                "member_status": "active",
                "is_active": True,
            }],
            "topic_events": [{
                "id": "event-1",
                "share_token": "public-token",
                "book_title": "인증 테스트 도서",
                "is_active": True,
                "meeting_date": "2099-09-08",
            }],
            "topic_submissions": [{
                "id": "submission-1",
                "event_id": "event-1",
                "author_name": "인증회원",
                "department": "국문학과",
                "student_id": "2026123456",
                "pin_code": "MEMBER",
                "topics": [{"topic": "기존 발제"}],
                "topic_limit": 2,
            }],
        })
        self.app_module.supabase = self.fake

    def tearDown(self):
        self.app_module.supabase = self.original_supabase

    def test_name_and_student_id_do_not_bypass_guest_pin(self):
        client = self.app_module.app.test_client()
        response = client.post("/api/topics/load", json={
            "event_id": "event-1",
            "author_name": "인증회원",
            "department": "국문학과",
            "student_id": "2026123456",
            "pin_code": "",
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("PIN", response.get_json()["error"])

    def test_guest_pin_must_be_exactly_four_digits(self):
        client = self.app_module.app.test_client()
        for invalid_pin in ("123", "12345", "abcd"):
            with self.subTest(pin=invalid_pin):
                response = client.post("/api/topics/load", json={
                    "event_id": "event-1",
                    "author_name": "비회원",
                    "department": "국문학과",
                    "student_id": "2026000001",
                    "pin_code": invalid_pin,
                })
                self.assertEqual(response.status_code, 400)
                self.assertIn("4자리 숫자 PIN", response.get_json()["error"])

    def test_user_name_without_authenticated_member_id_does_not_bypass_pin(self):
        client = self.app_module.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["user_name"] = "인증회원"

        response = client.post("/api/topics/load", json={
            "event_id": "event-1",
            "author_name": "인증회원",
            "department": "국문학과",
            "student_id": "2026123456",
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("PIN", response.get_json()["error"])

    def test_public_page_ignores_stale_name_only_session(self):
        client = self.app_module.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["user_name"] = "인증회원"

        response = client.get("/shared_topics?token=public-token")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("const IS_LOGGED_IN = false", html)
        self.assertIn('id="pinCode"', html)

    def test_public_page_uses_member_loaded_from_authenticated_session(self):
        client = self.app_module.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["user_id"] = 7
            flask_session["user_name"] = "오래된세션이름"
            flask_session["user_role"] = "member"

        response = client.get("/shared_topics?token=public-token")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("const IS_LOGGED_IN = true", html)
        self.assertIn('value="인증회원"', html)

    def test_authenticated_member_uses_database_identity(self):
        client = self.app_module.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["user_id"] = 7
            flask_session["user_name"] = "오래된세션이름"
            flask_session["user_role"] = "member"

        response = client.post("/api/topics/load", json={
            "event_id": "event-1",
            "author_name": "다른사람",
            "department": "다른학과",
            "student_id": "2099999999",
            "pin_code": "",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["topics"], [{"topic": "기존 발제"}])

    def test_inactive_session_does_not_bypass_pin(self):
        self.fake.rows["members"][0]["is_active"] = False
        client = self.app_module.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["user_id"] = 7
            flask_session["user_name"] = "인증회원"
            flask_session["user_role"] = "member"

        response = client.post("/api/topics/load", json={
            "event_id": "event-1",
            "author_name": "인증회원",
            "department": "국문학과",
            "student_id": "2026123456",
        })

        self.assertEqual(response.status_code, 400)
        self.assertIn("PIN", response.get_json()["error"])

    def test_authenticated_submit_cannot_replace_author_identity(self):
        self.fake.rows["topic_submissions"] = []
        client = self.app_module.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["user_id"] = 7
            flask_session["user_name"] = "인증회원"
            flask_session["user_role"] = "member"

        response = client.post("/api/topics/submit", json={
            "event_id": "event-1",
            "author_name": "다른사람",
            "department": "다른학과",
            "student_id": "2099999999",
            "topics": [{"topic": "새 발제", "page": "p.1", "reference": ""}],
        })

        self.assertEqual(response.status_code, 200)
        inserted = self.fake.rows["topic_submissions"][0]
        self.assertEqual(inserted["author_name"], "인증회원")
        self.assertEqual(inserted["department"], "국문학과")
        self.assertEqual(inserted["student_id"], "2026123456")
        self.assertEqual(inserted["pin_code"], "MEMBER")


if __name__ == "__main__":
    unittest.main()
