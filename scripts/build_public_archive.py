#!/usr/bin/env python3
"""Read-only snapshot builder for the public club archive and member-only pre-seminar materials.

Reads:
  1. Naver Cafe backups on H:\\ (read-only in-memory streaming; never writes to H:\\)
  2. Notion API via C:\\Users\\HOME\\.config\\knu-read\\notion.env.txt (read-only; when available)

Writes (inside this repository):
  - data/public_archive.json
  - data/member_pre_seminar_materials.json
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import sys
import tarfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure pymupdf is importable even if invoked from a venv without it when system Python has it.
try:
    import pymupdf
except ImportError:
    py313_site = Path(r"C:\Users\HOME\AppData\Local\Programs\Python\Python313\Lib\site-packages")
    if py313_site.exists() and str(py313_site) not in sys.path:
        sys.path.append(str(py313_site))
    import pymupdf  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
PUBLIC_ARCHIVE_PATH = DATA_DIR / "public_archive.json"
PRE_SEMINAR_PATH = DATA_DIR / "member_pre_seminar_materials.json"

ARCHIVE1_DIR = Path(r"H:\내 드라이브\책반우 네이버카페 원본 (2026-10-31)")
ARCHIVE2_DIR = Path(r"H:\내 드라이브\책반우 네이버카페 추가 백업 (2026-11-01~2026-11-20)")
NOTION_ENV_PATH = Path(r"C:\Users\HOME\.config\knu-read\notion.env.txt")

NOTION_CURRICULUM_PAGE_ID = "3be901e3-4f3e-8074-b5cd-e763ce3d4a73"
NOTION_PRE_SEMINAR_PAGE_ID = "3a6901e3-4f3e-80dd-a4cd-fcbd9457fee4"

PRIVATE_BOARDS = frozenset({
    "회계장부",
    "총회 회의록",
    "공지사항",
    "신입모집",
    "친목활동",
    "회칙",
    "후기",
    "자유게시판",
    "커리큘럼 책 추천",
    "책크메이트",
})

SEMESTER_META = [
    {"id": "2025-2", "label": "2025-2학기", "period": "2025.09 – 2025.12"},
    {"id": "2026-겨울", "label": "2026 겨울방학", "period": "2025.12 – 2026.02"},
    {"id": "2026-1", "label": "2026-1학기", "period": "2026.03 – 2026.06"},
    {"id": "2026-여름", "label": "2026 여름방학", "period": "2026.07 – 2026.08"},
    {"id": "2026-2", "label": "2026-2학기", "period": "2026.09 – 2026.12"},
]

# Authoritative 44-book catalog across 2025-2 ~ 2026-2, mapped to Naver Cafe article IDs.
# Format: (slug, semester, date, title, author, genre, prompt_aids, log_aids, status_note)
BOOK_CATALOG: list[tuple[str, str, str, str, str, str, list[int], list[int], str]] = [
    # 2025-2학기 (9권)
    ("2025-2-bonjour-tristesse-brahms", "2025-2", "2025-09-15", "브람스를 좋아하세요...", "프랑수아즈 사강", "프랑스 현대소설", [39], [], ""),
    ("2025-2-pavane", "2025-2", "2025-09-22", "죽은 왕녀를 위한 파반느", "박민규", "한국 현대소설", [40], [41], ""),
    ("2025-2-apology", "2025-2", "2025-09-29", "소크라테스의 변명 (플라톤의 네 대화편)", "플라톤", "고대 철학", [52], [54], ""),
    ("2025-2-no-longer-human", "2025-2", "2025-10-13", "인간실격", "다자이 오사무", "일본 현대소설", [70], [64], ""),
    ("2025-2-beneath-the-wheel", "2025-2", "2025-11-03", "수레바퀴 아래서", "헤르만 헤세", "독일 교양소설", [71], [74], ""),
    ("2025-2-the-plague", "2025-2", "2025-11-10", "페스트", "알베르 카뮈", "프랑스 실존주의 소설", [75], [87], ""),
    ("2025-2-shokos-smile", "2025-2", "2025-11-17", "쇼코의 미소", "최은영", "한국 단편소설", [88], [89], ""),
    ("2025-2-regarding-the-pain-of-others", "2025-2", "2025-11-24", "타인의 고통", "수전 손택", "비평 · 인문 에세이", [99], [103], ""),
    ("2025-2-katharina-blum", "2025-2", "2025-12-01", "카타리나 블룸의 잃어버린 명예", "하인리히 뵐", "독일 현대소설", [110], [112], ""),

    # 2026 겨울방학 (8권)
    ("2026-winter-metamorphosis", "2026-겨울", "2025-12-29", "변신 외 6개 단편", "프란츠 카프카", "독일어권 단편소설", [121], [120], ""),
    ("2026-winter-mans-search-for-meaning", "2026-겨울", "2026-01-05", "죽음의 수용소에서", "빅터 프랭클", "심리학 · 에세이", [125], [131], ""),
    ("2026-winter-satantango", "2026-겨울", "2026-01-12", "사탄탱고", "크러스너호르커이 라슬로", "헝가리 현대소설", [133], [134], ""),
    ("2026-winter-wings", "2026-겨울", "2026-01-19", "이상 단편선 · 날개", "이상", "한국 근대 단편소설", [141], [147], ""),
    ("2026-winter-wonmi-dong", "2026-겨울", "2026-01-26", "원미동 사람들", "양귀자", "한국 연작소설", [149], [155], ""),
    ("2026-winter-all-life-is-problem-solving", "2026-겨울", "2026-02-02", "삶은 문제해결의 연속이다", "칼 포퍼", "과학철학 · 사회사상", [157], [158], ""),
    ("2026-winter-on-love", "2026-겨울", "2026-02-09", "왜 나는 너를 사랑하는가", "알랭 드 보통", "영국 현대소설 · 에세이", [160], [172], ""),
    ("2026-winter-goethe-said-everything", "2026-겨울", "2026-02-23", "괴테는 모든 것을 말했다", "스즈키 유이", "일본 현대소설", [179], [184], ""),

    # 2026-1학기 (10권)
    ("2026-1-uncle-vanya", "2026-1", "2026-03-23", "체호프 희곡선 (바냐 아저씨)", "안톤 체호프", "러시아 희곡", [189], [191], ""),
    ("2026-1-werther", "2026-1", "2026-03-30", "젊은 베르테르의 슬픔", "요한 볼프강 폰 괴테", "독일 서간체 소설", [215], [197, 205], ""),
    ("2026-1-rainy-season-together", "2026-1", "2026-04-06", "우리가 함께 장마를 볼 수도 있겠습니다", "박준", "한국 현대시", [216], [207, 213], ""),
    ("2026-1-great-gatsby", "2026-1", "2026-04-27", "위대한 개츠비", "F. 스콧 피츠제럴드", "미국 현대소설", [217], [218, 224], ""),
    ("2026-1-to-have-or-to-be", "2026-1", "2026-05-04", "소유냐 존재냐", "에리히 프롬", "사회철학 · 심리학", [], [230, 227], ""),
    ("2026-1-if-we-cannot-move-at-the-speed-of-light", "2026-1", "2026-05-11", "우리가 빛의 속도로 갈 수 없다면", "김초엽", "한국 SF 단편소설", [], [243, 245], ""),
    ("2026-1-to-live", "2026-1", "2026-05-18", "인생", "위화", "중국 현대소설", [], [246, 255], ""),
    ("2026-1-siddhartha", "2026-1", "2026-05-25", "싯다르타", "헤르만 헤세", "독일 구도소설", [], [252, 260], ""),
    ("2026-1-we-do-not-part", "2026-1", "2026-06-01", "작별하지 않는다", "한강", "한국 현대소설 (오픈세미나)", [], [263], ""),
    ("2026-1-what-does-it-all-mean", "2026-1", "2026-06-08", "이 모든 것의 철학적 의미는", "토머스 네이글", "입문 철학", [], [265, 264], ""),

    # 2026 여름방학 (7권)
    ("2026-summer-rashomon", "2026-여름", "2026-07-16", "라쇼몽", "아쿠타가와 류노스케", "일본 근대 단편소설", [], [274], ""),
    ("2026-summer-the-devil-and-the-good-lord", "2026-여름", "2026-07-23", "악마와 선한 신", "장 폴 사르트르", "프랑스 실존주의 희곡", [], [275], ""),
    ("2026-summer-true-story-of-ah-q", "2026-여름", "2026-07-30", "아Q 정전", "루쉰", "중국 근대소설", [], [287], ""),
    ("2026-summer-status-anxiety", "2026-여름", "2026-08-09", "불안", "알랭 드 보통", "인문 에세이", [], [302], ""),
    ("2026-summer-outside-is-summer", "2026-여름", "2026-08-16", "바깥은 여름", "김애란", "한국 단편소설", [], [311], ""),
    ("2026-summer-agony-of-eros", "2026-여름", "2026-08-23", "에로스의 종말", "한병철 · 알랭 바디우", "현대 철학", [], [313], ""),
    ("2026-summer-summer", "2026-여름", "2026-08-30", "여름", "이디스 워튼", "미국 현대소설 (오픈세미나)", [], [320], ""),

    # 2026-2학기 (10권)
    ("2026-2-drifting-island", "2026-2", "2026-09-17", "표류도", "박경리", "한국 현대소설", [], [345], ""),
    ("2026-2-kokoro", "2026-2", "2026-09-23", "마음", "나쓰메 소세키", "일본 근대소설", [], [343], ""),
    ("2026-2-i-wish-for-what-is-forbidden-to-me", "2026-2", "2026-10-01", "나는 소망한다 내게 금지된 것을", "양귀자", "한국 현대소설", [], [362], ""),
    ("2026-2-left-behind-summer", "2026-2", "2026-10-08", "두고 온 여름", "성해나", "한국 현대소설", [], [382], ""),
    ("2026-2-demian", "2026-2", "2026-10-29", "데미안", "헤르만 헤세", "독일 성장소설", [], [384], "이미지 기록 보관 중"),
    ("2026-2-serotonin", "2026-2", "2026-11-05", "세로토닌", "미셸 우엘벡", "프랑스 현대소설", [], [413], ""),
    ("2026-2-the-moon-and-sixpence", "2026-2", "2026-11-12", "달과 6펜스", "윌리엄 서머셋 몸", "영국 현대소설", [], [409], ""),
    ("2026-2-klara-and-the-sun", "2026-2", "2026-11-19", "클라라와 태양", "가즈오 이시구로", "영국 SF 현대소설", [], [], "세미나 기록 준비 중"),
    ("2026-2-waiting-for-godot", "2026-2", "2026-11-26", "고도를 기다리며", "사뮈엘 베케트", "부조리극 희곡", [], [], "세미나 진행 예정"),
    ("2026-2-white-nights", "2026-2", "2026-12-03", "백야", "표도르 도스토옙스키", "러시아 고전소설", [], [], "세미나 진행 예정"),
]

# Pre-seminar Notion page title -> catalog slug mapping (15 curated books: 2026-여름 7 + 2026-2 8)
PRE_SEMINAR_TITLE_TO_SLUG = {
    "라쇼몬": "2026-summer-rashomon",
    "악마와 선한 신": "2026-summer-the-devil-and-the-good-lord",
    "아Q정전": "2026-summer-true-story-of-ah-q",
    "불안": "2026-summer-status-anxiety",
    "바깥은 여름": "2026-summer-outside-is-summer",
    "에로스의 종말": "2026-summer-agony-of-eros",
    "여름": "2026-summer-summer",
    "표류도": "2026-2-drifting-island",
    "마음": "2026-2-kokoro",
    "나는 소망한다 내게 금지된 것을": "2026-2-i-wish-for-what-is-forbidden-to-me",
    "두고 온 여름": "2026-2-left-behind-summer",
    "데미안": "2026-2-demian",
    "세로토닌": "2026-2-serotonin",
    "달과 6펜스": "2026-2-the-moon-and-sixpence",
    "클라라와 태양": "2026-2-klara-and-the-sun",
}

# Literary authors/critics/terms that must NEVER be masked as club member names.
LITERARY_STOPWORDS = frozenset({
    "발제자", "사회자", "책반우", "호반우", "학술지원", "학술지원부", "기획부", "홍보부", "총무부",
    "서기", "부회장", "회장", "독어교육", "컴퓨터", "여름", "마음", "인생", "페스트", "라쇼몬", "데미안",
    "표류도", "세로토닌", "백야", "소유냐", "존재냐", "이상", "박민규", "최은영", "한강", "김초엽",
    "양귀자", "박경리", "성해나", "김애란", "박준", "플라톤", "괴테", "카프카", "헤세", "헤르만",
    "카뮈", "위화", "루쉰", "체호프", "사르트르", "도스토옙스키", "스즈키", "네이글", "아쿠타가와",
    "이시구로", "베케트", "피츠제럴드", "사강", "다자이", "오사무", "신경숙", "김동인", "강혜선",
    "한병철", "알랭", "바디우", "프롬", "포퍼", "이디스", "워튼", "우엘벡", "서머셋", "나쓰메",
    "소세키", "학과", "학부", "전공", "학번", "기수", "참여자", "질문", "답변", "작품", "소설",
    "이야기", "주인공", "작가", "인간", "사랑", "행복", "고통", "자유", "선악", "시간", "세계",
    "기억", "현실", "진실", "죽음", "태양", "바람", "바다", "하늘", "사람", "우리", "자신",
})

# Common 2-char names only masked in clear person-reference contexts.
SHORT_COMMON_EXCLUDE = frozenset({"이상", "박준", "위화", "루쉰", "괴테", "카뮈", "헤세", "사강", "여름", "마음", "인생"})


class MultiPartStream(io.RawIOBase):
    """Read-only sequential stream over split .tar.gz.partXX files."""

    def __init__(self, paths: list[Path]):
        self.paths = sorted(paths)
        self.idx = 0
        self.fp = open(self.paths[0], "rb") if self.paths else None

    def readable(self) -> bool:
        return True

    def readinto(self, b: bytearray | memoryview) -> int:
        if self.fp is None:
            return 0
        total = 0
        mv = memoryview(b)
        while total < len(b):
            n = self.fp.readinto(mv[total:])
            if n:
                total += n
                break
            self.fp.close()
            self.idx += 1
            if self.idx >= len(self.paths):
                self.fp = None
                break
            self.fp = open(self.paths[self.idx], "rb")
        return total

    def close(self) -> None:
        if self.fp is not None:
            self.fp.close()
            self.fp = None
        super().close()


def extract_page_clean(page: pymupdf.Page) -> str:
    """Extract PDF page text in accurate visual reading order using y-band span clustering."""
    d = page.get_text("dict")
    spans: list[tuple[float, float, float, str]] = []
    for block in d.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for sp in line.get("spans", []):
                txt = sp.get("text", "")
                if not txt.strip():
                    continue
                x0, y0, x1, y1 = sp["bbox"]
                yc = (y0 + y1) / 2.0
                spans.append((yc, x0, x1, txt))
    if not spans:
        return ""
    spans.sort(key=lambda s: (s[0], s[1]))
    lines: list[list[tuple[float, float, float, str]]] = []
    cur = [spans[0]]
    cur_y = spans[0][0]
    for sp in spans[1:]:
        if abs(sp[0] - cur_y) <= 5.5:
            cur.append(sp)
            cur_y = sum(x[0] for x in cur) / len(cur)
        else:
            lines.append(cur)
            cur = [sp]
            cur_y = sp[0]
    lines.append(cur)

    out_lines: list[str] = []
    no_space_before = (" ", ".", ",", "?", "!", ":", ";", ")", "]", "”", "’", "」", "』", "…")
    no_space_after = (" ", "(", "[", "“", "‘", "「", "『")
    for ln in lines:
        ln.sort(key=lambda s: s[1])
        buf: list[str] = []
        prev_x1: float | None = None
        for _, x0, x1, txt in ln:
            if (
                prev_x1 is not None
                and (x0 - prev_x1) > 2.5
                and not txt.startswith(no_space_before)
                and (not buf or not buf[-1].endswith(no_space_after))
            ):
                buf.append(" ")
            buf.append(txt)
            prev_x1 = x1
        cleaned = re.sub(r"[ \t\u00a0]+", " ", "".join(buf)).strip()
        if cleaned:
            out_lines.append(cleaned)
    return "\n".join(out_lines)


def read_pdf_pages(raw_bytes: bytes) -> list[str]:
    doc = pymupdf.open(stream=raw_bytes, filetype="pdf")
    return [extract_page_clean(page) for page in doc]


# Honorifics / roles / placeholders that are safe to keep with '님' in public discussion logs.
HONORIFIC_NIM_ALLOWLIST = frozenset({
    "선생", "작가", "교수", "하나", "하느", "부모", "어머", "아버", "할머", "할아", "조부모",
    "오라버", "누", "형", "도련", "사모", "아드", "따", "어르", "주인", "임금", "여왕",
    "신부", "목사", "스", "큰스", "부처", "보살", "손", "사장", "회장", "부회장", "회원",
    "선배", "후배", "대표", "팀장", "실장", "원장", "총장", "학장", "부원", "의사", "간호사",
    "기사", "라이더", "판사", "검사", "변호사", "감독", "기자", "시인", "철학자", "소설가",
    "화자", "주인공", "인물", "독자", "역자", "번역가", "편집자", "평론가", "타인",
    "선조", "선대", "장군", "대장", "사제", "수녀", "고승", "대사", "전하", "폐하",
    "마마", "나으", "대감", "영감", "참여자", "발제자", "사회자", "서기", "다른참여자",
    "대한민국", "조국", "어린이",
})

HONORIFIC_NIM_SUFFIXES = (
    "선생", "작가", "교수", "회장", "부회장", "선배", "후배", "참여자", "사회자", "발제자", "서기",
    "부모", "어머", "아버", "할머", "할아", "스", "사장", "의사", "기사", "라이더",
    "대표", "감독", "기자", "시인", "주인", "임금", "신부", "목사",
)

LITERARY_NIM_ALLOWLIST = frozenset({
    "포퍼", "예수", "부처", "오라버", "경하", "인선", "나까무라", "소크라테스", "베르테르",
})

_ROLE_WORDS_NOT_NAMES = frozenset({
    "학과", "학부", "전공", "학년", "학기", "학번", "기수", "오픈", "세미나", "발제문",
    "발제자", "사회자", "서기", "부회장", "회장", "총무", "기획부", "홍보부", "학술지원",
    "학술지원부", "부원", "임원", "회원", "자율학부", "인문학부", "동아리", "호반우", "책반우",
})


def _add_candidate_name(cand: str, sink: set[str]) -> None:
    if not cand or len(cand) < 2 or len(cand) > 4:
        return
    if cand in LITERARY_STOPWORDS or cand in _ROLE_WORDS_NOT_NAMES:
        return
    if cand.endswith(("학과", "학부", "전공", "기수", "학년", "학기")):
        return
    sink.add(cand)


def _collect_names_from_text(text: str, sink: set[str], is_cover: bool = False) -> None:
    # Self-intro / role lines with department/admission-year
    for m in re.finditer(
        r"(?:학과|학부|전공|과)\s*(?:\d+\s+)?(?:\(\s*(?:1[89]|2[0-6])\s*\)|(?:1[89]|2[0-6])\s*(?:학번)?)\s*([가-힣]{2,4})(?=\s|$|[.,:：()])",
        text,
    ):
        _add_candidate_name(m.group(1), sink)
    for m in re.finditer(
        r"\b(?:1[89]|2[0-6])\s*학번\s*([가-힣]{2,4})(?=\s|$|[.,:：()이과])",
        text,
    ):
        _add_candidate_name(m.group(1), sink)
    for m in re.finditer(
        r"(?:발제[자지]|사회자|서기)\s*[:：]\s*(?:(?:[가-힣·]+(?:학과|학부|전공|과)|부?회장|총무|학술지원부?원?)\s+)?(?:(?:\d+\s*기|\d{2}\s*(?:학번)?)\s+)?([가-힣]{2,4})(?=\s|$|[.,:：()])",
        text,
    ):
        _add_candidate_name(m.group(1), sink)
    if is_cover:
        # Cover-page role rows: "이름 : 24", "<과> 24 이름", "24 이름", "사회자 : 부회장 이름", etc.
        for m in re.finditer(r"([가-힣]{2,4})\s*[:：]\s*(?:1[89]|2[0-6])\b", text):
            _add_candidate_name(m.group(1), sink)
        for m in re.finditer(
            r"(?:^|\s)(?:1[89]|2[0-6])\s+([가-힣]{2,4})(?=\s|$|[.,:：()])",
            text,
            re.M,
        ):
            _add_candidate_name(m.group(1), sink)
        for m in re.finditer(
            r"(?:부?회장|총무|학술지원부?원?|서기)\s+([가-힣]{2,4})(?=\s|$|[.,:：()])",
            text,
        ):
            _add_candidate_name(m.group(1), sink)


def load_backup_pdfs() -> tuple[dict[tuple[int, int], list[list[str]]], set[str], dict[tuple[int, int], set[str]]]:
    """Stream both Naver Cafe backups in memory.

    Returns:
      - pdf_pages_by_article: {(menuid, articleid): [page_texts_list, ...]} for menuid in (4, 5)
      - dynamic_member_names: set of real member names collected solely for anonymization
      - article_member_names: {(menuid, articleid): set of member names found in that article}
    """
    pdf_pages: dict[tuple[int, int], list[list[str]]] = {}
    member_names: set[str] = set()
    article_member_names: dict[tuple[int, int], set[str]] = {}

    def handle_member_name_from_meta(board: str, title: str, author: str) -> None:
        m1 = re.search(r"(?:\d+\s*기\s*)?([가-힣]{2,4})$", (author or "").strip())
        if m1 and m1.group(1) not in LITERARY_STOPWORDS:
            _add_candidate_name(m1.group(1), member_names)
        m2 = re.search(r"(?:학과|학부|전공|과)\s*\d{2}학번\s*([가-힣]{2,4})", title or "")
        if m2 and m2.group(1) not in LITERARY_STOPWORDS:
            _add_candidate_name(m2.group(1), member_names)

    # 1. Archive 1 (split tar.gz parts)
    parts = sorted(ARCHIVE1_DIR.glob("naver-cafe-archive-20261031.tar.gz.part*"))
    if parts:
        stream = MultiPartStream(parts)
        with tarfile.open(fileobj=io.BufferedReader(stream, buffer_size=1024 * 1024), mode="r|gz") as tf:
            for m in tf:
                if not m.isfile():
                    continue
                if m.name.endswith("index.csv"):
                    raw_csv = tf.extractfile(m).read().decode("utf-8-sig", errors="replace")
                    for row in csv.DictReader(io.StringIO(raw_csv)):
                        handle_member_name_from_meta(
                            row.get("board", ""),
                            row.get("title", ""),
                            row.get("author", ""),
                        )
                    continue
                if m.name.endswith(".pdf") and not m.name.endswith("page.pdf"):
                    pp = m.name.split("/")
                    # raw/<menuid>/<articleid>/<filename>.pdf
                    if len(pp) >= 5 and pp[2] in ("4", "5") and pp[3].isdigit():
                        mid, aid = int(pp[2]), int(pp[3])
                        raw_pdf = tf.extractfile(m).read()
                        pages = read_pdf_pages(raw_pdf)
                        if pages:
                            art_names = article_member_names.setdefault((mid, aid), set())
                            _collect_names_from_text(pages[0], art_names, is_cover=True)
                            for pg in pages[1:]:
                                _collect_names_from_text(pg, art_names, is_cover=False)
                            member_names.update(art_names)
                            pdf_pages.setdefault((mid, aid), []).append(pages)

    # 2. Archive 2 (single tar.gz)
    idx2_path = ARCHIVE2_DIR / "index.json"
    if idx2_path.exists():
        idx2 = json.loads(idx2_path.read_text(encoding="utf-8"))
        for art in idx2.get("articles", []):
            handle_member_name_from_meta(
                art.get("board", ""),
                art.get("title", ""),
                art.get("author", ""),
            )
    tar2_path = ARCHIVE2_DIR / "naver-cafe-archive-20261101-20261120.tar.gz"
    if tar2_path.exists():
        with tarfile.open(tar2_path, mode="r:gz") as tf:
            for m in tf:
                if not m.isfile():
                    continue
                if m.name.endswith(".pdf") and not m.name.endswith("page.pdf"):
                    pp = m.name.split("/")
                    if len(pp) >= 5 and pp[2] in ("4", "5") and pp[3].isdigit():
                        mid, aid = int(pp[2]), int(pp[3])
                        raw_pdf = tf.extractfile(m).read()
                        pages = read_pdf_pages(raw_pdf)
                        if pages:
                            art_names = article_member_names.setdefault((mid, aid), set())
                            _collect_names_from_text(pages[0], art_names, is_cover=True)
                            for pg in pages[1:]:
                                _collect_names_from_text(pg, art_names, is_cover=False)
                            member_names.update(art_names)
                            pdf_pages.setdefault((mid, aid), []).append(pages)

    member_names -= LITERARY_STOPWORDS
    return pdf_pages, member_names, article_member_names


_NIM_SUFFIX_PARTICLES = (
    r"(?:께서(?:는|도|만)?|에서(?:는|도|만)?|부터(?:는|도|만)?|까지(?:는|도|만)?|"
    r"처럼(?:은|도|만)?|보다(?:는|도|만)?|한테(?:서|는|도|만)?|에게(?:서|는|도|만)?|"
    r"이랑|이라(?:고|서|도|는|면)?|이고|이다|이시|이야|이나|하고|과도|과는|와도|와는|"
    r"들(?:의|이|을|은|과|도|한테|에게|이랑)?|"
    r"의|이|가|은|는|을|를|도|만|께|과|와|랑|야|고|시|라)(?=$|[^가-힣])"
)
_NIM_BOUNDARY = rf"(?=$|[^가-힣]|{_NIM_SUFFIX_PARTICLES})"


@dataclass
class TextAnonymizer:
    """Strict privacy-preserving sanitizer & anonymizer for public archive text."""

    member_names: set[str]

    def __post_init__(self) -> None:
        self._three_plus_names = sorted(
            (n for n in self.member_names if len(n) >= 3 and n not in LITERARY_STOPWORDS),
            key=len,
            reverse=True,
        )
        self._two_char_names = sorted(
            (n for n in self.member_names if len(n) == 2 and n not in LITERARY_STOPWORDS and n not in SHORT_COMMON_EXCLUDE),
            key=len,
            reverse=True,
        )
        # Collect 2-char given names derived from 3+ char member full names for inline mention scrubbing.
        self._given_names: set[str] = {
            n[1:]
            for n in self.member_names
            if len(n) >= 3
            and n not in LITERARY_STOPWORDS
            and n[1:] not in HONORIFIC_NIM_ALLOWLIST
            and n[1:] not in LITERARY_NIM_ALLOWLIST
        }
        self._all_member_or_given = set(self._three_plus_names) | set(self._two_char_names) | self._given_names
        # Keep literary author names safe if any member shares the same name (e.g. 김연수/김나영 in literary context).
        self._ambiguous_full_names = frozenset({"김연수", "김나영"})

    def anonymize(self, text: str, book_name_to_anon: dict[str, str] | None = None) -> str:
        if not text:
            return ""
        s = text
        name_map = book_name_to_anon or {}

        # 1. Strip contact / ID / financial PII immediately
        s = re.sub(r"(?<!\d)01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}(?!\d)", "[연락처 마스킹]", s)
        s = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[이메일 마스킹]", s)
        s = re.sub(r"\b20[12]\d{6,7}\b", "[학번 마스킹]", s)
        s = re.sub(
            r"(?:국민|신한|우리|하나|농협|기업|카카오뱅크|토스뱅크|새마을|우체국|대구|아이엠|iM|SC제일|씨티|수협|신협|부산|경남|광주|전북|제주)\s*[:\-]?\s*\d{2,6}[-\s]?\d{2,6}[-\s]?\d{2,7}(?:[-\s]?\d{1,4})?",
            "[계좌 마스킹]",
            s,
        )
        s = re.sub(r"\b\d{3,4}-\d{2,4}-\d{4,6}\b", "[번호 마스킹]", s)

        # 2. Strip self-introduction lines / clauses mentioning department + admission year + name
        s = re.sub(
            r"(?:안녕하세요[.,]?\s*)?(?:저는\s*)?(?:[가-힣·]{2,18}(?:학과|학부|전공|과)\s*)?(?:\(\s*\d{2}\s*\)|\d{2}\s*(?:학번)?)\s*[가-힣*○0O]{2,4}?(?:입니다|이고요|이라고\s*합니다|이에요|예요)(?=$|\s|[.,])",
            "참여자",
            s,
        )
        s = re.sub(
            r"(?:안녕하세요[.,]?\s*)?(?:저는\s*)?(?:[가-힣·]{2,18}(?:학과|학부|전공|과)\s*)?(?:\(\s*\d{2}\s*\)|\d{2}\s*(?:학번)?)\s*[가-힣*○0O]{2,4}[.,]?(?=\s|$)",
            "참여자",
            s,
        )
        s = re.sub(
            r"(?:안녕하세요[.,]?\s*)?(?:저는\s*)?(?:첨단기술\s*융합\s*대학\s*)?자율학부\s*(?:소속\s*)?\d{2}\s*(?:학번)?\s*[가-힣*○0O]{2,4}?(?:입니다|이고요|이라고\s*합니다)?(?=$|\s|[.,])[.,]?",
            "참여자",
            s,
        )
        s = re.sub(
            r"(?:[가-힣·]{2,18}(?:학과|학부|전공|과))\s*\(\s*\d{2}\s*\)\s*[가-힣*○0O]{2,4}?(?:입니다|이고요)?(?=$|\s|[.,])[.,]?",
            "참여자",
            s,
        )
        s = re.sub(
            r"\d{2}\s*학번\s*(?:[가-힣·]{2,18}(?:학과|학부|전공|과)\s*)?[가-힣*○0O]{2,4}?(?:입니다|이고요|이라고\s*합니다)?(?=$|\s|[.,])[.,]?",
            "참여자",
            s,
        )

        # 3. Strip department + student year combos (even without name)
        s = re.sub(
            r"[가-힣·]{2,18}(?:학과|학부|전공)\s*(?:\(\s*\d{2}\s*\)|\d{2}\s*(?:학번|학과)?)",
            "",
            s,
        )
        s = re.sub(r"\b\d{2}\s*학번\b", "", s)

        # 4. Mask cohort + masked/unmasked name patterns (e.g., 6기 정*용, 노*림(8기), 박0서, 김*준님)
        s = re.sub(
            r"\d+\s*기\s*[가-힣*○0O]{1,4}\s*[가-힣*○0O]{1,3}(?:\s*\(\s*이하\s*[가-힣]\s*\))?",
            "참여자",
            s,
        )
        s = re.sub(
            r"[가-힣*○0O]{1,3}\s*[가-힣*○0O]{1,3}\s*\(\s*\d+\s*기\s*\)",
            "참여자",
            s,
        )
        s = re.sub(r"[가-힣]\s*[*○0]\s*[가-힣]\s*(?:님|형|누나|오빠|언니|씨)?", "참여자", s)
        s = re.sub(r"\(\s*이하\s*[가-힣]\s*\)", "", s)

        # 5. Mask socializer/secretary notes
        s = re.sub(r"사회자\s*(?:\([^)]*\)|[:：]\s*[^\n]+)?", "사회자", s)
        s = re.sub(r"학술지원부[^\n]*서기[^\n]*", "", s)

        # Normalize spurious PDF span spaces inside common honorifics & known 2-char names before 님/씨
        s = re.sub(r"(?<![가-힣])(선)\s+(생님|배님|조님)", r"\1\2", s)
        s = re.sub(r"(?<![가-힣])(사회|발제|참여)\s+(자님)", r"\1\2", s)
        s = re.sub(r"(?<![가-힣])(부\s*회|부회|회|총무|서기|부원)\s+(장님|님)", lambda m: re.sub(r"\s+", "", m.group(1)) + m.group(2), s)
        s = re.sub(r"(?<![가-힣])(스|손)\s+(님)", r"\1\2", s)
        s = re.sub(r"(?<![가-힣])(아버|어머|할머|할아|부모|부처|예수)\s+(님)", r"\1\2", s)
        s = re.sub(
            rf"(?<![가-힣])([가-힣])\s+([가-힣])(?=\s*(?:님|씨){_NIM_BOUNDARY})",
            lambda m: (m.group(1) + m.group(2)) if (m.group(1) + m.group(2)) in self._all_member_or_given or (m.group(1) + m.group(2)) in name_map else m.group(0),
            s,
        )

        # 5.5 Replace mapped speaker names & inline "<name>님" / "<name>씨" references
        def _scrub_nim(m: re.Match[str]) -> str:
            tok = m.group(1)
            if tok == "다른" or tok == "다른참여자":
                return m.group(0)
            if tok.startswith("참여자") and tok != "참여자":
                rest_role = tok[3:]
                if rest_role in HONORIFIC_NIM_ALLOWLIST or rest_role.endswith(HONORIFIC_NIM_SUFFIXES):
                    return f"참여자 {rest_role}님"
            if tok in HONORIFIC_NIM_ALLOWLIST or tok.endswith(HONORIFIC_NIM_SUFFIXES):
                return m.group(0)
            if tok in name_map:
                return f"{name_map[tok]}님"
            if len(tok) == 4 and tok[1:] in name_map:
                return f"{tok[0]}{name_map[tok[1:]]}님"
            if tok in LITERARY_NIM_ALLOWLIST:
                return m.group(0)
            if tok in self._all_member_or_given or len(tok) in (2, 3):
                return "다른 참여자님"
            return m.group(0)

        def _scrub_ssi(m: re.Match[str]) -> str:
            tok = m.group(1)
            if tok in name_map:
                return name_map[tok]
            if tok in self._all_member_or_given:
                return "다른 참여자"
            return m.group(0)

        # First replace known speaker full names (boundary-guarded so compound words stay intact)
        _left_bound = r"(?:(?<=^)|(?<![가-힣])|(?<=발제자)|(?<=사회자)|(?<=서기))"
        for full_name in sorted((k for k in name_map if len(k) >= 3), key=len, reverse=True):
            if full_name not in s:
                continue
            anon_label = name_map[full_name]
            if full_name in self._ambiguous_full_names:
                s = re.sub(
                    rf"(?:(?<=\s)|^){re.escape(full_name)}(?=\s*(?:님|씨|형|누나|오빠|언니|이|가|은|는|의|[:：(]))",
                    anon_label,
                    s,
                )
            else:
                s = re.sub(rf"{_left_bound}{re.escape(full_name)}\s*님{_NIM_BOUNDARY}", f"{anon_label}님", s)
                s = re.sub(rf"{_left_bound}{re.escape(full_name)}\s*(?:씨|형|누나|오빠|언니){_NIM_BOUNDARY}", anon_label, s)
                s = re.sub(rf"{_left_bound}{re.escape(full_name)}", anon_label, s)

        # Normalize "참여자 A 님" / "참여자 님" / "<name> 선배님" spacing before general 님 scan
        s = re.sub(r"참여자\s*(선배|후배|선생|회장|부회장)", r"참여자 \1", s)
        s = re.sub(rf"([가-힣]{{2,5}})\s*님{_NIM_BOUNDARY}", _scrub_nim, s)
        s = re.sub(rf"([가-힣]{{2,4}})\s*씨{_NIM_BOUNDARY}", _scrub_ssi, s)

        # 6. Mask remaining dynamically collected 3+ char member names (preserve 님 + particles cleanly)
        for name in self._three_plus_names:
            if name not in s:
                continue
            replacement = name_map.get(name, "참여자")
            nim_replacement = "다른 참여자님" if replacement == "참여자" else f"{replacement}님"
            if name in self._ambiguous_full_names:
                s = re.sub(
                    rf"(?:(?<=\s)|^){re.escape(name)}(?=\s*(?:님|씨|형|누나|오빠|언니|이|가|은|는|의|[:：(]))",
                    replacement,
                    s,
                )
            else:
                s = re.sub(rf"{_left_bound}{re.escape(name)}\s*님{_NIM_BOUNDARY}", nim_replacement, s)
                s = re.sub(rf"{_left_bound}{re.escape(name)}\s*(?:씨|형|누나|오빠|언니){_NIM_BOUNDARY}", replacement, s)
                s = re.sub(rf"{_left_bound}{re.escape(name)}", replacement, s)

        # 7. Mask remaining 2-char member names in person-reference contexts
        for name in self._two_char_names:
            if name not in s:
                continue
            replacement = name_map.get(name, "참여자")
            nim_replacement = "다른 참여자님" if replacement == "참여자" else f"{replacement}님"
            s = re.sub(
                rf"(?:(?<=^)|(?<=[\s(\[])){re.escape(name)}\s*님{_NIM_BOUNDARY}",
                nim_replacement,
                s,
            )
            s = re.sub(
                rf"(?:(?<=^)|(?<=[\s(\[])){re.escape(name)}(?=\s*(?:씨|형|누나|오빠|언니|[:：]))",
                replacement,
                s,
            )

        # 8. Clean redundant repeated "참여자 참여자" / extra whitespace (preserve "참여자 A님" & "다른 참여자님")
        s = re.sub(r"참여자\s*(선배|후배|선생|회장|부회장)", r"참여자 \1", s)
        s = re.sub(r"(?<!다른 )(?:참여자\s+){2,}(?![A-Z]\b)", "참여자 ", s)
        s = re.sub(r"(?<!다른 )(?<![A-Z] )참여자\s*(?:님|씨)", "참여자", s)
        s = re.sub(r"[ \t]+", " ", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()


def _is_cover_page(page_text: str) -> bool:
    head = page_text[:400]
    if "책 먹는 호반우" in head and ("발제자" in head or "사회자" in head or re.search(r"202[56]\.\d{2}\.\d{2}", head)):
        return True
    if re.search(r"202[56]\.\d{2}\.\d{2}", head) and len(re.findall(r"(?:학과|학부|전공|\b2[0-6]\b)", head)) >= 2:
        return True
    return False


_PROMPT_HEADER_RE = re.compile(
    r"^\s*(?:발제[자지]\s*[:：]?.*|"
    r"[가-힣·]{2,18}(?:학과|학부|전공)\s*(?:\(\s*\d{2}\s*\)|\d{2}\s*(?:학번)?)\s*[가-힣]{2,4}\s*|"
    r"\d{2}\s*[가-힣]{2,4})\s*$"
)

_SPEAKER_TURN_RE = re.compile(
    r"^\s*(?:"
    r"(?:\d+\s*기\s+[가-힣*○0O]{1,4}\s*[가-힣*○0O]{0,3}|[가-힣*○0O]{1,4}\s*[가-힣*○0O]{0,3}\s*\(\s*\d+\s*기\s*\))\s*[:：]?\s*(.*)|"
    r"[가-힣]\s*[*○0]\s*[가-힣]\s*[:：]?\s*(.*)|"
    r"(?:[가-힣·]{2,18}(?:학과|학부|전공)\s*)?(?:\(\s*\d{2}\s*\)|\d{2}\s*(?:학번)?)\s*(?:[가-힣·]{2,18}(?:학과|학부|전공)\s*)?[가-힣]{2,4}\s*[:：]?\s*(.*)|"
    r"([가-힣]{1})\s*[:：]\s+(.*)"
    r")$"
)

_QUESTION_START_RE = re.compile(r"^\s*(\d+(?:[-–.]\d+)?)\s*[.)]\s*(.+)$")


def _clean_line_noise(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    if re.fullmatch(r"[-–—\s]*\d{1,3}[-–—\s]*", s):
        return False
    if s in {"", "", "•", "·"}:
        return False
    if re.fullmatch(r"경북대학교\s*(?:중앙\s*)?독서동아리\s*책\s*먹는\s*호반우", s):
        return False
    return True


def _extract_speaker_key(line: str, known_names: set[str], single_char_mode: bool) -> tuple[str | None, str]:
    s = line.strip()
    # Pattern A: "6 기 정*용 : ..." or "노*림(8 기) : ..." or "7 기 김*수" (whole line)
    m = re.match(
        r"^(?:(\d+\s*기)\s+([가-힣*○0O]{1,4}(?:\s*[가-힣*○0O]{1,2})?)|([가-힣*○0O]{1,4}(?:\s*[가-힣*○0O]{1,2})?)\s*\(\s*(\d+\s*기)\s*\))\s*(?:[:：]\s*(.*))?$",
        s,
    )
    if m:
        name_part = re.sub(r"\s+", "", m.group(2) or m.group(3) or "")
        rest = (m.group(5) or "").strip()
        if len(name_part) >= 2 and ("*" in name_part or "○" in name_part or "0" in name_part or name_part in known_names or m.group(1) or m.group(4)):
            # Verify rest isn't just continuing sentence when there's no colon and line has many words
            if ":" in s or "：" in s or rest == "" or rest.startswith(("안녕하세요", "저는", "전 ", "제가", "저희", "일단", "이번", "책")):
                return name_part, rest

    # Pattern B: "박0 서" / "윤0 웅" standalone speaker line (#343 마음)
    m = re.match(r"^([가-힣]\s*[*○0]\s*[가-힣])\s*(?:[:：]\s*(.*))?$", s)
    if m:
        return re.sub(r"\s+", "", m.group(1)), (m.group(2) or "").strip()

    # Pattern C: "경영학부 22 학번 박성원" / "의학과 25 김도윤" standalone header (#413 세로토닌)
    m = re.match(
        r"^(?:[가-힣·]{2,18}(?:학과|학부|전공|과)\s*)?(?:\d{2}\s*(?:학번)?)\s*([가-힣]{2,4})\s*(?:[:：]\s*(.*))?$",
        s,
    )
    if m and m.group(1) in known_names:
        return m.group(1), (m.group(2) or "").strip()

    # Pattern D: Single-char surname speaker in group discussion ("박 : ...", "정 : ...", #230)
    if single_char_mode:
        m = re.match(r"^([가-힣])\s*[:：]\s*(.+)$", s)
        if m and m.group(1) not in {"참", "예", "책", "그", "이", "저"}:
            return f"surname:{m.group(1)}", m.group(2).strip()

    return None, s


def _classify_pages(pages: list[str], is_prompt_board: bool, known_names: set[str]) -> tuple[list[list[str]], list[list[str]]]:
    """Split a PDF's pages (skipping cover page 1) into prompt_pages and discussion_pages."""
    prompt_pages: list[list[str]] = []
    discussion_pages: list[list[str]] = []

    if not pages:
        return prompt_pages, discussion_pages

    start_idx = 1 if (len(pages) > 1 and _is_cover_page(pages[0])) else 0
    if start_idx == 0 and len(pages) > 1 and not re.search(r"^\s*1[.)]\s+", pages[0], re.M):
        start_idx = 1

    # Heuristic: determine default mode from page content
    in_discussion = False
    for idx in range(start_idx, len(pages)):
        raw_lines = [ln for ln in pages[idx].splitlines() if _clean_line_noise(ln)]
        if not raw_lines:
            continue
        joined = "\n".join(raw_lines)

        if is_prompt_board:
            has_disc = any(
                _extract_speaker_key(ln, known_names, False)[0] is not None
                for ln in raw_lines[:8]
            )
            if has_disc and not re.search(r"발제[자지]\s*[:：]?", joined):
                discussion_pages.append(raw_lines)
            else:
                prompt_pages.append(raw_lines)
            continue

        # In 일지 PDFs:
        has_bal = bool(re.search(r"(?:^|\n)\s*발제[자지]\s*[:：]?", joined))
        has_ref = bool(re.search(r"페이지\s*[:：]|참조\s*[:：]", joined))
        has_header_plus_q = (
            len(raw_lines) >= 2
            and bool(_PROMPT_HEADER_RE.match(raw_lines[0]))
            and bool(re.match(r"^\s*\d+(?:[-–.]\d+)?[.)]\s+", raw_lines[1]))
        )
        has_speaker = any(
            _extract_speaker_key(ln, known_names, "발언 기록" in joined or "발언자 :" in joined)[0] is not None
            for ln in raw_lines[:10]
        )
        has_group_marker = ("[단체 후기]" in joined) or ("발언자 :" in joined) or ("단체 토의로 진행" in joined)

        if has_bal or has_header_plus_q or (has_ref and (not has_speaker or prompt_pages)):
            in_discussion = False
            prompt_pages.append(raw_lines)
        elif has_speaker or has_group_marker:
            in_discussion = True
            discussion_pages.append(raw_lines)
        elif in_discussion:
            discussion_pages.append(raw_lines)
        elif re.match(r"^\s*\d+(?:[-–.]\d+)?[.)]\s+", raw_lines[0]):
            prompt_pages.append(raw_lines)
        elif prompt_pages and not discussion_pages:
            # Prompt continuation page (e.g. second page of a presenter's questions)
            prompt_pages.append(raw_lines)
        elif not prompt_pages and not discussion_pages:
            # Early discussion pages before any prompt pages (e.g. #260/#275/#409 continuation)
            if re.search(r"^\s*\d{2}\s+[가-힣]{2,4}\s*$", raw_lines[0]):
                prompt_pages.append(raw_lines)
            else:
                in_discussion = True
                discussion_pages.append(raw_lines)
        else:
            prompt_pages.append(raw_lines)

    return prompt_pages, discussion_pages


