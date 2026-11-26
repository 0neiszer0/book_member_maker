"""Unit tests for public archive (/archive), public pre-seminar materials (/pre-seminar), and zero-PII guarantees."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from testing._fake_supabase import FakeSupabase
from testing.test_home_overview import fixture

os.environ.setdefault("PYTHON_DOTENV_DISABLED", "1")
os.environ.setdefault("FLASK_SECRET_KEY", "ci-test-only")
os.environ.setdefault("SUPABASE_URL", "http://127.0.0.1:9")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "ci-test-only")

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ARCHIVE_JSON = ROOT / "content" / "public_archive.json"
PRE_SEMINAR_JSON = ROOT / "content" / "member_pre_seminar_materials.json"


class PublicArchiveAndPreSeminarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fake = FakeSupabase()
        spec = importlib.util.spec_from_file_location("_public_archive_app", ROOT / "app.py")
        cls.module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.module
        with patch("supabase.create_client", return_value=cls.fake):
            spec.loader.exec_module(cls.module)

    def setUp(self):
        rows = fixture()
        rows["members"][0].update(gender="F", email="member@example.test", role="member")
        rows["members"][1].update(gender="M", email="admin@example.test", role="admin")
        self.fake.rows = rows
        self.fake.calls.clear()
        self.module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = self.module.app.test_client()

    def login(self, role="member", user_id=None, csrf="test-csrf"):
        if user_id is None:
            user_id = 2 if role in ("admin", "officer") else 1
        if role == "officer":
            self.fake.rows["members"][1]["role"] = "officer"
        with self.client.session_transaction() as state:
            state.clear()
            state.update(
                user_id=user_id,
                user_role=role,
                user_name="테스트 회원",
                sensitive_csrf=csrf,
            )

    def _extract_quick_search_urls(self, html: str) -> set[str]:
        match = re.search(
            r'<script id="lms-quick-search-items" type="application/json">(.*?)</script>',
            html,
            re.S,
        )
        self.assertIsNotNone(match)
        return {item["url"] for item in json.loads(match.group(1))}

    # --- 1. Snapshot Data Integrity & Strict Automated PII Scan ---

    def test_snapshot_files_exist_with_expected_coverage(self):
        self.assertTrue(PUBLIC_ARCHIVE_JSON.exists(), "content/public_archive.json must exist")
        self.assertTrue(PRE_SEMINAR_JSON.exists(), "content/member_pre_seminar_materials.json must exist")

        pub = json.loads(PUBLIC_ARCHIVE_JSON.read_text(encoding="utf-8"))
        books = pub.get("books", [])
        self.assertGreaterEqual(len(books), 42)
        semesters = {b["semester"] for b in books}
        self.assertEqual(semesters, {"2025-2", "2026-겨울", "2026-1", "2026-여름", "2026-2"})
        self.assertGreaterEqual(sum(1 for b in books if b.get("has_prompts")), 25)
        self.assertGreaterEqual(sum(1 for b in books if b.get("has_discussion")), 25)

        demian = next((b for b in books if b["slug"] == "2026-2-demian"), None)
        self.assertIsNotNone(demian)
        self.assertEqual(demian.get("status_note"), "이미지 기록 보관 중")

        pre = json.loads(PRE_SEMINAR_JSON.read_text(encoding="utf-8"))
        pre_books = pre.get("books", [])
        self.assertEqual(len(pre_books), 15)
        self.assertEqual(sum(1 for b in pre_books if b["semester"] == "2026-여름"), 7)
        self.assertEqual(sum(1 for b in pre_books if b["semester"] == "2026-2"), 8)

    def test_strict_pii_scanner_over_generated_json_bytes(self):
        for json_path in (PUBLIC_ARCHIVE_JSON, PRE_SEMINAR_JSON):
            raw_bytes = json_path.read_bytes()
            text = raw_bytes.decode("utf-8")
            with self.subTest(file=json_path.name):
                self.assertIsNone(
                    re.search(r"(?<!\d)01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}(?!\d)", text),
                    f"Phone number leaked in {json_path.name}",
                )
                self.assertIsNone(
                    re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text),
                    f"Email leaked in {json_path.name}",
                )
                self.assertIsNone(
                    re.search(r"\b20[12]\d{6,7}\b", text),
                    f"8-10 digit student ID leaked in {json_path.name}",
                )
                self.assertIsNone(
                    re.search(
                        r"(?:국민|신한|우리|하나|농협|기업|카카오뱅크|토스뱅크|새마을|우체국|대구)\s*[:\-]?\s*\d{2,6}[-\s]?\d{2,6}",
                        text,
                    ),
                    f"Bank account leaked in {json_path.name}",
                )

        pub_text = PUBLIC_ARCHIVE_JSON.read_text(encoding="utf-8")
        # Ensure cover-table department+year and student-number combos never leak into public archive
        self.assertIsNone(
            re.search(r"[가-힣]{2,14}(?:학과|학부|전공)\s*(?:\(\s*\d{2}\s*\)|\d{2}\s*학번)", pub_text),
            "Department + admission year leaked in public_archive.json",
        )
        self.assertIsNone(
            re.search(r"\b(?:1[89]|2[0-6])\s*학번", pub_text),
            "Admission year ('XX학번') leaked in public_archive.json",
        )
        # Ensure presenter headers only contain anonymous letters (발제자 A..Z)
        for m in re.finditer(r"발제자\s*[:：]\s*([가-힣]{2,4})", pub_text):
            self.fail(f"Unmasked presenter name header in public_archive.json: {m.group(0)!r}")
        # Ensure zero unmasked member "<이름>님" references slip through
        honorific_allowlist = {
            "선생", "작가", "교수", "하나", "하느", "부모", "어머", "아버", "할머", "할아", "조부모",
            "오라버", "누", "형", "도련", "사모", "아드", "따", "어르", "주인", "임금", "여왕",
            "신부", "목사", "스", "큰스", "부처", "보살", "손", "사장", "회장", "부회장", "회원",
            "선배", "후배", "대표", "팀장", "실장", "원장", "총장", "학장", "부원", "의사", "간호사",
            "기사", "라이더", "판사", "검사", "변호사", "감독", "기자", "시인", "철학자", "소설가",
            "화자", "주인공", "인물", "독자", "역자", "번역가", "편집자", "평론가", "타인",
            "선조", "선대", "장군", "대장", "사제", "수녀", "고승", "대사", "전하", "폐하",
            "마마", "나으", "대감", "영감", "참여자", "발제자", "사회자", "서기", "다른",
            "대한민국", "조국", "어린이",
            # Verified literary characters/authors only
            "포퍼", "예수", "경하", "인선", "나까무라", "소크라테스", "베르테르",
        }
        honorific_suffixes = (
            "선생", "작가", "교수", "회장", "부회장", "선배", "후배", "참여자", "사회자", "발제자", "서기",
            "부모", "어머", "아버", "할머", "할아", "스", "사장", "의사", "기사", "라이더",
            "대표", "감독", "기자", "시인", "주인", "임금", "신부", "목사",
        )
        nim_particle_tail = (
            r"(?=$|[^가-힣]|"
            r"(?:께서(?:는|도|만)?|에서(?:는|도|만)?|부터(?:는|도|만)?|까지(?:는|도|만)?|"
            r"처럼(?:은|도|만)?|보다(?:는|도|만)?|한테(?:서|는|도|만)?|에게(?:서|는|도|만)?|"
            r"이랑|이라(?:고|서|도|는|면)?|이고|이다|이시|이야|이나|하고|과도|과는|와도|와는|"
            r"들(?:의|이|을|은|과|도|한테|에게|이랑)?|"
            r"의|이|가|은|는|을|를|도|만|께|과|와|랑|야|고|시|라)(?=$|[^가-힣]))"
        )
        for m in re.finditer(rf"([가-힣]{{2,5}})\s*님{nim_particle_tail}", pub_text):
            tok = m.group(1)
            if tok in honorific_allowlist or tok.endswith(honorific_suffixes):
                continue
            self.fail(
                f"Unmasked '<이름>님' mention in public_archive.json: <{len(tok)}-char token>"
            )
        # Also guard against PDF-split 2-char names before 님 ("X Y님")
        allowed_1char_prefix = {"내", "그", "이", "저", "한", "두", "세", "네"}
        for m in re.finditer(rf"(?<![가-힣])([가-힣])\s+([가-힣])\s*님{nim_particle_tail}", pub_text):
            w1, w2 = m.group(1), m.group(2)
            joined = w1 + w2
            if joined in honorific_allowlist or w1 in allowed_1char_prefix or w2 in {"아", "스", "손", "형", "누"}:
                continue
            self.fail(
                "Unmasked spaced '<X Y>님' mention in public_archive.json"
            )
        # Ensure no banned numeric 26-1 stats
        for banned in ("2,397", "2397", "34시간"):
            self.assertNotIn(banned, pub_text)

    # --- 2. Public Archive Routes (/archive & /archive/<slug>) ---

    def test_public_archive_renders_200_without_login(self):
        resp = self.client.get("/archive")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn('name="app-layout" content="public-landing"', html)
        self.assertNotIn('id="lms-global"', html)
        self.assertNotIn('id="lms-content"', html)
        self.assertNotIn('data-lms-quick-search', html)
        self.assertNotIn('quick_search.js', html)
        self.assertIn('header class="mast"', html)
        self.assertIn("역대 커리큘럼·발제·토의 아카이브", html)
        self.assertIn("필담", html)
        self.assertIn("미식회", html)
        for banned in ("2,397", "2397", "34시간"):
            self.assertNotIn(banned, html)
        # Pre-seminar reading materials are public now: guests get the link too
        self.assertIn('href="/pre-seminar"', html)
        self.assertIn("세미나 전 자료 보기", html)
        self.assertNotIn("회원 전용 세미나 전 자료", html)

        # Logged-in members still receive the Canvas LMS shell on /archive
        self.login("member")
        member_html = self.client.get("/archive").get_data(as_text=True)
        self.assertIn('name="app-layout" content="canvas"', member_html)
        self.assertEqual(member_html.count('id="lms-global"'), 1)
        urls = self._extract_quick_search_urls(member_html)
        self.assertIn("/archive", urls)
        self.assertIn("/pre-seminar", urls)

    def test_public_archive_semester_filter_and_keyword_search(self):
        sem_resp = self.client.get("/archive?semester=2026-1")
        self.assertEqual(sem_resp.status_code, 200)
        sem_html = sem_resp.get_data(as_text=True)
        self.assertIn("위대한 개츠비", sem_html)
        self.assertIn("표시 중인 도서 <strong>10권</strong>", sem_html)
        self.assertNotIn("브람스를 좋아하세요...", sem_html)

        q_resp = self.client.get("/archive?q=페스트")
        self.assertEqual(q_resp.status_code, 200)
        q_html = q_resp.get_data(as_text=True)
        self.assertIn("페스트", q_html)
        self.assertNotIn("고도를 기다리며", q_html)

    def test_public_archive_book_detail_and_404(self):
        ok = self.client.get("/archive/2025-2-the-plague")
        self.assertEqual(ok.status_code, 200)
        html = ok.get_data(as_text=True)
        self.assertIn("페스트", html)
        self.assertIn("도서별 발제문", html)
        self.assertIn("전체 토의 내용 (서기 정리본)", html)
        self.assertIn("발제자 A", html)
        self.assertIn("참여자 A", html)

        demian = self.client.get("/archive/2026-2-demian")
        self.assertEqual(demian.status_code, 200)
        self.assertIn("이미지 기록 보관 중", demian.get_data(as_text=True))

        missing = self.client.get("/archive/nonexistent-book-slug")
        self.assertEqual(missing.status_code, 404)

    # --- 3. Member-Only Pre-Seminar Routes (/pre-seminar & /pre-seminar/<slug>) ---

    def test_pre_seminar_public_access_and_login_cta(self):
        cases = {
            "/pre-seminar": "/login?next=%2Fpre-seminar",
            "/pre-seminar/2026-summer-rashomon": "/login?next=%2Fpre-seminar%2F2026-summer-rashomon",
        }
        for path, login_href in cases.items():
            with self.subTest(path=path):
                resp = self.client.get(path)
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.headers.get("Cache-Control"), "private, no-store")
                html = resp.get_data(as_text=True)
                self.assertIn('name="app-layout" content="public-landing"', html)
                self.assertIn('header class="mast"', html)
                self.assertNotIn('id="lms-global"', html)
                self.assertNotIn("quick_search.js", html)
                self.assertIn(f'href="{login_href}"', html)
                self.assertIn('class="pre-toplink-login"', html)
                self.assertIn('class="pre-login-cta"', html)
                self.assertIn("회원 로그인하기", html)
                self.assertIn("로그인하고 발제문·세미나 일정 보기", html)
                for leak in ("/admin/pre-seminar", "/seminars?term_id=", "/seminars/topics/", "사전 자료 관리"):
                    self.assertNotIn(leak, html)
                # Reading material starts before the login invitation card
                self.assertLess(html.index('class="pre-detail-head"'), html.index('class="pre-login-cta"'))

        filtered = self.client.get("/pre-seminar?semester=2026-2").get_data(as_text=True)
        self.assertIn('href="/login?next=%2Fpre-seminar%3Fsemester%3D2026-2"', filtered)

        self.fake.rows["pre_seminar_materials"] = [{
            "id": "draft", "slug": "secret-draft", "title": "비공개 초안", "semester": "2027-1",
            "semester_label": "2027년 1학기", "markdown_body": "## 초안", "is_published": False,
            "created_at": "2026-11-01T00:00:00Z",
        }]
        self.assertEqual(self.client.get("/pre-seminar/secret-draft").status_code, 404)
        self.assertNotIn("비공개 초안", self.client.get("/pre-seminar").get_data(as_text=True))

        admin = self.client.get("/admin/pre-seminar")
        self.assertEqual(admin.status_code, 302)
        self.assertIn("/login", admin.headers.get("Location", ""))

    def test_pre_seminar_logged_in_member_can_read_all_15_books(self):
        self.login("member")

        home_urls = self._extract_quick_search_urls(self.client.get("/").get_data(as_text=True))
        self.assertIn("/archive", home_urls)
        self.assertIn("/pre-seminar", home_urls)

        resp = self.client.get("/pre-seminar")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("Cache-Control"), "private, no-store")
        html = resp.get_data(as_text=True)
        self.assertIn('name="app-layout" content="canvas"', html)
        self.assertIn('id="lms-global"', html)
        self.assertNotIn('class="pre-login-cta"', html)
        self.assertNotIn('class="pre-toplink-login"', html)
        self.assertNotIn("회원 로그인하기", html)
        self.assertNotIn("로그인하고 발제문·세미나 일정 보기", html)
        self.assertIn("전체 (15권)", html)
        self.assertIn("라쇼몬", html)
        self.assertIn("클라라와 태양", html)

        klara = self.client.get("/pre-seminar/2026-2-klara-and-the-sun")
        self.assertEqual(klara.status_code, 200)
        klara_html = klara.get_data(as_text=True)
        self.assertIn("클라라와 태양", klara_html)
        self.assertIn('target="_blank" rel="noopener noreferrer"', klara_html)

        missing = self.client.get("/pre-seminar/unknown-book-slug")
        self.assertEqual(missing.status_code, 404)


class MarkdownPublisherTests(PublicArchiveAndPreSeminarTests):
    def test_parser_and_slug(self):
        from public_archive_routes import parse_pre_seminar_markdown, _slugify_material
        parsed = parse_pre_seminar_markdown("Intro **bold** *em* `code` [safe](https://example.com) [bad](javascript:alert) <script>\n\n## Heading\n- item\n1. second\n> quote\n| a | b |\n|---|---|\n| x | y |\n### Sub\nhttp://example.org")
        self.assertEqual([s["heading"] for s in parsed["sections"]], ["개요", "Heading", "Sub"])
        runs = parsed["sections"][0]["items"][0]["runs"]
        self.assertTrue(any(r.get("strong") for r in runs))
        self.assertTrue(any(r.get("em") for r in runs))
        self.assertTrue(any(r.get("code") for r in runs))
        self.assertEqual(len(parsed["references"]), 2)
        self.assertFalse(any("javascript:" in r.get("href", "") for r in runs))
        items = parsed["sections"][1]["items"]
        self.assertEqual([i["type"] for i in items], ["li", "li", "quote", "table"])
        self.assertEqual(len(items[-1]["rows"]), 2)
        self.assertEqual(_slugify_material("한글 제목"), "한글-제목")
        with self.assertRaises(ValueError):
            _slugify_material("title", "../bad")

    def test_admin_lifecycle_and_member_visibility(self):
        self.assertEqual(self.client.get('/admin/pre-seminar').status_code, 302)
        self.login('member')
        self.assertEqual(self.client.get('/admin/pre-seminar').status_code, 302)
        self.login('officer')
        self.assertEqual(self.client.get('/admin/pre-seminar').status_code, 200)
        self.assertEqual(self.client.post('/admin/pre-seminar/save', data={'title':'x','markdown_body':'x'}).status_code, 403)
        data={'csrf_token':'test-csrf','title':'새 도서','author':'작가','semester':'2027-1','semester_label':'2027년 1학기','markdown_body':'## 본문\n<script>alert(1)</script> **강조**','is_published':'on'}
        self.assertEqual(self.client.post('/admin/pre-seminar/save', data=data).status_code, 303)
        row=self.fake.rows['pre_seminar_materials'][0]
        self.assertEqual(self.client.post('/admin/pre-seminar/save', data=data).status_code, 303)
        self.assertEqual(self.fake.rows['pre_seminar_materials'][1]['slug'], row['slug']+'-2')
        detail=self.client.get('/pre-seminar/'+row['slug']).get_data(as_text=True)
        self.assertIn('새 도서',detail)
        self.assertIn('&lt;script&gt;',detail)
        self.assertIn('<strong>강조</strong>',detail)
        self.assertNotIn('발제문·토의 기록 보기',detail)
        self.assertIn('2027년 1학기',detail)
        self.assertIn('전체 (17권)',detail)
        headers={'X-App-CSRF':'test-csrf'}
        preview=self.client.post('/api/admin/pre-seminar/preview',json={'markdown_body':'## 제목'},headers=headers)
        self.assertEqual(preview.json['sections'][0]['heading'],'제목')
        self.assertEqual(self.client.post('/api/admin/pre-seminar/'+row['id']+'/toggle',headers=headers).status_code,200)
        self.assertEqual(self.client.get('/pre-seminar/'+row['slug']).status_code,404)
        self.assertEqual(self.client.get('/admin/pre-seminar?edit='+row['id']).status_code,200)
        data.update(material_id=row['id'],title='고친 제목')
        self.assertEqual(self.client.post('/admin/pre-seminar/save',data=data).status_code,303)
        self.assertEqual(self.fake.rows['pre_seminar_materials'][0]['title'],'고친 제목')
        self.assertEqual(self.client.post('/api/admin/pre-seminar/'+row['id']+'/delete',headers=headers).status_code,200)
        self.login('admin')
        self.assertEqual(self.client.get('/admin/pre-seminar').status_code,200)


GODOT_MD = """# 요약본

