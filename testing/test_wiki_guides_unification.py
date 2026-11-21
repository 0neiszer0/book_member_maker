"""Tests for unifying member/officer help into the wiki.

Covers the internal-link rewrite in clean_wiki_html, the /help and /help/admin
redirect/fallback behaviour, the guide source files under content/wiki_guides,
and the idempotent scripts/sync_wiki_guides.py sync logic.
"""
import importlib
import importlib.util
import os
import unittest
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from testing._fake_supabase import FakeSupabase
from wiki_routes import clean_wiki_html


ROOT = Path(__file__).resolve().parents[1]
GUIDES_DIR = ROOT / "content" / "wiki_guides"
MEMBER_GUIDE = GUIDES_DIR / "member_guide.namu"
OFFICER_GUIDE = GUIDES_DIR / "officer_guide.namu"


def guide_fixture(today=None):
    today = today or date(2026, 10, 28)
    return {
        "members": [
            dict(id=1, name="활동 회원", social_id="9001", role="member",
                 is_active=True, account_status="active", member_status="active"),
            dict(id=2, name="관리자", social_id="9002", role="admin",
                 is_active=True, account_status="active", member_status="active"),
            dict(id=3, name="운영진", social_id="9003", role="officer",
                 is_active=True, account_status="active", member_status="active"),
        ],
        "seminar_terms": [dict(id="current", name="2026년 2학기", is_active=True,
            start_date=(today - timedelta(days=30)).isoformat(),
            end_date=(today + timedelta(days=30)).isoformat(),
            roster_initialized_at="2026-09-01")],
        "seminar_term_members": [dict(term_id="current", member_id=1, status="active")],
    }


