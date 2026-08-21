"""
경북대 총동아리연합회 세미나실 예약 게시판 크롤러 + 글 생성 헬퍼.

  - dongari.knu.ac.kr 게시판은 gnuboard5 기반 서버 렌더링 HTML 이므로
    requests + BeautifulSoup 만으로 파싱 가능하다.
  - 게시판 **조회**는 로그인 없이 가능 (게스트).
  - 글 **작성**은 원래 로그인이 필요하지만, 이 프로젝트에선 자동 작성을 하지 않는다.
    대신 사용자가 복사·붙여넣기 할 수 있도록 제목/내용 텍스트만 생성한다.
  - 게시글은 wr_id 를 PK 로 Supabase 에 캐싱한다.
    승인/반려는 종착 상태이므로 이미 캐시된 글이면 상세 페이지를 재요청하지 않는다.
    -> 첫 1회 크롤 이후엔 신규 글 + pending 글의 상세만 fetch.
"""

import os
import re
import logging
from datetime import datetime, timedelta, date, timezone

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://dongari.knu.ac.kr"
BOARD_URL = f"{BASE_URL}/bbs/board.php?bo_table=place"
WRITE_URL = f"{BASE_URL}/bbs/write.php?bo_table=place"

WEEKDAY_KR = ['월', '화', '수', '목', '금', '토', '일']
SEMINAR_ROOMS = ['민주', '통일', '백호']

USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)

# ─────────────────────────────────────────────
# 예약 신청 글 기본값 (env 로 덮어쓰기 가능)
# ─────────────────────────────────────────────
CLUB_NAME = os.environ.get('SEMINAR_CLUB_NAME', '책 먹는 호반우')
CLUB_PHONE = os.environ.get('SEMINAR_CLUB_PHONE', '010-6509-3524')
SEMINAR_TIME_SLOT = os.environ.get('SEMINAR_TIME_SLOT', '19:00~21:00')
SEMINAR_PURPOSE = os.environ.get('SEMINAR_PURPOSE', '동아리 세미나 진행')

# 이번 학기 마지막 세미나 날짜 (학기 바뀌면 수정)
SEMESTER_LAST_DATE = date(2026, 6, 8)

TARGET_WEEKDAYS = (0, 3)   # 월(0), 목(3)
DAYS_AHEAD_MIN = 7         # 최소 7일 후부터 예약 가능
DAYS_AHEAD_MAX = 28        # 최대 28일 후까지 예약 가능


# ─────────────────────────────────────────────
# 파싱 유틸
# ─────────────────────────────────────────────
_DATE_TOKEN_RE = re.compile(
    r'''(?<!\d)(?:
        (?P<ymd_kr>(?P<y_kr>\d{4})\s*년?\s*(?P<ym_kr>\d{1,2})\s*월\s*(?P<yd_kr>\d{1,2})\s*일?)
      | (?P<ymd_num>(?P<y_num>\d{4})\s*[./-]\s*(?P<ym_num>\d{1,2})\s*[./-]\s*(?P<yd_num>\d{1,2}))
      | (?P<md_kr>(?P<m_kr>\d{1,2})\s*월\s*(?P<d_kr>\d{1,2})\s*일?)
      | (?P<md_num>(?P<m_num>\d{1,2})\s*[./-]\s*(?P<d_num>\d{1,2}))
      | (?P<bare_day>(?P<d_only>\d{1,2})\s*일)
      | (?P<compact_day>(?P<d_compact>\d{1,2})(?=\s*[,，·]))
    )(?!\d)''',
    re.VERBOSE,
)


