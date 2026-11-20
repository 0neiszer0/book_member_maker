import importlib
import os
import re
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from testing._fake_supabase import FakeSupabase

os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
os.environ.setdefault("FLASK_SECRET_KEY", "render-smoke-only")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:9")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "render-smoke-only")

TOKEN = "22222222-2222-2222-2222-222222222222"
PATH = f"/review/seminar/{TOKEN}"


def member(mid, sid):
    return dict(id=mid, name=f"회원{mid}", role="member", is_active=True, member_status="active",
                account_status="active", social_id=f"fake-{mid}", student_id=sid, department="테스트학과")


def rows():
    return {
        "members": [member(1, "2026000001"), member(2, "2026000002")],
        "seminar_review_forms": [dict(id="form-1", seminar_session_id="s-1", share_token=TOKEN, status="open")],
        "seminar_sessions": [dict(id="s-1", book_title="데미안", meeting_date="2026-10-29")],
        "seminar_reviews": [],
        "review_edit_attempts": [],
        "submission_revisions": [],
        "history": [dict(id="h-1", seminar_session_id="s-1", date="2026-10-29")],
    }


class GuestSeminarReviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module("app")
        cls.real = cls.module.supabase

    def setUp(self):
        self.db = FakeSupabase(rows())
        self.patch = patch.object(self.real, "table", self.db.table)
        self.patch.start()
        self.module.app.config.update(TESTING=True)
        self.client = self.module.app.test_client()

    def tearDown(self):
        self.patch.stop()

    def csrf(self):
        html = self.client.get(PATH).get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def post(self, **data):
        data.setdefault("csrf_token", self.csrf())
        return self.client.post(PATH, data=data)

    def test_guest_form_renders_without_login(self):
        html = self.client.get(PATH).get_data(as_text=True)
        self.assertIn('name="author_name"', html)
        self.assertIn('name="student_id"', html)
        self.assertIn('name="website"', html)
        self.assertIn("로그인 없이 바로 쓸 수 있어요", html)

    def test_guest_submit_requires_csrf(self):
        result = self.client.post(PATH, data={"author_name": "손님", "student_id": "2026000009", "review_content": "좋았다"})
        self.assertEqual(result.status_code, 403)
        self.assertEqual(self.db.rows["seminar_reviews"], [])

    def test_guest_submit_stores_digest_and_shows_code_once_with_signup_prompt(self):
        result = self.post(author_name="손님", student_id="2026-000009", review_content="좋았다")
        html = result.get_data(as_text=True)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.headers["Cache-Control"], "no-store")
        row = self.db.rows["seminar_reviews"][0]
        self.assertIsNone(row["member_id"])
        self.assertEqual(row["identity_kind"], "guest")
        self.assertEqual(row["student_id"], "2026000009")
        code = re.search(r'id="review-edit-code" readonly value="([^"]+)"', html).group(1)
        self.assertNotIn(code, str(row))
        self.assertRegex(row["edit_token_hash"], r"^[0-9a-f]{64}$")
        self.assertIn("가입하고 내 후기 모아보기", html)
        self.assertIn("/signup?next=", html)
        self.assertIn("/login?next=", html)
        self.assertEqual(self.db.rows["review_edit_attempts"][0]["action"], "submit")

    def page_token(self):
        html = self.client.get(PATH).get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def test_signed_token_works_without_a_session_cookie(self):
        token = self.page_token()
        self.assertTrue(token.startswith('s1.'))
        with self.client.session_transaction() as state:
            self.assertNotIn('sensitive_csrf', state)  # nothing for the CDN to drop
        fresh = self.module.app.test_client()
        result = fresh.post(PATH, data={'csrf_token': token, 'author_name': '손님', 'student_id': '2026000009',
                                        'review_content': '쿠키 없이'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(self.db.rows['seminar_reviews']), 1)

    def test_signed_token_rejects_tampering_age_and_other_visitor(self):
        token = self.page_token()
        version, issued, mac = token.split('.')
        bad = [f'{version}.{issued}.{"0" * len(mac)}', f'{version}.{int(issued) - 13 * 3600}.{mac}', 's1.x.y']
        for value in bad:
            result = self.client.post(PATH, data={'csrf_token': value, 'author_name': '손님', 'student_id': '2026000009',
                                                  'review_content': 'x'})
            self.assertEqual(result.status_code, 403, value)
        with self.client.session_transaction() as state:
            state.update(user_id=1, auth_provider='kakao')
        result = self.client.post(PATH, data={'csrf_token': token, 'review_content': '회원으로 위조'})
        self.assertEqual(result.status_code, 403)
        self.assertEqual(self.db.rows['seminar_reviews'], [])

    def test_honeypot_stores_nothing(self):
        result = self.post(author_name="봇", student_id="2026000009", review_content="spam", website="http://x")
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.db.rows["seminar_reviews"], [])

    def test_resubmit_needs_edit_code_and_failures_are_limited(self):
        html = self.post(author_name="손님", student_id="2026000009", review_content="처음").get_data(as_text=True)
        code = re.search(r'id="review-edit-code" readonly value="([^"]+)"', html).group(1)
        self.db.rows["seminar_reviews"][0]["id"] = "r-1"
        self.assertEqual(self.post(author_name="남", student_id="2026000009", review_content="덮어쓰기").status_code, 403)
        self.assertEqual(self.db.rows["seminar_reviews"][0]["memorable_point"], "처음")
        ok = self.post(author_name="손님", student_id="2026000009", review_content="고침", edit_code=code)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(self.db.rows["seminar_reviews"][0]["memorable_point"], "고침")
        revision = self.db.rows["submission_revisions"][0]
        self.assertEqual(revision["actor_kind"], "guest")
        self.assertNotIn("edit_token_hash", revision["payload"])
        now = datetime.now(timezone.utc).isoformat()
        attempt = dict(self.db.rows["review_edit_attempts"][-1], succeeded=False, created_at=now, action="edit")
        self.db.rows["review_edit_attempts"] = [dict(attempt) for _ in range(10)]
        self.assertEqual(self.post(author_name="손님", student_id="2026000009", review_content="x", edit_code=code).status_code, 429)

    def test_guest_cannot_overwrite_member_review(self):
        self.db.rows["seminar_reviews"].append(dict(id="r-m", form_id="form-1", member_id=1, identity_kind="member",
                                                    student_id="2026000001", memorable_point="회원 글"))
        self.assertEqual(self.post(author_name="남", student_id="2026000001", review_content="가로채기").status_code, 409)
        self.assertEqual(self.db.rows["seminar_reviews"][0]["memorable_point"], "회원 글")

    def test_member_claims_guest_review_with_code(self):
        html = self.post(author_name="회원1", student_id="2026000001", review_content="로그인 전").get_data(as_text=True)
        code = re.search(r'id="review-edit-code" readonly value="([^"]+)"', html).group(1)
        self.db.rows["seminar_reviews"][0]["id"] = "r-1"
        with self.client.session_transaction() as state:
            state.update(user_id=1, auth_provider="kakao", sensitive_csrf="c")
        page = self.client.get(PATH).get_data(as_text=True)
        self.assertIn("내 계정에 연결하기", page)
        self.client.post(PATH + "/claim", data={"csrf_token": "c", "edit_code": "wrong"})
        self.assertIsNone(self.db.rows["seminar_reviews"][0]["member_id"])
        self.client.post(PATH + "/claim", data={"csrf_token": "c", "edit_code": code})
        row = self.db.rows["seminar_reviews"][0]
        self.assertEqual((row["member_id"], row["identity_kind"], row["edit_token_hash"]), (1, "member", None))

    def test_id_password_member_claims_guest_review(self):
        html = self.post(author_name="회원1", student_id="2026000001", review_content="가입 전").get_data(as_text=True)
        code = re.search(r'id="review-edit-code" readonly value="([^"]+)"', html).group(1)
        self.db.rows["seminar_reviews"][0]["id"] = "r-1"
        member = self.db.rows["members"][0]
        member.update(social_id=None, auth_provider="local", auth_session_version=2)
        with self.client.session_transaction() as state:
            state.update(user_id=1, auth_provider="local", auth_session_version=2, sensitive_csrf="c")
        self.client.post(PATH + "/claim", data={"csrf_token": "c", "edit_code": code})
        self.assertEqual(self.db.rows["seminar_reviews"][0]["member_id"], 1)

    def test_stale_password_session_cannot_claim(self):
        html = self.post(author_name="회원1", student_id="2026000001", review_content="가입 전").get_data(as_text=True)
        code = re.search(r'id="review-edit-code" readonly value="([^"]+)"', html).group(1)
        self.db.rows["members"][0].update(social_id=None, auth_provider="local", auth_session_version=3)
        with self.client.session_transaction() as state:
            state.update(user_id=1, auth_provider="local", auth_session_version=2, sensitive_csrf="c")
        self.client.post(PATH + "/claim", data={"csrf_token": "c", "edit_code": code})
        self.assertIsNone(self.db.rows["seminar_reviews"][0]["member_id"])

    def test_other_member_cannot_claim(self):
        html = self.post(author_name="회원1", student_id="2026000001", review_content="로그인 전").get_data(as_text=True)
        code = re.search(r'id="review-edit-code" readonly value="([^"]+)"', html).group(1)
        with self.client.session_transaction() as state:
            state.update(user_id=2, auth_provider="kakao", sensitive_csrf="c")
        self.client.post(PATH + "/claim", data={"csrf_token": "c", "edit_code": code})
        self.assertIsNone(self.db.rows["seminar_reviews"][0]["member_id"])

    def test_claim_requires_login(self):
        result = self.client.post(PATH + "/claim", data={"edit_code": "x"})
        self.assertEqual(result.status_code, 303)
        self.assertIn("/login?next=", result.location)

    def test_closed_form_rejects_guest(self):
        self.db.rows["seminar_review_forms"][0]["status"] = "closed"
        self.post(author_name="손님", student_id="2026000009", review_content="늦음")
        self.assertEqual(self.db.rows["seminar_reviews"], [])

    def test_soft_deleted_guest_review_is_ignored_by_student_lookup(self):
        self.db.rows["seminar_reviews"].append(dict(
            id="r-del", form_id="form-1", member_id=None, identity_kind="guest",
            author_name="손님", student_id="2026000009", memorable_point="삭제됨",
            edit_token_hash="0" * 64, deleted_at="2026-10-30T00:00:00Z",
        ))
        res = self.post(author_name="손님", student_id="2026000009", review_content="새 후기")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(self.db.rows["seminar_reviews"]), 2)
        self.assertEqual(self.db.rows["seminar_reviews"][1]["memorable_point"], "새 후기")

    def test_form_includes_submit_guard_and_guest_done_includes_copy_button(self):
        form_html = self.client.get(PATH).get_data(as_text=True)
        self.assertIn("제출 중...", form_html)
        self.assertIn("checkValidity", form_html)
        done_html = self.post(author_name="손님", student_id="2026000009", review_content="좋았다").get_data(as_text=True)
        self.assertIn('id="copy-review-edit-code"', done_html)
        self.assertIn('id="copy-review-edit-status"', done_html)
        self.assertIn("수정 코드를 복사했습니다.", done_html)