def load_sync_module():
    spec = importlib.util.spec_from_file_location(
        "sync_wiki_guides", ROOT / "scripts" / "sync_wiki_guides.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CleanWikiHtmlTests(unittest.TestCase):
    def test_internal_links_preserve_path_query_and_fragment(self):
        html = str(clean_wiki_html(
            '<a href="https://knu-read.xyz/seminars?term_id=term#weekly">세미나</a>'
            '<a href="https://knu-read.xyz/my/term_attendance">내 출석</a>'
        ))
        self.assertIn("/seminars?term_id=term#weekly", html)
        self.assertIn("/my/term_attendance", html)
        # The absolute site URL is rewritten to a same-site relative shortcut.
        self.assertNotIn("https://knu-read.xyz", html)

    def test_dangerous_schemes_and_engine_links_are_still_blocked(self):
        html = str(clean_wiki_html(
            '<a href="javascript:alert(1)">bad</a>'
            '<a href="/manager">native</a>'
            '<a href="/edit/문서">engine edit</a>'
        ))
        self.assertNotIn("javascript:", html)
        self.assertNotIn("/manager", html)
        self.assertNotIn("/edit/", html)

    def test_external_links_keep_rel_attribute(self):
        html = str(clean_wiki_html('<a href="https://example.com/x">외부</a>'))
        self.assertIn('href="https://example.com/x"', html)
        self.assertIn('rel="noreferrer noopener"', html)


class WikiGuideContentTests(unittest.TestCase):
    def read(self, path):
        return path.read_text(encoding="utf-8")

    def test_member_guide_has_no_officer_links_and_valid_hyperlinks(self):
        source = self.read(MEMBER_GUIDE)
        self.assertNotIn("운영진:", source)
        for link in (
            "[[https://knu-read.xyz/seminars|세미나 일정]]",
            "[[https://knu-read.xyz/my/term_attendance|내 학기 참석 현황]]",
            "[[https://knu-read.xyz/mypage|내 활동]]",
            "[[https://knu-read.xyz/club-room|동아리방 시간표·신청]]",
            "[[https://knu-read.xyz/boards|공지·게시판]]",
            "[[https://knu-read.xyz/archive|역대 커리큘럼 아카이브]]",
            "[[https://knu-read.xyz/pre-seminar|세미나 전 자료]]",
            "[[https://knu-read.xyz/books/suggest|책 추천]]",
        ):
            self.assertIn(link, source)
        self.assertIn("[목차]", source)
        self.assertIn("Ctrl+K", source)

    def test_officer_guide_contains_core_admin_hyperlinks(self):
        source = self.read(OFFICER_GUIDE)
        for link in (
            "[[https://knu-read.xyz/admin/dashboard|이번 주 운영 개요]]",
            "[[https://knu-read.xyz/admin/seminars|세미나 운영]]",
            "[[https://knu-read.xyz/making_team|조 편성]]",
            "[[https://knu-read.xyz/admin/term_attendance|학기 참석 현황]]",
            "[[https://knu-read.xyz/records/members|회원·계정 관리]]",
            "[[https://knu-read.xyz/admin/term_members|학기 회원 명단]]",
            "[[https://knu-read.xyz/records/seminars|세미나 진행 현황]]",
            "[[https://knu-read.xyz/records/analytics|활동 통계·출석표]]",
            "[[https://knu-read.xyz/admin/seminar_rooms|세미나실 예약]]",
            "[[https://knu-read.xyz/admin/handover|임원 인수인계 설문]]",
            "[[https://knu-read.xyz/admin/privacy|개인정보 정리]]",
            "[[https://knu-read.xyz/admin/bug-reports|버그 제보]]",
        ):
            self.assertIn(link, source)
        self.assertIn("[목차]", source)
        self.assertIn("미연락 불참", source)

    def test_wiki_css_styles_internal_app_links(self):
        css = (ROOT / "static" / "lms_wiki.css").read_text(encoding="utf-8")
        self.assertIn('.wiki-prose a[href^="/"]:not([href^="/wiki/"])', css)


class SyncWikiGuidesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_sync_module()

    def test_ensure_officer_home_link_under_existing_section(self):
        source = "== 대문 ==\n안내\n\n== 업무별 문서 ==\n[[운영진:회장 가이드]]\n"
        updated, changed = self.mod.ensure_officer_home_link(source)
        self.assertTrue(changed)
        self.assertIn(self.mod.OFFICER_HOME_LINK, updated)
        # Inserted inside the 업무별 문서 section, right after the heading.
        self.assertLess(
            updated.index("== 업무별 문서 =="),
            updated.index(self.mod.OFFICER_HOME_LINK),
        )

    def test_ensure_officer_home_link_never_duplicates(self):
        existing = "== 업무별 문서 ==\n[[운영진:운영 안내|사이트 운영 매뉴얼 (바로가기 포함)]]\n"
        updated, changed = self.mod.ensure_officer_home_link(existing)
        self.assertFalse(changed)
        self.assertEqual(updated, existing)
        self.assertEqual(updated.count(self.mod.OFFICER_HOME_LINK), 1)

    def test_ensure_officer_home_link_appends_when_section_missing(self):
        source = "== 인사 ==\n안녕하세요.\n"
        updated, changed = self.mod.ensure_officer_home_link(source)
        self.assertTrue(changed)
        self.assertIn(self.mod.OFFICER_HOME_LINK, updated)

    def test_sync_dry_run_reports_without_writing(self):
        engine = StubEngine()
        actions = self.mod.sync(engine, 7, dry_run=True)
        titles = {a["title"] for a in actions}
        self.assertIn(self.mod.MEMBER_TITLE, titles)
        self.assertIn(self.mod.OFFICER_TITLE, titles)
        self.assertEqual(engine.saves, [])

    def test_sync_apply_then_rerun_is_idempotent(self):
        engine = StubEngine()
        engine.pages[self.mod.OFFICER_HOME_TITLE] = "== 업무별 문서 ==\n[[운영진:회장 가이드]]\n"

        first = self.mod.sync(engine, 7, dry_run=False)
        self.assertEqual({a["action"] for a in first}, {"create", "update"})
        self.assertEqual(len(engine.saves), 3)

        second = self.mod.sync(engine, 7, dry_run=False)
        self.assertEqual(second, [])
        self.assertEqual(len(engine.saves), 3, "re-run must not write again")

        # The officer home page now carries the guide link exactly once.
        home = engine.pages[self.mod.OFFICER_HOME_TITLE]
        self.assertEqual(home.count(self.mod.OFFICER_HOME_LINK), 1)
        self.assertEqual(engine.pages[self.mod.MEMBER_TITLE],
                         (MEMBER_GUIDE).read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n"))


class StubEngine:
    """Minimal OpenNamu stand-in: stores pages in memory and records saves."""

    def __init__(self):
        self.pages = {}
        self.saves = []

    @contextmanager
    def user(self, member_id):
        yield None

    def document(self, client, title, revision=None):
        if title in self.pages:
            return dict(title=title, source=self.pages[title], exists=True,
                        version="1", history=[["1", "", "2026-10-28", "a", "init"]])
        return dict(title=title, source="", exists=False, version="0", history=[])

    def save(self, client, title, content, summary, version):
        self.saves.append((title, content, summary, version))
        self.pages[title] = content


class HelpUnificationRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        environment = patch.dict(os.environ, dict(
            PYTHON_DOTENV_DISABLED="1", FLASK_SECRET_KEY="wiki-guides-test-only",
            SUPABASE_URL="http://127.0.0.1:9", SUPABASE_SERVICE_KEY="wiki-guides-test-only",
            PUBLIC_BASE_URL="http://localhost", SESSION_COOKIE_SECURE="0"))
        environment.start()
        cls.addClassCleanup(environment.stop)
        with patch("supabase.create_client", return_value=FakeSupabase()), patch("dotenv.load_dotenv"):
            cls.module = importlib.import_module("app")
        config = patch.dict(cls.module.app.config, TESTING=True, WIKI_ENABLED=True,
                            SESSION_COOKIE_SECURE=False)
        config.start()
        cls.addClassCleanup(config.stop)
        base_url = patch.object(cls.module, "PUBLIC_BASE_URL", "http://localhost")
        base_url.start()
        cls.addClassCleanup(base_url.stop)

    def setUp(self):
        from datetime import datetime, timezone
        today = datetime.now(timezone(timedelta(hours=9))).date()
        self.db = FakeSupabase(guide_fixture(today))
        database = patch.object(self.module, "supabase", self.db)
        database.start()
        self.addCleanup(database.stop)
        self.module.app.extensions["officer_wiki_nav_cache"].clear()
        self.client = self.module.app.test_client()

    def login(self, member=1, role="member"):
        with self.client.session_transaction() as s:
            s.clear()
            s.update(user_id=member, user_role=role, user_name="예시 회원",
                     auth_provider="kakao", wiki_csrf="token")

    def member_wiki_url(self):
        with self.module.app.test_request_context():
            return self.module.url_for("wiki.document", title="사이트 이용 안내")

    def officer_wiki_url(self):
        with self.module.app.test_request_context():
            return self.module.url_for("wiki.document", title="운영진:운영 안내")

    # --- GET /help (help_member) ---

    def test_help_redirects_logged_in_member_to_wiki(self):
        self.login(1, "member")
        response = self.client.get("/help/member")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, self.member_wiki_url())

    def test_help_renders_fallback_when_wiki_disabled(self):
        self.login(1, "member")
        with patch.dict(self.module.app.config, WIKI_ENABLED=False):
            response = self.client.get("/help/member")
        self.assertEqual(response.status_code, 200)
        self.assertIn("참여 전 확인할 3가지", response.get_data(as_text=True))

    def test_help_renders_fallback_with_classic_param(self):
        self.login(1, "member")
        response = self.client.get("/help/member?classic=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("참여 전 확인할 3가지", response.get_data(as_text=True))

    def test_help_logged_out_never_redirects_to_wiki(self):
        response = self.client.get("/help/member")
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("/wiki/", response.location or "")

    # --- GET /help/admin (help_admin) ---

    def test_help_admin_redirects_admin_to_wiki(self):
        self.login(2, "admin")
        response = self.client.get("/help/admin")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, self.officer_wiki_url())

    def test_help_admin_redirects_officer_to_wiki(self):
        self.login(3, "officer")
        response = self.client.get("/help/admin")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, self.officer_wiki_url())

    def test_help_admin_renders_fallback_when_wiki_disabled(self):
        self.login(2, "admin")
        with patch.dict(self.module.app.config, WIKI_ENABLED=False):
            response = self.client.get("/help/admin")
        self.assertEqual(response.status_code, 200)
        self.assertIn("매주 하는 일", response.get_data(as_text=True))

    def test_help_admin_renders_fallback_with_classic_param(self):
        self.login(2, "admin")
        response = self.client.get("/help/admin?classic=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("매주 하는 일", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