def _date_scope_from_title(title: str) -> str:
    """동아리명·대여 문구를 제외하고 제목의 날짜 표현 부분만 반환한다."""
    text = str(title or '').strip()
    text = re.sub(r'^\s*[\[［【][^\]］】]+[\]］】]\s*', '', text, count=1)
    room_marker = re.search(r'세미나\s*실', text)
    if room_marker:
        text = text[:room_marker.start()]

    # 요일은 날짜 구분자가 아니므로 먼저 제거한다. "(금,토)"도 지원한다.
    text = re.sub(
        r'[\(（]\s*[월화수목금토일](?:\s*,\s*[월화수목금토일])*\s*(?:요일)?\s*[\)）]',
        ' ',
        text,
    )
    return (text.replace('／', '/').replace('．', '.')
            .replace('～', '~').replace('〜', '~')
            .replace('–', '-').replace('—', '-').replace('−', '-'))


def _is_date_range_connector(text: str) -> bool:
    compact = re.sub(r'\s+', '', text or '')
    return ('~' in compact or '부터' in compact or '까지' in compact
            or (bool(compact) and set(compact) <= {'-'}))


def parse_dates_from_title(title: str, fallback_year: int) -> list:
    """게시글 제목에서 예약 날짜를 유연하게 추출한다.

    월·연도 반복 생략(`8월 26일, 27일, 28일`), 숫자 표기(`9/13`),
    연속 범위(`9월 11일~13일`)와 혼합 월 표기를 모두 지원한다.
    범위는 시작일부터 종료일까지의 모든 날짜로 펼친다.
    """
    scope = _date_scope_from_title(title)
    year_match = re.search(
        r'(?<!\d)(\d{4})\s*(?:년)?(?=\s*\d{1,2}\s*(?:월|[./-]))',
        scope,
    )
    base_year = int(year_match.group(1)) if year_match else int(fallback_year)

    parsed: list[date] = []
    current_year = base_year
    current_month = None
    previous_date = None
    previous_end = 0

    for match in _DATE_TOKEN_RE.finditer(scope):
        explicit_year = False
        explicit_month = False

        if match.group('ymd_kr'):
            current_year = int(match.group('y_kr'))
            current_month = int(match.group('ym_kr'))
            day = int(match.group('yd_kr'))
            explicit_year = explicit_month = True
        elif match.group('ymd_num'):
            current_year = int(match.group('y_num'))
            current_month = int(match.group('ym_num'))
            day = int(match.group('yd_num'))
            explicit_year = explicit_month = True
        elif match.group('md_kr'):
            current_month = int(match.group('m_kr'))
            day = int(match.group('d_kr'))
            explicit_month = True
        elif match.group('md_num'):
            current_month = int(match.group('m_num'))
            day = int(match.group('d_num'))
            explicit_month = True
        else:
            if current_month is None:
                continue
            day = int(match.group('d_only') or match.group('d_compact'))

        connector = scope[previous_end:match.start()] if previous_date else ''
        is_range = previous_date is not None and _is_date_range_connector(connector)

        try:
            candidate = date(current_year, current_month, day)
        except (TypeError, ValueError):
            previous_end = match.end()
            continue

        # "12월 30일~1월 2일"처럼 연도만 생략된 연말 범위도 처리한다.
        if (is_range and candidate < previous_date and not explicit_year
                and explicit_month and current_month < previous_date.month):
            try:
                current_year = previous_date.year + 1
                candidate = date(current_year, current_month, day)
            except ValueError:
                previous_end = match.end()
                continue

        if is_range:
            gap = (candidate - previous_date).days
            if 0 <= gap <= 62:
                parsed.extend(previous_date + timedelta(days=offset)
                              for offset in range(gap + 1))
            else:
                parsed.append(candidate)
        else:
            parsed.append(candidate)

        previous_date = candidate
        previous_end = match.end()

    return sorted(set(parsed))


def is_seminar_post(title: str) -> bool:
    """진짜 세미나실 예약 글인지 판정.

    대괄호류 동아리명 + 세미나실 + 방 이름을 모두 요구해 일반 안내 공지를
    예약 글로 잘못 인식하지 않도록 한다.
    """
    return bool(
        extract_club_name(title)
        and re.search(r'세미나\s*실', str(title or ''))
        and get_room_from_title(title)
    )