## 제1막

블라디미르와 에스트라공이 *고도*를 기다린다.

- 첫 장면
- 두 번째 장면

## 제2막

### 다음 날

나무에 잎이 돋았다.

# 인물과 관계

에스트라공과 블라디미르.

---

**본문 기준:** 사뮈엘 베케트, 오증자 옮김, 『고도를 기다리며』, 민음사 세계문학전집 43, 첨부 OCR 교정본. 제1막 9–93쪽, 제2막 97–163쪽. 배경 및 연구 자료의 출처는 각 항목에 표시하였다.
"""


class Wave13PreSeminarReaderTests(PublicArchiveAndPreSeminarTests):
    def test_canonicalize_semester_merges_variants(self):
        from public_archive_routes import canonicalize_semester, semester_sort_key
        for raw in ("2026-2학기", "2026년 2학기", "2026-2", "2026 2학기"):
            self.assertEqual(canonicalize_semester(raw), ("2026-2", "2026-2학기"))
        self.assertEqual(canonicalize_semester("2026-여름"), ("2026-여름", "2026 여름방학"))
        self.assertEqual(canonicalize_semester("2027-1", "2027년 1학기"), ("2027-1", "2027년 1학기"))
        self.assertEqual(canonicalize_semester("", "", "2025-03-04")[0], "2025-custom")
        order = sorted(["2026-여름", "2026-2", "2026-1", "2026-겨울"], key=semester_sort_key, reverse=True)
        self.assertEqual(order, ["2026-2", "2026-여름", "2026-1", "2026-겨울"])

    def test_colophon_and_rules_are_stripped(self):
        from public_archive_routes import parse_pre_seminar_markdown, strip_editorial_colophon
        cleaned = strip_editorial_colophon(GODOT_MD)
        self.assertNotIn("본문 기준", cleaned)
        self.assertNotIn("---", cleaned)
        self.assertIn("에스트라공과 블라디미르.", cleaned)
        self.assertEqual(strip_editorial_colophon("## A\n본문\n"), "## A\n본문\n")
        parsed = parse_pre_seminar_markdown(GODOT_MD + "\n")
        texts = [run["text"] for sec in parsed["sections"] for item in sec["items"] for run in item.get("runs", [])]
        self.assertFalse(any("OCR" in t or "본문 기준" in t or t.strip() == "---" for t in texts))
        mid = parse_pre_seminar_markdown("## A\n하나\n\n---\n\n둘")
        self.assertEqual([i["runs"][0]["text"] for i in mid["sections"][0]["items"]], ["하나", "둘"])
        self.assertEqual([s["level"] for s in parsed["sections"]], [1, 2, 2, 3, 1])

    def test_outline_hierarchy_for_markdown_and_archive(self):
        from public_archive_routes import build_pre_seminar_outline, parse_pre_seminar_markdown
        outline = build_pre_seminar_outline(parse_pre_seminar_markdown(GODOT_MD)["sections"])
        self.assertEqual([n["heading"] for n in outline], ["요약본", "인물과 관계"])
        summary, people = outline
        self.assertFalse(summary["is_toggle"])
        self.assertEqual([c["heading"] for c in summary["children"]], ["제1막", "제2막"])
        self.assertTrue(all(c["is_toggle"] and not c["default_open"] for c in summary["children"]))
        self.assertEqual(summary["children"][0]["blocks"][1]["type"], "ul")
        self.assertEqual(len(summary["children"][0]["blocks"][1]["items"]), 2)
        self.assertEqual(summary["children"][1]["children"][0]["variant"], "sub")
        self.assertTrue(people["is_toggle"])
        self.assertEqual(people["variant"], "major")
        books = {b["slug"]: b for b in json.loads(PRE_SEMINAR_JSON.read_text(encoding="utf-8"))["books"]}
        klara = build_pre_seminar_outline(books["2026-2-klara-and-the-sun"]["sections"])
        self.assertEqual([n["heading"] for n in klara], ["요약본", "인물과 관계", "작가", "더 깊이 파고 싶다면"])
        self.assertEqual(len(klara[3]["children"]), 5)
        self.assertTrue(klara[2]["is_toggle"])
        devil = build_pre_seminar_outline(books["2026-summer-the-devil-and-the-good-lord"]["sections"])
        self.assertEqual(devil[0]["heading"], "작품을 읽기 전에")
        self.assertTrue(devil[0]["default_open"])

    def test_db_book_merges_into_archive_semester_and_reader_ui(self):
        self.fake.rows["pre_seminar_materials"] = [{
            "id": "godot", "slug": "waiting-for-godot", "title": "고도를 기다리며", "author": "",
            "semester": "2026-2학기", "semester_label": "2026-2학기", "seminar_date": "2026-11-26",
            "edition_note": "", "markdown_body": GODOT_MD, "is_published": True, "created_at": "2026-11-20T00:00:00Z"}]
        self.login("member")
        html = self.client.get("/pre-seminar/waiting-for-godot").get_data(as_text=True)
        self.assertEqual(html.count("2026-2학기 (9권)"), 1)
        self.assertIn("2026 여름방학 (7권)", html)
        self.assertIn("전체 (16권)", html)
        self.assertNotIn("(1권)", html)
        self.assertNotIn("· 2026-11-26</small>", html)
        self.assertIn("2026-2학기 · 2026-11-26</p>", html)
        self.assertNotIn("2026-11-26 · </p>", html)
        self.assertIn('<details class="pre-toggle"', html)
        self.assertIn('id="pre-toggle-all"', html)
        self.assertIn('id="pre-catalog"', html)
        self.assertNotIn("pre-hero", html)
        self.assertNotIn("본문 기준", html)
        self.assertNotIn("<p class=\"pre-p\">---</p>", html)
        self.assertLess(html.index('class="pre-catalog"'), html.index('class="pre-detail"'))
        self.assertIn("다음 도서 →", html)
        self.assertIn("2026-2학기 (9권)", self.client.get("/pre-seminar?semester=2026-2학기").get_data(as_text=True))
        klara = self.client.get("/pre-seminar/2026-2-klara-and-the-sun").get_data(as_text=True)
        self.assertIn('<details class="pre-toggle"', klara)
        self.assertIn("← 이전 도서", klara)

    def test_save_strips_colophon_and_canonicalizes_semester(self):
        self.login("admin")
        self.fake.rows["pre_seminar_materials"] = []
        data = {"csrf_token": "test-csrf", "title": "고도를 기다리며", "semester": "2026-2학기", "semester_label": "",
                "seminar_date": "2026-11-26", "markdown_body": GODOT_MD, "is_published": "on"}
        self.assertEqual(self.client.post("/admin/pre-seminar/save", data=data).status_code, 303)
        row = self.fake.rows["pre_seminar_materials"][0]
        self.assertEqual(row["semester"], "2026-2")
        self.assertEqual(row["semester_label"], "2026-2학기")
        self.assertNotIn("본문 기준", row["markdown_body"])
        self.assertNotIn("---", row["markdown_body"])


if __name__ == "__main__":
    unittest.main()
