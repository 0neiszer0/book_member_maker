import importlib
import os
import unittest
from datetime import datetime, timezone

from testing._fake_supabase import FakeSupabase
from topic_credentials import (
    topic_edit_token_digest,
    topic_edit_token_matches,
    topic_request_fingerprint,
)


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
                "member_id": 7,
                "identity_kind": "member",
                "edit_token_hash": None,
                "credential_version": 2,
                "pin_code": "MEMBER",
                "topics": [{"topic": "기존 발제"}],
                "topic_limit": 2,
            }],
            "topic_edit_attempts": [],
        })
        self.app_module.supabase = self.fake

    def tearDown(self):
        self.app_module.supabase = self.original_supabase

    def test_name_and_student_id_do_not_bypass_member_ownership(self):
        client = self.app_module.app.test_client()
        response = client.post("/api/topics/load", json={
            "event_id": "event-1",
            "author_name": "인증회원",
            "department": "국문학과",
            "student_id": "2026123456",
            "edit_credential": "",
        })

        self.assertEqual(response.status_code, 403)
        self.assertIn("수정 정보", response.get_json()["error"])

    def test_guest_record_requires_valid_strong_edit_token(self):
        token = "guest-edit-token-with-enough-entropy"
        record = self.fake.rows["topic_submissions"][0]
        record.update({
            "author_name": "비회원",
            "department": "국문학과",
            "student_id": "2026000001",
            "member_id": None,
            "identity_kind": "guest",
            "pin_code": "TOKEN",
            "edit_token_hash": topic_edit_token_digest(token, "topic-auth-test"),
        })
        client = self.app_module.app.test_client()
        denied = client.post("/api/topics/load", json={
            "event_id": "event-1",
            "author_name": "비회원",
            "department": "국문학과",
            "student_id": "2026000001",
            "edit_credential": "wrong-token",
        })
        allowed = client.post("/api/topics/load", json={
            "event_id": "event-1",
            "author_name": "비회원",
            "department": "국문학과",
            "student_id": "2026000001",
            "edit_credential": token,
        })

        self.assertEqual(denied.status_code, 403)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.get_json()["topics"], [{"topic": "기존 발제"}])

    def test_guest_edit_is_rate_limited_after_ten_recent_failures(self):
        token = "guest-edit-token-with-enough-entropy"
        record = self.fake.rows["topic_submissions"][0]
        record.update({
            "author_name": "비회원",
            "department": "국문학과",
            "student_id": "2026000001",
            "member_id": None,
            "identity_kind": "guest",
            "pin_code": "TOKEN",
            "edit_token_hash": topic_edit_token_digest(token, "topic-auth-test"),
        })
        request_hash = topic_request_fingerprint(
            "127.0.0.1", "event-1", "topic-auth-test"
        )
        self.fake.rows["topic_edit_attempts"] = [{
            "id": index,
            "event_id": "event-1",
            "request_hash": request_hash,
            "succeeded": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        } for index in range(10)]

        client = self.app_module.app.test_client()
        response = client.post("/api/topics/load", json={
            "event_id": "event-1",
            "author_name": "비회원",
            "department": "국문학과",
            "student_id": "2026000001",
            "edit_credential": token,
        })

        self.assertEqual(response.status_code, 429)
        self.assertIn("15분", response.get_json()["error"])

    def test_user_name_without_authenticated_member_id_does_not_bypass_ownership(self):
        client = self.app_module.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["user_name"] = "인증회원"

        response = client.post("/api/topics/load", json={
            "event_id": "event-1",
            "author_name": "인증회원",
            "department": "국문학과",
            "student_id": "2026123456",
        })

        self.assertEqual(response.status_code, 403)
        self.assertIn("수정 정보", response.get_json()["error"])

    def test_public_page_ignores_stale_name_only_session(self):
        client = self.app_module.app.test_client()
        with client.session_transaction() as flask_session:
            flask_session["user_name"] = "인증회원"

        response = client.get("/shared_topics?token=public-token")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("const IS_LOGGED_IN = false", html)
        self.assertIn('id="pinCode"', html)
        self.assertEqual(response.headers["Cache-Control"], "no-store, max-age=0")
        self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")

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
            "edit_credential": "",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["topics"], [{"topic": "기존 발제"}])

    def test_member_can_claim_submission_written_by_old_app_during_rollout(self):
        record = self.fake.rows["topic_submissions"][0]
        record.update({
            "member_id": None,
            "identity_kind": "legacy_pin",
            "pin_code": "MEMBER",
        })
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

        self.assertEqual(response.status_code, 200)

    def test_inactive_session_does_not_bypass_member_ownership(self):
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

        self.assertEqual(response.status_code, 403)
        self.assertIn("수정 정보", response.get_json()["error"])

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
        self.assertEqual(inserted["member_id"], 7)
        self.assertEqual(inserted["identity_kind"], "member")

    def test_new_guest_receives_token_but_database_only_stores_digest(self):
        self.fake.rows["topic_submissions"] = []
        client = self.app_module.app.test_client()
        response = client.post("/api/topics/submit", json={
            "event_id": "event-1",
            "author_name": "비회원",
            "department": "국문학과",
            "student_id": "2026000001",
            "topics": [{"topic": "비회원 발제", "page": "p.2", "reference": ""}],
        })

        self.assertEqual(response.status_code, 200)
        token = response.get_json()["edit_token"]
        inserted = self.fake.rows["topic_submissions"][0]
        self.assertGreaterEqual(len(token), 40)
        self.assertNotEqual(inserted["edit_token_hash"], token)
        self.assertTrue(topic_edit_token_matches(
            inserted["edit_token_hash"], token, "topic-auth-test"
        ))
        self.assertEqual(inserted["pin_code"], "TOKEN")
        self.assertEqual(inserted["identity_kind"], "guest")

    def test_registered_student_id_cannot_be_squatted_by_guest(self):
        self.fake.rows["topic_submissions"] = []
        client = self.app_module.app.test_client()
        response = client.post("/api/topics/submit", json={
            "event_id": "event-1",
            "author_name": "다른사람",
            "department": "다른학과",
            "student_id": "2026123456",
            "topics": [{"topic": "가로채기 시도", "page": "", "reference": ""}],
        })

        self.assertEqual(response.status_code, 403)
        self.assertIn("로그인 후", response.get_json()["error"])
        self.assertEqual(self.fake.rows["topic_submissions"], [])

    def test_legacy_pin_is_upgraded_after_successful_edit(self):
        record = self.fake.rows["topic_submissions"][0]
        record.update({
            "author_name": "예전비회원",
            "department": "국문학과",
            "student_id": "2026000002",
            "member_id": None,
            "identity_kind": "legacy_pin",
            "pin_code": "1234",
            "edit_token_hash": None,
            "credential_version": 1,
        })
        client = self.app_module.app.test_client()
        response = client.post("/api/topics/submit", json={
            "event_id": "event-1",
            "author_name": "예전비회원",
            "department": "국문학과",
            "student_id": "2026000002",
            "edit_credential": "1234",
            "topics": [{"topic": "수정된 발제", "page": "", "reference": ""}],
        })

        self.assertEqual(response.status_code, 200)
        token = response.get_json()["edit_token"]
        updated = self.fake.rows["topic_submissions"][0]
        self.assertEqual(updated["identity_kind"], "guest")
        self.assertEqual(updated["credential_version"], 2)
        self.assertEqual(updated["pin_code"], "TOKEN")
        self.assertTrue(topic_edit_token_matches(
            updated["edit_token_hash"], token, "topic-auth-test"
        ))


if __name__ == "__main__":
    unittest.main()