class ReviewCredentialTests(unittest.TestCase):
    def test_review_and_topic_codes_use_separate_domains(self):
        from topic_credentials import (review_edit_token_digest, review_edit_token_matches,
                                       topic_edit_token_digest, topic_edit_token_matches)
        self.assertNotEqual(review_edit_token_digest("code", "k" * 32), topic_edit_token_digest("code", "k" * 32))
        self.assertFalse(review_edit_token_matches(topic_edit_token_digest("code", "k" * 32), "code", "k" * 32))
        self.assertFalse(topic_edit_token_matches(review_edit_token_digest("code", "k" * 32), "code", "k" * 32))
        self.assertTrue(review_edit_token_matches(review_edit_token_digest("code", "k" * 32), "code", "k" * 32))

    def test_author_label_marks_guests_for_staff_and_boards(self):
        from engagement import review_author_label
        guest = dict(member_id=None, identity_kind="guest", author_name="손님")
        self.assertEqual(review_author_label(guest), "손님")
        self.assertEqual(review_author_label(guest, staff=True), "손님 (비회원)")
        self.assertEqual(review_author_label(guest, mark_guest=True), "손님 (비회원)")
        self.assertEqual(review_author_label(dict(member_id=1), {1: {"name": "회원1"}}, staff=True), "회원1")