def _parse_prompts(
    prompt_page_groups: list[list[str]],
    anonymizer: TextAnonymizer,
    known_names: set[str],
    book_name_to_anon: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Parse prompt pages into presenter groups with anonymized labels and structured questions."""
    groups: list[dict[str, Any]] = []
    current_group: dict[str, Any] | None = None
    current_q: dict[str, str] | None = None
    in_reference = False
    presenter_idx = 0

    def ensure_group() -> dict[str, Any]:
        nonlocal current_group, presenter_idx
        if current_group is None:
            presenter_idx += 1
            letter = chr(ord("A") + (presenter_idx - 1) % 26)
            suffix = "" if presenter_idx <= 26 else str((presenter_idx - 1) // 26 + 1)
            current_group = {"label": f"발제자 {letter}{suffix}", "questions": []}
            groups.append(current_group)
        return current_group

    def flush_q() -> None:
        nonlocal current_q, in_reference
        if current_q is not None:
            q_text = anonymizer.anonymize(current_q["question"], book_name_to_anon=book_name_to_anon).strip()
            ref_text = anonymizer.anonymize(current_q["reference"], book_name_to_anon=book_name_to_anon).strip()
            if q_text:
                ensure_group()["questions"].append({
                    "number": current_q["number"],
                    "question": q_text,
                    "reference": ref_text,
                })
            current_q = None
            in_reference = False

    def is_presenter_header(line: str, next_line: str) -> bool:
        s = line.strip()
        if re.match(r"^\s*발제[자지]\s*(?:[:：]|$)", s):
            return True
        if re.match(r"^\s*발제[자지][가-힣]{2,}", s):
            return True
        if _PROMPT_HEADER_RE.match(s) and len(s) <= 35:
            # Verify it's not a random sentence
            if re.search(r"(?:학과|학부|전공|\b\d{2}\b)", s) or s in known_names:
                return True
        if s in known_names and _QUESTION_START_RE.match(next_line):
            return True
        return False

    for lines in prompt_page_groups:
        for i, raw_line in enumerate(lines):
            s = raw_line.strip()
            next_s = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if is_presenter_header(s, next_s):
                flush_q()
                current_group = None
                ensure_group()
                continue

            # Ignore leftover socializer header lines
            if re.match(r"^\s*사회자\s*(?:[:：]|$)", s):
                continue

            qm = _QUESTION_START_RE.match(s)
            if qm and not in_reference:
                flush_q()
                current_q = {
                    "number": qm.group(1),
                    "question": qm.group(2).strip(),
                    "reference": "",
                }
                continue
            if qm and in_reference:
                # Could be a new numbered question right after reference!
                body_part = qm.group(2).strip()
                if "?" in body_part or "까" in body_part or len(body_part) > 12:
                    flush_q()
                    current_q = {
                        "number": qm.group(1),
                        "question": body_part,
                        "reference": "",
                    }
                    continue

            if current_q is not None:
                # Check for reference line ("페이지: ... | 참조: ..." or "p.123" / "123p." / "작품 전반")
                if re.match(r"^(?:페이지\s*[:：]|참조\s*[:：]|p\.?\s*\d+|\d+\s*p\.?$|작품\s*전반$)", s, re.I):
                    in_reference = True
                    cleaned_ref = re.sub(r"페이지\s*[:：]\s*\|\s*참조\s*[:：]\s*", "", s).strip()
                    if cleaned_ref:
                        current_q["reference"] = (current_q["reference"] + "\n" + cleaned_ref).strip()
                elif in_reference:
                    current_q["reference"] = (current_q["reference"] + "\n" + s).strip()
                else:
                    current_q["question"] = (current_q["question"] + " " + s).strip()

    flush_q()
    # Drop empty groups & deduplicate questions across duplicate Monday/Thursday uploads
    seen_q: set[str] = set()
    final_groups: list[dict[str, Any]] = []
    for grp in groups:
        deduped = []
        for q in grp["questions"]:
            key = re.sub(r"\s+", "", q["question"])[:80]
            if key and key not in seen_q:
                seen_q.add(key)
                deduped.append(q)
        if deduped:
            final_groups.append({"label": grp["label"], "questions": deduped})
    return final_groups


def _resolve_speaker_name_map(
    speaker_map: dict[str, str],
    book_participants: set[str],
    known_names: set[str],
) -> dict[str, str]:
    """Map full names & unambiguous 2-char given names of mapped speakers to '참여자 X' labels."""
    full_to_anon: dict[str, str] = {}
    pool_local = sorted(book_participants)
    pool_global = sorted(known_names)

    for raw_key, anon_label in speaker_map.items():
        if raw_key.startswith("surname:"):
            continue
        if re.fullmatch(r"[가-힣]{2,4}", raw_key):
            full_to_anon[raw_key] = anon_label
            continue
        # Masked key like "정*용" / "박0서" / "노○림"
        cleaned = re.sub(r"\s+", "", raw_key)
        if len(cleaned) == 3 and cleaned[1] in "*○0O":
            matches = [n for n in pool_local if len(n) == 3 and n[0] == cleaned[0] and n[2] == cleaned[2]]
            if not matches:
                matches = [n for n in pool_global if len(n) == 3 and n[0] == cleaned[0] and n[2] == cleaned[2]]
            if len(matches) == 1:
                full_to_anon[matches[0]] = anon_label

    # Register full names and unambiguous 2-char given names (not colliding across multiple speakers)
    name_to_anon: dict[str, str] = dict(full_to_anon)
    given_candidates: dict[str, set[str]] = {}
    for full_name, anon_label in full_to_anon.items():
        if len(full_name) >= 3:
            given = full_name[1:]
            if given not in HONORIFIC_NIM_ALLOWLIST and given not in LITERARY_NIM_ALLOWLIST:
                given_candidates.setdefault(given, set()).add(anon_label)
    for given, labels in given_candidates.items():
        if len(labels) == 1 and given not in name_to_anon:
            name_to_anon[given] = next(iter(labels))
    return name_to_anon


def _parse_discussion(
    discussion_page_groups: list[list[str]],
    session_label: str,
    anonymizer: TextAnonymizer,
    known_names: set[str],
    book_participants: set[str] | None = None,
) -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Parse discussion pages into anonymized speaker turns (two-pass for full speaker-reference mapping)."""
    all_lines: list[str] = []
    for pg in discussion_page_groups:
        all_lines.extend(pg)
    if not all_lines:
        return None, {}

    full_joined = "\n".join(all_lines)
    single_char_mode = ("발언 기록" in full_joined) or ("발언자 :" in full_joined)

    speaker_map: dict[str, str] = {}

    def get_anon_speaker(raw_key: str) -> str:
        if raw_key not in speaker_map:
            idx = len(speaker_map) + 1
            letter = chr(ord("A") + (idx - 1) % 26)
            suffix = "" if idx <= 26 else str((idx - 1) // 26 + 1)
            speaker_map[raw_key] = f"참여자 {letter}{suffix}"
        return speaker_map[raw_key]

    raw_turns: list[tuple[str, str]] = []
    cur_speaker: str | None = None
    cur_buf: list[str] = []

    def flush_raw_turn() -> None:
        nonlocal cur_buf
        if cur_buf:
            raw_txt = " ".join(cur_buf).strip()
            if raw_txt:
                raw_turns.append((cur_speaker or "참여자", raw_txt))
            cur_buf = []

    for ln in all_lines:
        s = ln.strip()
        if not s:
            continue
        if re.match(r"^\d{4}\s*_\s*\[.*\]_?세미나는", s) or s.startswith("발언자 : 총 ") or s in ("[단체 후기]", "발언 기록 :"):
            continue
        if re.match(r"^\d+\s*기\s*[가-힣*○]+\s*\(\s*이하\s*[가-힣]\s*\)", s):
            continue
        if s.startswith("○ 토의 발제"):
            flush_raw_turn()
            cur_speaker = "토의 주제"
            cur_buf.append(s)
            continue

        sp_key, rest = _extract_speaker_key(s, known_names, single_char_mode)
        if sp_key is not None:
            flush_raw_turn()
            cur_speaker = get_anon_speaker(sp_key)
            if rest:
                cur_buf.append(rest)
        else:
            cur_buf.append(s)

    flush_raw_turn()
    if not raw_turns:
        return None, {}

    session_name_to_anon = _resolve_speaker_name_map(
        speaker_map,
        book_participants or set(),
        known_names,
    )

    turns: list[dict[str, str]] = []
    for spk, raw_txt in raw_turns:
        txt = anonymizer.anonymize(raw_txt, book_name_to_anon=session_name_to_anon)
        # Strip leading redundant "참여자" / "참여자 A" left over from self-intro
        txt = re.sub(r"^참여자(?:\s+[A-Z0-9]+)?(?:입니다|이고요|이라고\s*합니다)?[.,\s]*", "", txt).strip()
        if txt:
            turns.append({"speaker": spk, "text": txt})

    if not turns:
        return None, session_name_to_anon
    return {
        "session_label": session_label,
        "turns": turns,
    }, session_name_to_anon


# ---------------- Notion API (Read-Only) ----------------

def _load_notion_token() -> str:
    if not NOTION_ENV_PATH.exists():
        return ""
    for line in NOTION_ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() in ("NOTION_TOKEN", "NOTION_API_KEY"):
            return v.strip().strip('"').strip("'")
    return ""


def _notion_get(path: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(
        f"https://api.notion.com/v1/{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_notion_children(block_id: str, token: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    cursor: str | None = None
    while True:
        q = f"blocks/{block_id}/children?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
        data = _notion_get(q, token)
        results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return results


def _rt_runs(rich_text: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    runs: list[dict[str, str]] = []
    for t in rich_text or []:
        txt = t.get("plain_text", "")
        if not txt:
            continue
        href = t.get("href") or ""
        if href:
            runs.append({"text": txt, "href": href})
        else:
            runs.append({"text": txt})
    return runs


def _plain_from_runs(runs: list[dict[str, str]]) -> str:
    return "".join(r.get("text", "") for r in runs).strip()


def _extract_urls_from_runs(runs: list[dict[str, str]]) -> list[str]:
    urls: list[str] = []
    for r in runs:
        href = r.get("href", "")
        if href and href.startswith(("http://", "https://")) and href not in urls:
            urls.append(href)
        for m in re.findall(r"https?://[^\s\])>\"']+", r.get("text", "")):
            if m not in urls:
                urls.append(m)
    return urls


def _collect_notion_blocks_tree(
    block_id: str,
    token: str,
    depth: int = 0,
    include_child_pages: bool = False,
) -> list[dict[str, Any]]:
    if depth > 3:
        return []
    out: list[dict[str, Any]] = []
    for b in _fetch_notion_children(block_id, token):
        btype = b.get("type", "")
        val = b.get(btype, {}) if isinstance(b.get(btype), dict) else {}
        node: dict[str, Any] = {"type": btype, "id": b.get("id", "")}
        if "rich_text" in val:
            node["runs"] = _rt_runs(val.get("rich_text"))
        elif btype == "table_row":
            node["cells"] = [_rt_runs(c) for c in val.get("cells", [])]
        elif btype in ("bookmark", "embed", "link_preview"):
            node["url"] = val.get("url", "")
        elif btype == "child_page":
            node["title"] = val.get("title", "")
        if b.get("has_children") and (
            btype not in ("child_page", "child_database")
            or (btype == "child_page" and include_child_pages and depth < 2)
        ):
            node["children"] = _collect_notion_blocks_tree(
                b["id"],
                token,
                depth + 1,
                include_child_pages=include_child_pages,
            )
        out.append(node)
    return out


def fetch_pre_seminar_from_notion(catalog_by_slug: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Fetch the 15 curated pre-seminar reading guides from Notion (read-only)."""
    token = _load_notion_token()
    if not token:
        return []
    try:
        top_blocks = _fetch_notion_children(NOTION_PRE_SEMINAR_PAGE_ID, token)
    except (urllib.error.URLError, TimeoutError, OSError):
        return []

    books: list[dict[str, Any]] = []
    for blk in top_blocks:
        if blk.get("type") != "child_page":
            continue
        page_title = (blk.get("child_page", {}).get("title") or "").strip()
        slug = PRE_SEMINAR_TITLE_TO_SLUG.get(page_title)
        if not slug or slug not in catalog_by_slug:
            continue
        meta = catalog_by_slug[slug]
        tree = _collect_notion_blocks_tree(blk["id"], token, include_child_pages=True)

        sections: list[dict[str, Any]] = []
        references: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        edition_note = ""

        def add_block(sec_list: list[dict[str, Any]], node: dict[str, Any]) -> None:
            nonlocal edition_note
            bt = node["type"]
            if bt == "child_page":
                child_title = (node.get("title") or "").strip()
                if child_title:
                    sec_list.append({"level": 2, "heading": child_title, "items": []})
                for ch in node.get("children", []):
                    add_block(sec_list, ch)
                return

            if bt in ("heading_1", "heading_2", "heading_3"):
                heading_txt = _plain_from_runs(node.get("runs", []))
                if heading_txt:
                    level = int(bt.split("_")[1])
                    sec_list.append({"level": level, "heading": heading_txt, "items": []})
                for ch in node.get("children", []):
                    add_block(sec_list, ch)
                return

            if bt == "divider":
                return

            if bt == "table":
                rows_data = []
                for ch in node.get("children", []):
                    if ch["type"] == "table_row":
                        rows_data.append([_plain_from_runs(c) for c in ch.get("cells", [])])
                if rows_data:
                    if not sec_list:
                        sec_list.append({"level": 2, "heading": "개요", "items": []})
                    sec_list[-1]["items"].append({"type": "table", "rows": rows_data})
                return

            if bt in ("bookmark", "embed", "link_preview"):
                u = node.get("url", "")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    references.append({"title": u, "url": u})
                return

            runs = node.get("runs", [])
            plain = _plain_from_runs(runs)
            if not plain:
                return

            # Capture top-of-page edition line ("작가 · 책 · 출판사")
            if not sec_list and "·" in plain and len(plain) < 120 and not edition_note:
                edition_note = plain
                return

            urls = _extract_urls_from_runs(runs)
            for u in urls:
                if u not in seen_urls:
                    seen_urls.add(u)
                    references.append({"title": plain[:140], "url": u})

            if not sec_list:
                sec_list.append({"level": 2, "heading": "작품 안내", "items": []})

            item_type = (
                "li" if bt == "bulleted_list_item"
                else "quote" if bt in ("quote", "callout")
                else "p"
            )
            sec_list[-1]["items"].append({"type": item_type, "runs": runs})
            for ch in node.get("children", []):
                add_block(sec_list, ch)

        for node in tree:
            add_block(sections, node)

        # Clean empty sections
        sections = [sec for sec in sections if sec["items"] or sec["level"] == 1]

        books.append({
            "slug": slug,
            "semester": meta["semester"],
            "semester_label": meta["semester_label"],
            "date": meta["date"],
            "title": meta["title"],
            "author": meta["author"],
            "genre": meta["genre"],
            "edition_note": edition_note,
            "sections": sections,
            "references": references,
        })

    return books


def build_special_programs() -> list[dict[str, Any]]:
    """Curated, non-PII, non-numeric-stats highlights for Pil-dam & Misikhoe."""
    return [
        {
            "id": "pildam-joint-seminar",
            "badge": "연합세미나",
            "title": "책 먹는 호반우 × 필담 연합 세미나",
            "period": "2026-1학기",
            "summary": (
                "경북대학교 중앙 독서동아리 ‘책 먹는 호반우’와 창작동아리 ‘필담’이 함께 연 합동 세미나입니다. "
                "책반우 내부 문예 공모전 〈미식회〉 우수작과 필담의 창작 작품을 사전 공유한 뒤, "
                "조별 토의와 단체 공유를 통해 읽기와 쓰기의 시선을 함께 나누었습니다."
            ),
            "highlights": [
                "읽기 중심 독서동아리와 쓰기 중심 창작동아리의 첫 교류 세미나",
                "부원 창작 작품을 대상으로 한 발제문 작성 및 조별 합평·토론",
                "연합 세미나 이후 소감을 담은 공동 회지 제작 프로젝트로 확장",
            ],
        },
        {
            "id": "misikhoe-contest",
            "badge": "내부 문예 공모전",
            "title": "책반우 백일장 〈미식회〉",
            "period": "제1회 2026 겨울 · 제2회 2026 여름",
            "summary": (
                "“여러분의 가장 맛있는 문장을 보여주세요”라는 모토 아래 부원들이 직접 창작물을 선보이는 "
                "책반우 내부 문예 공모전입니다. 필명을 사용한 블라인드 투고로 시·소설·수필·서평·독후감을 "
                "모아 함께 읽고 서로의 문장을 비평하며 세미나를 넘어선 창작 경험을 쌓았습니다."
            ),
            "highlights": [
                "제1회: 커리큘럼 도서 독후감·서평 및 제시어 기반 자유 작문",
                "제2회: 제시 주제어(일탈, 창문, 여행, 바다, 기억, 장마 등) 기반 시·소설·수필 투고",
                "필명 익명 심사와 우수작 세미나 공동 강독 진행",
            ],
        },
    ]


def verify_zero_pii(payload: Any, member_names: set[str], label: str, check_nim: bool = False) -> None:
    """Fail-fast guard ensuring zero PII leaks into generated JSON."""
    serialized = json.dumps(payload, ensure_ascii=False)
    checks = [
        ("phone", re.compile(r"(?<!\d)01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}(?!\d)")),
        ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
        ("student_id", re.compile(r"\b20[12]\d{6,7}\b")),
        ("bank_account", re.compile(r"(?:국민|신한|우리|하나|농협|기업|카카오뱅크|토스뱅크|새마을|우체국|대구)\s*[:\-]?\s*\d{2,6}[-\s]?\d{2,6}")),
    ]
    for kind, pat in checks:
        m = pat.search(serialized)
        if m:
            raise AssertionError(f"PII leak detected in {label} ({kind}): {m.group(0)!r}")

    # Verify no unmasked 3+ char member name leaked
    strict_names = [
        n for n in member_names
        if len(n) >= 3 and n not in LITERARY_STOPWORDS and n not in {"김연수", "김나영"}
    ]
    for name in strict_names:
        if name in serialized:
            raise AssertionError(f"Unmasked member name detected in {label}: <{len(name)}-char name>")

    if check_nim:
        for m in re.finditer(rf"([가-힣]{{2,5}})\s*님{_NIM_BOUNDARY}", serialized):
            tok = m.group(1)
            if tok == "다른" or tok in HONORIFIC_NIM_ALLOWLIST or tok.endswith(HONORIFIC_NIM_SUFFIXES) or tok in LITERARY_NIM_ALLOWLIST:
                continue
            raise AssertionError(f"Unmasked honorific name mention detected in {label}: <{len(tok)}-char token>")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pdf_pages, member_names, article_member_names = load_backup_pdfs()
    anonymizer = TextAnonymizer(member_names)

    sem_label_map = {s["id"]: s["label"] for s in SEMESTER_META}
    books: list[dict[str, Any]] = []
    catalog_by_slug: dict[str, dict[str, Any]] = {}

    for slug, semester, dt, title, author, genre, prompt_aids, log_aids, status_note in BOOK_CATALOG:
        all_prompt_pages: list[list[str]] = []
        discussion_sections: list[dict[str, Any]] = []
        book_participants: set[str] = set()
        merged_name_to_anon: dict[str, str] = {}

        for aid in prompt_aids:
            book_participants.update(article_member_names.get((4, aid), set()))
        for aid in log_aids:
            book_participants.update(article_member_names.get((5, aid), set()))

        for aid in prompt_aids:
            for pages in pdf_pages.get((4, aid), []):
                p_pages, d_pages = _classify_pages(pages, is_prompt_board=True, known_names=member_names)
                all_prompt_pages.extend(p_pages)
                if d_pages:
                    sec, sec_map = _parse_discussion(
                        d_pages, f"{dt} 세미나 토의", anonymizer, member_names, book_participants
                    )
                    merged_name_to_anon.update(sec_map)
                    if sec:
                        discussion_sections.append(sec)

        for aid in log_aids:
            for pages in pdf_pages.get((5, aid), []):
                p_pages, d_pages = _classify_pages(pages, is_prompt_board=False, known_names=member_names)
                all_prompt_pages.extend(p_pages)
                if d_pages:
                    sec, sec_map = _parse_discussion(
                        d_pages, f"{dt} 세미나 토의 (서기 정리본)", anonymizer, member_names, book_participants
                    )
                    merged_name_to_anon.update(sec_map)
                    if sec:
                        discussion_sections.append(sec)

        prompts = _parse_prompts(
            all_prompt_pages,
            anonymizer,
            member_names,
            book_name_to_anon=merged_name_to_anon,
        )
        entry = {
            "slug": slug,
            "semester": semester,
            "semester_label": sem_label_map[semester],
            "date": dt,
            "title": title,
            "author": author,
            "genre": genre,
            "status_note": status_note,
            "has_prompts": len(prompts) > 0,
            "has_discussion": len(discussion_sections) > 0,
            "prompt_count": sum(len(g["questions"]) for g in prompts),
            "discussion_turn_count": sum(len(s["turns"]) for s in discussion_sections),
            "prompts": prompts,
            "discussion_sections": discussion_sections,
        }
        books.append(entry)
        catalog_by_slug[slug] = entry

    public_archive = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "club_name": "경북대학교 중앙 독서동아리 책 먹는 호반우",
        "semesters": SEMESTER_META,
        "special_programs": build_special_programs(),
        "books": books,
    }
    verify_zero_pii(public_archive, member_names, "public_archive.json", check_nim=True)

    pre_books = fetch_pre_seminar_from_notion(catalog_by_slug)
    if not pre_books and PRE_SEMINAR_PATH.exists():
        # Preserve existing snapshot if Notion is unreachable offline
        existing = json.loads(PRE_SEMINAR_PATH.read_text(encoding="utf-8"))
        pre_books = existing.get("books", [])

    pre_seminar_payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "description": "책 먹는 호반우 회원 전용 세미나 전 읽기 자료 (작가 배경 · 학술 논문 · 서평 링크)",
        "semesters": [s for s in SEMESTER_META if s["id"] in ("2026-여름", "2026-2")],
        "books": pre_books,
    }
    verify_zero_pii(pre_seminar_payload, member_names, "member_pre_seminar_materials.json")

    PUBLIC_ARCHIVE_PATH.write_text(json.dumps(public_archive, ensure_ascii=False, indent=2), encoding="utf-8")
    PRE_SEMINAR_PATH.write_text(json.dumps(pre_seminar_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote {PUBLIC_ARCHIVE_PATH} ({PUBLIC_ARCHIVE_PATH.stat().st_size:,} bytes), books={len(books)}")
    print(f"  with prompts: {sum(1 for b in books if b['has_prompts'])}, with discussion: {sum(1 for b in books if b['has_discussion'])}")
    print(f"Wrote {PRE_SEMINAR_PATH} ({PRE_SEMINAR_PATH.stat().st_size:,} bytes), books={len(pre_books)}")


if __name__ == "__main__":
    main()
