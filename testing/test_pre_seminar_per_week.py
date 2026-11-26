"""Wave 12: 읽기 전 자료 is a per-seminar item (like 발제문) on member and officer screens."""
import copy
import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from testing._fake_supabase import FakeSupabase
from testing.test_home_overview import fixture

os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
os.environ.setdefault("FLASK_SECRET_KEY", "pre-seminar-week-only")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:9")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "pre-seminar-week-only")

ROOT = Path(__file__).resolve().parents[1]


def material(**kw):
    base = dict(id="m1", slug="my-mind", title="새 도서", author="나쓰메 소세키", semester="2026-2",
                semester_label="2026-2학기", seminar_date="2026-12-03", edition_note="",
                markdown_body="## 배경\n[서평](https://example.com/review)", is_published=True,
                created_at="2026-11-01T00:00:00Z", seminar_week_id="week")
    base.update(kw)
    return base


class PreSeminarPerWeekTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeSupabase()
        spec = importlib.util.spec_from_file_location("_pre_seminar_week_app", ROOT / "app.py")
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        with patch("supabase.create_client", return_value=cls.fake):
            spec.loader.exec_module(cls.module)

    def setUp(self):
        rows = fixture()
        rows["members"][0].update(gender="F", email="member@example.test", role="member")
        rows["members"][1].update(gender="M", email="admin@example.test", role="admin")
        rows["seminar_weeks"] = [{"id": "week", "term_id": "term", "week_start": "2026-11-30", "book_title": "새 도서", "book_author": "나쓰메 소세키"}]
        rows["seminar_sessions"] = [
            {"id": "wed", "term_id": "term", "seminar_week_id": "week", "day_type": "thu", "meeting_date": "2026-12-03", "moderator_name": "사회자", "is_active": True}]
        rows["history"] = []
        rows["pre_seminar_materials"] = []
        self.fake.rows = rows
        self.fake.calls.clear()
        self.module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = self.module.app.test_client()

    def login(self, role="member"):
        with self.client.session_transaction() as s:
            s.clear()
            s.update(user_id=2 if role in ("admin", "officer") else 1, user_role=role, user_name="테스트 회원", sensitive_csrf="test-csrf")

    def add(self, **kw):
        self.fake.rows["pre_seminar_materials"].append(material(**kw))

    # --- helpers -----------------------------------------------------
    def test_attach_matching_priority_and_no_cache_mutation(self):
        from public_archive_routes import attach_pre_seminar_materials_to_weeks, PRE_SEMINAR_PATH, _load_json_snapshot
        before = copy.deepcopy(_load_json_snapshot(PRE_SEMINAR_PATH))
        weeks = [
            {"id": "w1", "week_start": "2026-07-13", "book_title": "라쇼몽", "sessions": [{"meeting_date": "2026-07-16"}]},
            {"id": "w2", "week_start": "2026-01-05", "book_title": "클라라와 태양", "sessions": []},
            {"id": "w3", "week_start": "2026-02-02", "book_title": "도서 미정", "sessions": []},
            {"id": "w4", "week_start": "2026-02-09", "book_title": "없는 책", "sessions": []},
        ]
        attach_pre_seminar_materials_to_weeks(self.fake, weeks)
        self.assertEqual(weeks[0]["pre_seminar"]["slug"], "2026-summer-rashomon")
        self.assertEqual(weeks[0]["pre_seminar"]["source"], "archive")
        self.assertEqual(weeks[1]["pre_seminar"]["slug"], "2026-2-klara-and-the-sun")  # unique title fallback
        self.assertIsNone(weeks[2]["pre_seminar"])
        self.assertIsNone(weeks[3]["pre_seminar"])
        self.assertEqual(before, _load_json_snapshot(PRE_SEMINAR_PATH))
        self.assertNotIn("source", _load_json_snapshot(PRE_SEMINAR_PATH)["books"][0])

    def test_explicit_link_beats_archive_and_fail_soft(self):
        from public_archive_routes import attach_pre_seminar_materials_to_weeks
        self.add(title="전혀 다른 제목", slug="explicit")
        weeks = [{"id": "week", "week_start": "2026-11-30", "book_title": "새 도서", "sessions": []}]
        attach_pre_seminar_materials_to_weeks(self.fake, weeks)
        self.assertEqual(weeks[0]["pre_seminar"]["slug"], "explicit")
        self.assertEqual(weeks[0]["pre_seminar"]["reference_count"], 1)
        broken = [{"id": "x", "book_title": "라쇼몽", "week_start": "2026-07-13", "sessions": []}]
        attach_pre_seminar_materials_to_weeks(None, broken)
        self.assertEqual(broken[0]["pre_seminar"]["source"], "archive")

    # --- admin save / edit -------------------------------------------
    def save(self, **kw):
        data = {"csrf_token": "test-csrf", "title": "새 도서", "markdown_body": "## 본문", "is_published": "on"}
        data.update(kw)
        return self.client.post("/admin/pre-seminar/save", data=data)

    def test_save_link_clear_and_invalid(self):
        self.login("admin")
        self.assertEqual(self.save(seminar_week_id="nope").status_code, 400)
        self.assertEqual(self.fake.rows["pre_seminar_materials"], [])
        self.assertEqual(self.save(seminar_week_id="week", return_term="term").status_code, 303)
        row = self.fake.rows["pre_seminar_materials"][0]
        self.assertEqual(row["seminar_week_id"], "week")
        self.save(material_id=row["id"], seminar_week_id="")
        self.assertIsNone(self.fake.rows["pre_seminar_materials"][0]["seminar_week_id"])
        self.save(title="독립 자료")
        self.assertNotIn("seminar_week_id", self.fake.rows["pre_seminar_materials"][1])

    def test_admin_page_prefill_and_auto_edit(self):
        self.login("admin")
        html = self.client.get("/admin/pre-seminar?week_id=week&return_term=term").get_data(as_text=True)
        self.assertIn('id="seminar-week-id"', html)
        self.assertIn('value="새 도서"', html)
        self.assertIn('value="2026-12-03"', html)
        self.assertIn("Markdown 등록", html)
        self.add()
        html = self.client.get("/admin/pre-seminar?week_id=week").get_data(as_text=True)
        self.assertIn("Markdown 수정", html)
        self.assertIn("연결 세미나: 2026-2학기 · 2026-12-03", html)
        self.assertIn("Markdown 등록", self.client.get("/admin/pre-seminar?week_id=week&new=1").get_data(as_text=True))
        saved = self.client.get("/admin/pre-seminar?saved=1&return_term=term&week_id=week").get_data(as_text=True)
        self.assertIn("← 세미나 운영으로 돌아가기", saved)
        self.assertIn("/admin/seminars?term_id=term#week-week", saved)

    # --- member screens -----------------------------------------------
    def test_seminars_curriculum_shows_published_only(self):
        self.login("member")
        self.add(is_published=False)
        html = self.client.get("/seminars?term_id=term").get_data(as_text=True)
        self.assertNotIn("data-pre-seminar-slug", html)
        self.assertIn("읽기 전 자료가 아직 등록되지 않았습니다.", html)
        self.assertNotIn("이 세미나 사전 자료 등록", html)
        self.fake.rows["pre_seminar_materials"][0]["is_published"] = True
        html = self.client.get("/seminars?term_id=term").get_data(as_text=True)
        self.assertIn('data-pre-seminar-slug="my-mind"', html)
        self.assertIn("/pre-seminar/my-mind?term_id=term&amp;week_id=week", html)
        self.assertIn("참고 링크 1개", html)
        self.assertNotIn("사전 자료 관리", html)
        self.login("admin")
        html = self.client.get("/seminars?term_id=term").get_data(as_text=True)
        self.assertIn("사전 자료 관리", html)

    def test_seminars_staff_empty_cta_and_resources_tab(self):
        self.login("admin")
        html = self.client.get("/seminars?term_id=term").get_data(as_text=True)
        self.assertIn("이 세미나 사전 자료 등록", html)
        self.assertIn("week_id=week", html)
        self.add()
        res = self.client.get("/seminars?term_id=term&section=resources").get_data(as_text=True)
        self.assertIn("새 도서 읽기 전 자료", res)
        self.assertIn("전체 세미나 전 자료 모음 보기", res)
        self.assertNotIn("이 학기에 연결된 자료·기록이 없습니다", res)

    def test_home_upcoming_shows_link(self):
        self.login("member")
        self.assertNotIn(">읽기 전 자료</a>", self.client.get("/").get_data(as_text=True))
        self.add()
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("/pre-seminar/my-mind?term_id=term&amp;week_id=week", html)
        self.assertIn(">읽기 전 자료</a>", html)

    def test_detail_links_back_to_week_and_topic(self):
        self.login("member")
        self.add()
        self.fake.rows["topic_events"] = [{"id": "event", "seminar_week_id": "week", "is_active": True, "share_token": "t", "created_at": "2026-11-01"}]
        html = self.client.get("/pre-seminar/my-mind").get_data(as_text=True)
        self.assertIn("← 해당 세미나로 돌아가기", html)
        self.assertIn("이 세미나 발제문 보기", html)
        self.assertIn("#week-week", html)
        self.assertNotIn("발제문·토의 기록 보기", html)
        self.assertNotIn("이 자료 수정", html)
        self.login("admin")
        self.assertIn("이 자료 수정", self.client.get("/pre-seminar/my-mind").get_data(as_text=True))

    def test_detail_guest_hides_week_links_and_member_keeps_them(self):
        self.add()
        self.fake.rows["topic_events"] = [{"id": "event", "seminar_week_id": "week", "is_active": True, "share_token": "t", "created_at": "2026-11-01"}]
        self.fake.calls.clear()
        resp = self.client.get("/pre-seminar/my-mind")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("새 도서", html)
        self.assertNotIn("← 해당 세미나로 돌아가기", html)
        self.assertNotIn("이 세미나 발제문 보기", html)
        self.assertNotIn("/seminars/topics/", html)
        self.assertNotIn("/seminars?term_id=", html)
        self.assertNotIn("#week-week", html)
        self.assertIn("next=%2Fpre-seminar%2Fmy-mind", html)
        self.assertIn("회원 로그인하기", html)
        self.assertNotIn("seminar_weeks", {c[1] for c in self.fake.calls})
        self.login("member")
        html = self.client.get("/pre-seminar/my-mind").get_data(as_text=True)
        self.assertIn("← 해당 세미나로 돌아가기", html)
        self.assertIn("이 세미나 발제문 보기", html)
        self.assertNotIn("회원 로그인하기", html)
        self.assertNotIn('class="pre-login-cta"', html)

    def test_detail_without_week_has_no_back_link(self):
        self.login("member")
        self.add(seminar_week_id=None, title="독립", slug="solo", seminar_date="2020-01-01")
        html = self.client.get("/pre-seminar/solo").get_data(as_text=True)
        self.assertNotIn("해당 세미나로 돌아가기", html)
        self.assertEqual(self.client.get("/pre-seminar").status_code, 200)

    # --- officer -----------------------------------------------------
    def test_admin_seminars_status_pills(self):
        self.login("admin")
        html = self.client.get("/admin/seminars?term_id=term").get_data(as_text=True)
        self.assertIn('data-pre-seminar-status="none"', html)
        self.assertIn("미등록", html)
        self.assertIn("/admin/pre-seminar?week_id=week", html)
        self.add(is_published=False)
        html = self.client.get("/admin/seminars?term_id=term").get_data(as_text=True)
        self.assertIn("초안(비공개)", html)
        self.assertIn("수정·공개", html)
        self.fake.rows["pre_seminar_materials"][0]["is_published"] = True
        html = self.client.get("/admin/seminars?term_id=term").get_data(as_text=True)
        self.assertIn('data-pre-seminar-status="public"', html)
        self.assertIn("/admin/pre-seminar?edit=m1", html)
        self.fake.rows["pre_seminar_materials"] = []
        self.fake.rows["seminar_weeks"][0]["book_title"] = "라쇼몽"
        self.fake.rows["seminar_sessions"][0]["meeting_date"] = "2026-07-16"
        self.fake.rows["seminar_weeks"][0]["week_start"] = "2026-07-13"
        html = self.client.get("/admin/seminars?term_id=term").get_data(as_text=True)
        self.assertIn("아카이브 연결됨", html)
        self.assertIn("DB 자료로 등록", html)


if __name__ == "__main__":
    unittest.main()