class BoardLinkReviewTests(unittest.TestCase):
    def test_link_reviews_appear_in_session_board_view(self):
        from flask import Flask
        from boards import init_board_routes
        data = rows()
        data["boards"] = [{"id": "b", "slug": "seminar-reviews", "board_type": "seminar_review", "is_active": True,
                           "read_role": "member", "write_role": "member"}]
        data["posts"] = []
        data["seminar_reviews"] = [
            dict(id="r1", form_id="form-1", member_id=None, identity_kind="guest", author_name="손님",
                 memorable_point="링크 후기", created_at="2026-10-30T00:00:00Z", deleted_at=None),
            dict(id="r2", form_id="form-1", member_id=1, identity_kind="member", memorable_point="회원 후기",
                 created_at="2026-10-30T01:00:00Z", deleted_at=None)]
        db = FakeSupabase(data)
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY="test-only")
        init_board_routes(app, db, lambda *a, **k: lambda view: view)
        client = app.test_client()
        with client.session_transaction() as state:
            state["user_role"] = "member"
        with patch("boards.render_template", return_value="ok") as render:
            client.get("/board/seminar-reviews?history_id=h-1")
            labels = [r["author_label"] for r in render.call_args.kwargs["link_reviews"]]
            self.assertEqual(labels, ["손님 (비회원)", "회원1"])
            client.get("/board/seminar-reviews")
            self.assertEqual(render.call_args.kwargs["link_reviews"], [])


class ReviewReminderTests(unittest.TestCase):
    def test_guest_review_by_student_id_stops_reminder(self):
        from notification_delivery import collect_items
        from testing.test_lms_improvements import WriteDB, fixture
        data = fixture()
        data["seminar_review_forms"] = [dict(id="review", seminar_session_id="past", share_token="token", status="open")]
        sid = next(m for m in data["members"] if m["id"] == 1).get("student_id") or "2026000001"
        for m in data["members"]:
            if m["id"] == 1:
                m["student_id"] = sid
        data["seminar_reviews"] = [dict(id="g", form_id="review", member_id=None, student_id=sid, deleted_at=None)]
        items, _ = collect_items(WriteDB(data), datetime(2026, 9, 23, tzinfo=timezone.utc))
        self.assertFalse(any(r["event_key"] == "review:review" for r in items))


if __name__ == "__main__":
    unittest.main()