def get_room_from_title(title: str):
    text = str(title or '')
    marker = re.search(r'세미나\s*실', text)
    if marker:
        after = text[marker.end():]
        found = re.match(
            r'\s*(?:[:：=\-]|[\(（\[［【{])*\s*(민주|통일|백호)',
            after,
        )
        if found:
            return found.group(1)

        before = text[:marker.start()]
        found = re.search(r'(민주|통일|백호)\s*(?:방|실)?\s*$', before)
        if found:
            return found.group(1)

    # 건물명(예: 백호관)이나 동아리명 때문에 방을 잘못 고르지 않도록
    # 대괄호 동아리명과 "백호관"을 제외한 뒤 하나로 확정될 때만 사용한다.
    body = re.sub(r'^\s*[\[［【][^\]］】]+[\]］】]\s*', '', text, count=1)
    body = re.sub(r'(민주|통일|백호)\s*관', '', body)
    candidates = {room for room in SEMINAR_ROOMS if room in body}
    if len(candidates) == 1:
        return next(iter(candidates))
    return None


def extract_club_name(title: str):
    m = re.match(r'^\s*[\[［【]([^\]］】]+)[\]］】]', str(title or ''))
    return m.group(1).strip() if m else None


# ─────────────────────────────────────────────
# HTML 파서
# ─────────────────────────────────────────────
def parse_listing(html: str):
    """게시판 목록에서 (wr_id, title, post_url) 리스트를 반환."""
    soup = BeautifulSoup(html, 'html.parser')
    rows = []
    for div in soup.select('div.bo_tit'):
        a = div.find('a', href=lambda h: h and 'wr_id=' in h)
        if not a:
            continue
        href = a.get('href', '')
        m = re.search(r'wr_id=(\d+)', href)
        if not m:
            continue
        wr_id = int(m.group(1))
        title = a.get_text(strip=True)
        if not href.startswith('http'):
            href = BASE_URL + ('' if href.startswith('/') else '/') + href.lstrip('/')
        rows.append((wr_id, title, href))
    return rows


def parse_status_from_detail(html: str) -> str:
    """글 상세 페이지에서 승인/반려/대기 상태를 판정."""
    soup = BeautifulSoup(html, 'html.parser')
    cmt = (soup.find(id='cmt_list')
           or soup.find(class_='cmt_list')
           or soup.find(id='comment_list'))
    text = cmt.get_text(' ', strip=True) if cmt else soup.get_text(' ', strip=True)
    if '승인' in text:
        return 'approved'
    if any(kw in text for kw in ['반려', '불가', '거절', '취소']):
        return 'rejected'
    return 'pending'


def parse_subject_from_detail(html: str):
    """상세 페이지의 <h1> 에서 풀 제목 추출.

    gnuboard5 의 상세 페이지에서 잘리지 않은 풀 제목은 <h1> 안에 있고
    끝에 ' > 게시판명' 이 붙는다(예: '... 대여 신청 > 공용공간 대여').
    그 부분을 떼서 반환. 추출 실패 시 None.
    """
    soup = BeautifulSoup(html, 'html.parser')
    h1 = soup.find('h1')
    if not h1:
        return None
    text = h1.get_text(' ', strip=True)
    if not text:
        return None
    idx = text.rfind(' > ')
    if idx > 0:
        text = text[:idx].rstrip()
    return text or None


def is_truncated_listing_title(title: str) -> bool:
    """게시판 listing 의 제목이 잘려있는지 판정.

    gnuboard 게시판은 긴 제목을 '…' 또는 '...' 으로 잘라 노출한다.
    [동아리명] 으로 시작하는 잘린 글은 세미나실 신청글 후보로 본다.
    """
    if not extract_club_name(title):
        return False
    cleaned = str(title or '').rstrip()
    return cleaned.endswith('…') or cleaned.endswith('...')


# ─────────────────────────────────────────────
# 세션 (게스트 조회 전용)
# ─────────────────────────────────────────────
def make_session():
    """User-Agent 만 세팅한 requests.Session 반환 (로그인하지 않음)."""
    s = requests.Session()
    s.headers.update({
        'User-Agent': USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
    })
    return s


