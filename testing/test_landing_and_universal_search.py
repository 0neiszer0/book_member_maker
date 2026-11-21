"""Exercise the public entry points and role boundaries through Flask."""
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup
from testing._fake_supabase import FakeSupabase
from testing.test_home_overview import fixture

ROOT = Path(__file__).resolve().parents[1]


class LandingAndSearchTests(unittest.TestCase):
    def setUp(self):
        self.db = db = FakeSupabase(fixture())
        spec = importlib.util.spec_from_file_location("_landing_search_app", ROOT / "app.py")
        self.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.module
        with patch("supabase.create_client", return_value=db):
            spec.loader.exec_module(self.module)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        wiki = Path(tmp.name) / "data.db"
        conn = sqlite3.connect(wiki)
        with conn:
            conn.execute("create table data(title text)")
            conn.executemany("insert into data values (?)", [("라쇼몽 안내",), ("운영진:라쇼몽",)])
        conn.close()
        self.module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False,
                                      WIKI_ENABLED=True, WIKI_DATABASE=str(wiki))
        db.rows["members"][0].update(name="라쇼몽 회원", social_id="test-member")
        db.rows["members"][1].update(social_id="test-admin")
        db.rows["boards"] = [
            dict(id=i, slug=role, name=role, read_role=role, is_active=True)
            for i, role in enumerate(("member", "officer", "admin", "unknown"))
        ]
        db.rows["posts"] = [dict(id=b["id"], board_id=b["id"], title="라쇼몽 " + b["slug"]) for b in db.rows["boards"]]
        db.rows["posts"].append(dict(id=99, board_id=0, title="라쇼몽 deleted", deleted_at="yesterday"))
        self.client = self.module.app.test_client()

    def login(self, role, preview=False, client=None):
        member = self.db.rows["members"][0 if role == "member" else 1]
        member.update(role=role)
        with (client or self.client).session_transaction() as state:
            state.update(user_id=member["id"], user_role=role, auth_provider="kakao", member_preview=preview)

    def test_landing_and_preview(self):
        guest = self.client.get("/").get_data(as_text=True)
        dom = BeautifulSoup(guest, "html.parser")
        first_book_href = dom.select_one(".books a[href^='/archive/']")["href"]
        self.assertEqual(len(dom.select(".books a[href^='/archive/']")), 6)
        self.assertIsNotNone(dom.select_one('meta[name="app-layout"][content="public-landing"]'))
        self.assertIsNone(dom.select_one("[data-lms-quick-search]"))
        self.assertIsNone(dom.select_one("#lms-quick-search-items"))
        self.assertIsNone(dom.select_one(".lms-global"))
        self.assertIsNone(dom.select_one(".lms-breadcrumb"))
        self.assertNotIn("quick_search.js", guest)
        self.assertTrue(dom.select_one("header nav a[href='/archive']"))
        self.assertTrue(dom.select_one("header nav a[href='/login']"))
        self.assertIsNone(dom.select_one(".actions a[href='/login']"))
        self.assertTrue(dom.select_one(".actions a[href='/archive']"))
        for forbidden in ("notion.site", "동아리 소개(외부)", "shared_topics", "/topics/", "발제문 작성",
                          'id="lms-global"', "202600001", "지금 해야 할 일", "공개 캘린더", "동아리방", "이용안내"):
            self.assertNotIn(forbidden, guest)
        for title in ("필담", "미식회", "벽돌책"):
            self.assertIn(title, guest)

        for public_path in ("/archive", first_book_href):
            resp = self.client.get(public_path)
            self.assertEqual(resp.status_code, 200, public_path)
            pub_html = resp.get_data(as_text=True)
            pub_dom = BeautifulSoup(pub_html, "html.parser")
            self.assertIsNotNone(pub_dom.select_one('meta[name="app-layout"][content="public-landing"]'), public_path)
            self.assertIsNone(pub_dom.select_one("#lms-global"), public_path)
            self.assertIsNone(pub_dom.select_one(".lms-breadcrumb"), public_path)
            self.assertIsNone(pub_dom.select_one("[data-lms-quick-search]"), public_path)
            self.assertNotIn("quick_search.js", pub_html, public_path)
            self.assertIsNotNone(pub_dom.select_one("header.mast nav a[href='/archive']"), public_path)
            self.assertIsNotNone(pub_dom.select_one("header.mast nav a[href='/login']"), public_path)

        self.login("admin")
        self.assertEqual(BeautifulSoup(self.client.get("/landing").data, "html.parser").main, dom.main)
        archive_logged_in = BeautifulSoup(self.client.get("/archive").data, "html.parser")
        self.assertIsNotNone(archive_logged_in.select_one('meta[name="app-layout"][content="canvas"]'))

        dash = BeautifulSoup(self.client.get("/").data, "html.parser")
        self.assertIsNone(dash.select_one(".lms-breadcrumb"))
        self.assertIsNone(dash.select_one(".lms-global [data-lms-quick-search]"))
        self.assertIsNotNone(dash.select_one(".lms-dashboard-heading [data-lms-quick-search]"))
        self.assertIsNotNone(dash.select_one(".lms-mobile-header [data-lms-quick-search]"))
        self.assertIsNotNone(dash.select_one("a[href='/landing']"))
        self.assertNotIn("notion", str(dash).lower())

        cal = BeautifulSoup(self.client.get("/calendar").data, "html.parser")
        self.assertIsNone(cal.select_one(".lms-global [data-lms-quick-search]"))
        self.assertIsNotNone(cal.select_one(".lms-breadcrumb [data-lms-quick-search]"))
        self.assertIsNotNone(cal.select_one(".lms-mobile-header [data-lms-quick-search]"))
        self.assertIsNotNone(cal.select_one("a[href='/landing']"))
        self.assertNotIn("notion", str(cal).lower())
        self.assertIn('data-lms-page="dashboard"', self.client.get("/").get_data(as_text=True))

    def test_topics_only_listed_for_members(self):
        event = self.db.rows["topic_events"][0]
        event.update(meeting_date="2099-09-23", seminar_week_id=None, book_title="공유 링크 테스트")
        html = self.client.get("/now").get_data(as_text=True)
        self.assertFalse(any(call[1] == "topic_events" for call in self.db.calls))
        self.assertIn("열려 있는 신청·후기를 확인하세요.", html)
        self.assertNotIn(event["share_token"], html)
        self.assertNotIn("발제문", html)
        for path in ("/topics/share-test", "/shared_topics?token=share-test"):
            response = self.client.get(path, follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            self.assertIn("공유 링크 테스트", response.get_data(as_text=True))
        self.login("member")
        html = self.client.get("/now").get_data(as_text=True)
        self.assertIn(event["share_token"], html)
        self.assertIn("신청·발제문·후기", html)

    def test_role_scoped_results(self):
        cases = [(None, False), ("member", False), ("officer", False),
                 ("admin", False), ("admin", True), ("officer", True)]
        for role, preview in cases:
            with self.subTest(role=role, preview=preview):
                client = self.module.app.test_client()
                if role:
                    self.login(role, preview, client)
                response = client.get("/api/search", query_string={"q": " 라쇼몽 "})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["Cache-Control"],
                                 "private, no-store, max-age=0" if role else "public, max-age=30")
                self.assertEqual(response.json["query"], "라쇼몽")
                results = response.json["results"]
                groups = {item["group"] for item in results}
                titles = {item["title"] for item in results}
                self.assertTrue(all(set(item) == {"group", "url", "title", "description"} for item in results))
                self.assertIn("아카이브", groups)
                staff = role in ("officer", "admin") and not preview
                self.assertEqual("회원" in groups, staff)
                self.assertEqual("운영진:라쇼몽" in titles, staff)
                self.assertEqual("라쇼몽 officer" in titles, staff)
                self.assertEqual("라쇼몽 admin" in titles, role == "admin" and not preview)
                self.assertEqual("라쇼몽 member" in titles, bool(role))
                self.assertEqual("라쇼몽 안내" in titles, bool(role))
                self.assertEqual("세미나 전 자료" in groups, bool(role))
                self.assertFalse({"라쇼몽 deleted", "라쇼몽 unknown"} & titles)
                self.assertFalse(any("202600001" in item["description"] for item in results))
                if role:
                    public = client.get("/api/search", query_string={"q": "라쇼몽", "scope": "public"})
                    self.assertEqual({item["group"] for item in public.json["results"]}, {"아카이브"})

    def test_search_limits_missing_sources_and_seminars(self):
        client, db = self.client, self.db
        self.assertEqual(client.get("/api/search?q=%20").json, {"query": "", "results": []})
        self.assertEqual(len(client.get("/api/search?q=" + "a" * 120).json["query"]), 100)
        self.login("admin")
        self.assertEqual(len(client.get("/api/search?q=라쇼몽&limit=1").json["results"]), 1)
        self.module.app.config["WIKI_DATABASE"] += ".missing"
        original = FakeSupabase.table

        def broken(name):
            if name == "boards":
                raise RuntimeError("boards down")
            return original(db, name)

        with patch.object(db, "table", side_effect=broken):
            response = client.get("/api/search?q=라쇼몽")
            self.assertEqual(response.status_code, 200)
            self.assertIn("아카이브", {i["group"] for i in response.json["results"]})
        results = client.get("/api/search?q=표류도").json["results"]
        self.assertIn("/records/seminars/history", {i["url"] for i in results})
        self.login("member")
        results = client.get("/api/search?q=2026-09-17").json["results"]
        self.assertEqual({i["url"] for i in results if i["group"] == "세미나"}, {"/seminars?term_id=term"})

    def test_docs_fallback(self):
        self.module.app.config["WIKI_ENABLED"] = False
        self.login("member")
        self.assertEqual(self.client.get("/docs").location, "/archive")


if __name__ == "__main__":
    unittest.main()