# ─────────────────────────────────────────────
# F5 BIG-IP ASM JavaScript 챌린지 솔버
# ─────────────────────────────────────────────
#
# 클라우드 IP(Render 등)에서 dongari.knu.ac.kr 에 접근하면 첫 요청은 800B 짜리
# JS 챌린지 페이지로 응답된다. 진짜 브라우저는 다음을 수행한다:
#   1) AES-CBC 로 16바이트 평문을 복호화 → hex 인코딩
#   2) document.cookie = "<NAME>=<HEX>" 세팅
#   3) document.location.href 또는 reload() 로 같은 URL 재요청
# 우리는 JS 엔진 없이 위 단계를 Python 으로 재현한다.

_CHALLENGE_MARKERS = ('cupid.js', 'slowAES', 'toNumbers(', 'toHex(')
_CHALLENGE_HEX_RE = re.compile(r'toNumbers\(\s*"([0-9a-fA-F]+)"\s*\)')
_CHALLENGE_COOKIE_NAME_RE = re.compile(
    r'document\.cookie\s*=\s*"\s*([A-Za-z0-9_]+)\s*=', re.IGNORECASE
)


def looks_like_f5_challenge(html: str) -> bool:
    """응답이 F5/BIG-IP JS 챌린지인지 빠르게 판정."""
    if len(html) > 8000:
        return False
    hits = sum(1 for m in _CHALLENGE_MARKERS if m in html)
    return hits >= 2


def solve_f5_challenge(html: str):
    """챌린지 HTML 에서 (cookie_name, cookie_value) 추출.

    Returns:
        (name, value) 튜플 또는 None(실패).
    """
    try:
        from Crypto.Cipher import AES
    except ImportError:
        return None

    hex_strings = _CHALLENGE_HEX_RE.findall(html)
    if len(hex_strings) < 3:
        return None
    try:
        key = bytes.fromhex(hex_strings[0])
        iv = bytes.fromhex(hex_strings[1])
        ct = bytes.fromhex(hex_strings[2])
    except ValueError:
        return None
    if len(key) not in (16, 24, 32) or len(iv) != 16 or len(ct) == 0 or len(ct) % 16 != 0:
        return None
    try:
        pt = AES.new(key, AES.MODE_CBC, iv).decrypt(ct)
    except Exception:
        return None

    m = _CHALLENGE_COOKIE_NAME_RE.search(html)
    name = m.group(1) if m else None
    if not name:
        return None
    return name, pt.hex()


def fetch_with_challenge(session: requests.Session, url: str,
                        timeout: int = 20, max_retries: int = 2):
    """챌린지를 감지하면 쿠키 풀이 후 재요청. requests.Response 반환."""
    last = None
    for attempt in range(max_retries + 1):
        resp = session.get(url, timeout=timeout)
        resp.raise_for_status()
        last = resp
        if not looks_like_f5_challenge(resp.text):
            return resp
        solved = solve_f5_challenge(resp.text)
        if not solved:
            return resp
        name, value = solved
        host = requests.utils.urlparse(url).hostname or 'dongari.knu.ac.kr'
        session.cookies.set(name, value, domain=host, path='/')
    return last


# ─────────────────────────────────────────────
# 글 생성 헬퍼 (복사·붙여넣기용)
# ─────────────────────────────────────────────
def format_date_korean(d: date) -> str:
    """2026년 5월 14일(목)"""
    return f"{d.year}년 {d.month}월 {d.day}일({WEEKDAY_KR[d.weekday()]})"


def format_date_short(d: date) -> str:
    """5월 14일(목)"""
    return f"{d.month}월 {d.day}일({WEEKDAY_KR[d.weekday()]})"


def generate_post_title(dates, room: str, club_name: str | None = None) -> str:
    """예약 신청 글 제목을 생성."""
    club_name = club_name or CLUB_NAME
    sorted_dates = sorted(dates)
    if not sorted_dates:
        return ""
    if len(sorted_dates) == 1:
        return (f"[{club_name}] {format_date_korean(sorted_dates[0])} "
                f"세미나실({room}) 대여 신청")
    year = sorted_dates[0].year
    parts = ', '.join(format_date_short(d) for d in sorted_dates)
    return f"[{club_name}] {year}년 {parts} 세미나실({room}) 대여 신청"


def generate_post_content(time_slot: str | None = None,
                          purpose: str | None = None,
                          phone: str | None = None) -> str:
    """예약 신청 글 본문 생성 (원본 seminar_auto.py 와 동일 형식)."""
    return (
        f"일시: {time_slot or SEMINAR_TIME_SLOT}\n"
        f"목적: {purpose or SEMINAR_PURPOSE}\n"
        f"대표자번호: {phone or CLUB_PHONE}"
    )


def compute_available_dates(by_date: dict, *,
                            today: date | None = None,
                            days_ahead_min: int = DAYS_AHEAD_MIN,
                            days_ahead_max: int = DAYS_AHEAD_MAX,
                            semester_start: date | None = None,
                            semester_last: date | None = SEMESTER_LAST_DATE,
                            target_weekdays=TARGET_WEEKDAYS) -> list:
    """예약 가능한 월/목 날짜를 계산.

    Args:
        by_date: {'YYYY-MM-DD': [post, ...]} — 각 post 는 status 키를 가져야 함.
                 status != 'rejected' 인 글이 있으면 그 날짜는 점유로 본다.
        semester_start: 학기 시작일(이전 날짜는 제외, None 이면 제한 없음)
        semester_last:  학기 종료일(이후 날짜는 제외, None 이면 제한 없음)
    Returns:
        list[date] — 예약 가능 날짜들(오름차순).
    """
    if today is None:
        today = datetime.now().date()
    available = []
    for delta in range(days_ahead_min, days_ahead_max + 1):
        d = today + timedelta(days=delta)
        if semester_last and d > semester_last:
            break
        if semester_start and d < semester_start:
            continue
        if d.weekday() not in target_weekdays:
            continue
        occupied = any(
            (p.get('status') or '') != 'rejected'
            for p in by_date.get(d.isoformat(), [])
        )
        if not occupied:
            available.append(d)
    return available


# ─────────────────────────────────────────────
# 설정 로드/저장 (싱글톤 행, id=1)
# ─────────────────────────────────────────────
SETTINGS_KEYS = (
    'club_name', 'club_phone', 'time_slot', 'purpose',
    'semester_start', 'semester_end',
    'days_ahead_min', 'days_ahead_max',
)


def default_settings() -> dict:
    """DB 가 비어있을 때 쓸 기본값."""
    return {
        'club_name': CLUB_NAME,
        'club_phone': CLUB_PHONE,
        'time_slot': SEMINAR_TIME_SLOT,
        'purpose': SEMINAR_PURPOSE,
        'semester_start': None,
        'semester_end': SEMESTER_LAST_DATE.isoformat() if SEMESTER_LAST_DATE else None,
        'days_ahead_min': DAYS_AHEAD_MIN,
        'days_ahead_max': DAYS_AHEAD_MAX,
    }


def load_settings(supabase) -> dict:
    """seminar_room_settings 테이블에서 설정 1행을 읽어온다.

    테이블이 없거나 행이 없으면 default_settings() 를 반환.
    날짜 컬럼은 ISO 문자열로 정규화한다.
    """
    settings = default_settings()
    try:
        res = supabase.table('seminar_room_settings') \
            .select('*').eq('id', 1).execute()
        rows = res.data or []
    except Exception:
        return settings
    if not rows:
        return settings
    row = rows[0]
    for k in SETTINGS_KEYS:
        v = row.get(k)
        if v is None or v == '':
            continue
        if k in ('semester_start', 'semester_end'):
            settings[k] = str(v)[:10]
        else:
            settings[k] = v
    return settings


def save_settings(supabase, payload: dict) -> dict:
    """seminar_room_settings 싱글톤(id=1)에 upsert. 허용된 키만 반영."""
    row: dict = {'id': 1}
    for k in SETTINGS_KEYS:
        if k not in payload:
            continue
        v = payload[k]
        if isinstance(v, str):
            v = v.strip()
            if v == '':
                v = None
        if k in ('days_ahead_min', 'days_ahead_max') and v is not None:
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
        row[k] = v
    row['updated_at'] = datetime.now(timezone.utc).isoformat()
    supabase.table('seminar_room_settings') \
        .upsert(row, on_conflict='id').execute()
    return load_settings(supabase)


# ─────────────────────────────────────────────
# 크롤
# ─────────────────────────────────────────────
def crawl(supabase, *, max_pages: int = 3, recheck_pending: bool = True,
          logger: logging.Logger | None = None) -> dict:
    """게시판을 크롤링하여 seminar_room_posts 에 upsert.

    Returns:
        {
            'new': 신규 발견 글 수,
            'rechecked': pending 재확인 수,
            'skipped_terminal': 종착 상태로 스킵된 수,
            'pages_scanned': 실제로 받아본 페이지 수,
        }
    """
    log = logger or logging.getLogger(__name__)
    session = make_session()

    # 기존 캐시 로드. 종착 상태 글도 상세 페이지를 다시 받지 않고 저장된 제목을
    # 최신 파서로 재해석할 수 있도록 파싱 관련 필드를 함께 가져온다.
    try:
        existing = supabase.table('seminar_room_posts') \
            .select('wr_id, title, club_name, room, dates, status, post_url') \
            .execute().data or []
    except Exception as e:
        log.warning(f"기존 캐시 조회 실패(빈 캐시로 진행): {e}")
        existing = []
    known = {row['wr_id']: row for row in existing}

    now_iso = datetime.now(timezone.utc).isoformat()
    fallback_year = datetime.now().year

    upserts: list = []
    new_count = 0
    rechecked_count = 0
    skipped_terminal = 0
    reparsed_terminal = 0
    pages_scanned = 0
    diagnostics: list = []   # 페이지별 응답 진단(디버그용)
    total_listed = 0
    seminar_matched = 0

    for page_num in range(1, max_pages + 1):
        url = f"{BOARD_URL}&page={page_num}"
        try:
            resp = fetch_with_challenge(session, url, timeout=20)
        except requests.RequestException as e:
            log.warning(f"page {page_num} 요청 실패: {e}")
            diagnostics.append({'page': page_num, 'error': f'{type(e).__name__}: {e}'})
            break
        pages_scanned = page_num

        listing = parse_listing(resp.text)
        total_listed += len(listing)
        sample_titles = [t[:80] for _, t, _ in listing[:3]]
        body_snippet = resp.text[:300].replace('\n', ' ')
        diagnostics.append({
            'page': page_num,
            'http_status': resp.status_code,
            'body_len': len(resp.text),
            'final_url': resp.url,
            'listing_count': len(listing),
            'sample_titles': sample_titles,
            'body_head': body_snippet,
        })
        log.info(f"page {page_num}: http={resp.status_code} len={len(resp.text)} "
                 f"final_url={resp.url} listings={len(listing)}")
        if not listing:
            log.info(f"page {page_num} 에서 게시글 없음, 중단")
            break

        for wr_id, title, post_url in listing:
            listing_match = is_seminar_post(title)
            truncated = (not listing_match) and is_truncated_listing_title(title)
            if not listing_match and not truncated:
                continue

            cached = known.get(wr_id) or {}
            prev_status = cached.get('status')
            is_new = not cached
            is_terminal = prev_status in ('approved', 'rejected')

            # 종착 상태 글은 상세 페이지를 다시 fetch 하지 않되, 저장된 풀 제목은
            # 최신 파서로 다시 읽어 과거의 누락 날짜도 다음 새로고침 때 복구한다.
            if is_terminal:
                if listing_match:
                    seminar_matched += 1
                cached_title = cached.get('title') or title
                cached_fallback_year = fallback_year
                for cached_date in (cached.get('dates') or []):
                    try:
                        cached_fallback_year = date.fromisoformat(
                            str(cached_date)[:10]
                        ).year
                        break
                    except (TypeError, ValueError):
                        continue
                parsed_dates = [
                    item.isoformat()
                    for item in parse_dates_from_title(
                        cached_title, cached_fallback_year
                    )
                ]
                parsed_room = get_room_from_title(cached_title)
                parsed_club = extract_club_name(cached_title) or cached.get('club_name')
                old_dates = sorted(str(item)[:10] for item in (cached.get('dates') or []))
                if (parsed_dates and parsed_dates != old_dates) or (
                        parsed_room and parsed_room != cached.get('room')) or (
                        parsed_club and parsed_club != cached.get('club_name')):
                    upserts.append({
                        'wr_id': wr_id,
                        'title': cached_title[:500],
                        'club_name': parsed_club or '알 수 없음',
                        'room': parsed_room,
                        'dates': parsed_dates or old_dates,
                        'status': prev_status,
                        'post_url': cached.get('post_url') or post_url,
                        'last_checked_at': now_iso,
                    })
                    reparsed_terminal += 1
                skipped_terminal += 1
                continue
            if not is_new and not recheck_pending:
                if listing_match:
                    seminar_matched += 1
                continue

            # 상세 페이지 fetch — status 판정용. 잘린 글이면 풀 제목 복원도 함께.
            detail_text = None
            try:
                detail = fetch_with_challenge(session, post_url, timeout=20)
                detail_text = detail.text
            except requests.RequestException as e:
                log.debug(f"상세 fetch 실패 wr_id={wr_id}: {e}")

            effective_title = title
            if detail_text:
                subj = parse_subject_from_detail(detail_text)
                if subj:
                    effective_title = subj

            if not is_seminar_post(effective_title):
                # 잘림 후보였지만 실제로는 세미나실 글이 아니었음.
                continue
            seminar_matched += 1

            if detail_text:
                status = parse_status_from_detail(detail_text)
            else:
                status = prev_status or 'pending'

            dates = parse_dates_from_title(effective_title, fallback_year)
            room = get_room_from_title(effective_title)
            club = extract_club_name(effective_title) or '알 수 없음'

            row = {
                'wr_id': wr_id,
                'title': effective_title[:500],
                'club_name': club,
                'room': room,
                'dates': [d.isoformat() for d in dates],
                'status': status,
                'post_url': post_url,
                'last_checked_at': now_iso,
            }
            if is_new:
                row['discovered_at'] = now_iso
                new_count += 1
            else:
                rechecked_count += 1

            upserts.append(row)
            log.info(f"  {'NEW' if is_new else 'CHK'} wr_id={wr_id} [{club}] "
                     f"{room or '?'} {[d.isoformat() for d in dates]} → {status}")

    # 신규 row(discovered_at 포함) 와 재확인 row(discovered_at 미포함) 를
    # 별도 배치로 나눠 upsert. 한 배치 내 키가 동일해야 PostgREST 가
    # 누락 컬럼을 NULL 로 패딩하지 않는다. (NOT NULL 위반 방지)
    new_rows = [r for r in upserts if 'discovered_at' in r]
    recheck_rows = [r for r in upserts if 'discovered_at' not in r]
    try:
        if new_rows:
            supabase.table('seminar_room_posts') \
                .upsert(new_rows, on_conflict='wr_id').execute()
        if recheck_rows:
            supabase.table('seminar_room_posts') \
                .upsert(recheck_rows, on_conflict='wr_id').execute()
    except Exception as e:
        log.error(f"upsert 실패: {e}")
        raise

    return {
        'new': new_count,
        'rechecked': rechecked_count,
        'skipped_terminal': skipped_terminal,
        'reparsed_terminal': reparsed_terminal,
        'pages_scanned': pages_scanned,
        'total_listed': total_listed,
        'seminar_matched': seminar_matched,
        'diagnostics': diagnostics,
    }
