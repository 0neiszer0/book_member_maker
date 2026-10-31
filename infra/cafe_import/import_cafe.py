"""Move the read-only Naver cafe archive into the site boards.

Default is a dry run that only reads the archive and prints counts. Writing needs
--apply plus SUPABASE_URL / SUPABASE_SERVICE_KEY in the environment, and it records
every created row and storage object in --state so --rollback can undo exactly that.

Rules (decided with the president, 2026-10-31):
- 발제문/일지/후기 -> seminar-reviews with [발제문]/[일지]/[후기] prefixes and the
  matching history_id; 벽돌책 -> brick-book-reviews; 자유게시판 + 커리큘럼 책 추천
  ([책 추천]) -> free; 책크메이트/정규모임/친목활동 -> officer-only cafe-photo-review.
- 공지사항, 신입모집, 회칙, 회계장부, 총회 회의록 are never imported.
- Author is the '카페 보관' system account; the text keeps only "N기 회원".
- Member names and 학번 are removed from titles and bodies; comments are dropped.
- Images go through board_content.prepare_image (WebP, EXIF stripped). Images of
  public posts are held back until officers review them (--public-images attach).
- PDF/HWP/audio attachments are not uploaded; the post lists them by name and the
  originals stay in the officers' archive copy.
"""
import argparse
import csv
import io
import json
import re
import subprocess
import sys
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

KST = timezone(timedelta(hours=9))
SYSTEM_SOCIAL_ID = 'system:cafe-archive'
REVIEW_BOARD = 'cafe-photo-review'
SEMINAR_BOARD = 'seminar-reviews'
BOARD_RULES = {
    '4': (SEMINAR_BOARD, '[발제문]'),
    '5': (SEMINAR_BOARD, '[일지]'),
    '18': (SEMINAR_BOARD, '[후기]'),
    '22': ('brick-book-reviews', ''),
    '16': ('free', ''),
    '17': ('free', '[책 추천]'),
    '21': (REVIEW_BOARD, '[책크메이트]'),
    '11': (REVIEW_BOARD, '[정규모임]'),
    '12': (REVIEW_BOARD, '[친목활동]'),
}
# 벽돌책 글은 원래 이름·학번을 공개하고 모집하므로 작성자를 그대로 둔다 (회장 결정 2026-10-31).
PUBLIC_AUTHOR_BOARDS = {'22'}
SKIP_BOARDS = {'14': '공지사항', '9': '신입모집', '1': '회칙', '13': '회계장부', '23': '총회 회의록'}
# Posts that are templates or lists of people rather than club writing.
SKIP_POSTS = {('18', '책 제목'): '후기 양식 예시', ('4', '커리큘럼 발제자 정리'): '발제자 명단'}
IMAGE_EXT = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
CHROME = re.compile(r'^(구독 1:1 채팅|댓글알림|클린봇|URL 복사|댓글 \d+ URL 복사|첨부파일 모아보기 \d+|조회 \d+|\d+|기|-|\[|\])$')
STOP = re.compile(r'^(등록순 최신순|클린봇|댓글을 남겨보세요|등록)$')
DATE_LINE = re.compile(r'^\d{4}\.\d{2}\.\d{2}\. \d{2}:\d{2}$')


def norm(text):
    return re.sub(r'[^0-9A-Za-z가-힣]', '', text or '').lower()


def read_meta(path):
    meta = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        key, _, value = line.partition(':')
        meta[key.strip()] = value.strip()
    return meta


def cohort(author):
    match = re.match(r'^\s*(\d{1,2})\s*기', author or '')
    if match and 1 <= int(match.group(1)) <= 19:
        return f'{int(match.group(1))}기 회원'
    return '기수 미상 회원'


def public_byline(author):
    # '6기김윤일' / '6 기 김윤일' -> '6기 김윤일'
    return re.sub(r'^\s*(\d{1,2})\s*기\s*', r'\1기 ', author or '').strip() or '작성자 미상'


def person_names(rows):
    names = set()
    for row in rows:
        name = re.sub(r'^\s*\d{1,2}\s*[기시]\s*', '', row['author'] or '').strip()
        if re.fullmatch(r'[가-힣]{2,4}', name):
            names.add(name)
    return sorted(names, key=len, reverse=True)


def redact(text, names):
    text = re.sub(r'\b\d{2}\s*학번', '', text)
    for name in names:
        text = text.replace(name, '○○○')
    return re.sub(r'[ \t]{2,}', ' ', text)


def pdf_text(pdf):
    result = subprocess.run(['pdftotext', '-enc', 'UTF-8', str(pdf), '-'], capture_output=True, check=True)
    return result.stdout.decode('utf-8', 'replace')


def wrapped_at_space(previous, following):
    # Browser print wraps Korean mid-word, so guess from word endings and particles.
    if previous[-1] in '.,?!)"\'':
        return True
    return previous[-1] in '는은을를고며서다요게면데지' and following[0] not in '은는이가을를의에도만와과로나하'


def clean_body(raw, attachments):
    lines = [line.rstrip() for line in raw.replace('\f', '\n').splitlines()]
    start = next((i for i, line in enumerate(lines) if re.fullmatch(r'조회 \d+', line.strip())), None)
    if start is None:
        start = next((i for i, line in enumerate(lines) if DATE_LINE.match(line.strip())), -1)
    body, names = [], {a.strip() for a in attachments if a.strip()}
    for line in lines[start + 1:]:
        stripped = line.strip()
        if STOP.match(stripped):
            break
        if CHROME.match(stripped) or stripped in names or any(n.endswith(stripped) and len(stripped) > 3 for n in names):
            continue
        body.append(stripped)
    width = max((len(line) for line in body), default=0)
    merged = []
    for line in body:
        if merged and merged[-1] and line and width >= 40 and len(merged[-1]) >= width - 3:
            joiner = ' ' if wrapped_at_space(merged[-1], line) else ''
            merged[-1] = merged[-1] + joiner + line
        else:
            merged.append(line)
    text = '\n'.join(merged)
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def review_title(title, names):
    match = re.search(r'[\[<『](.+?)[\]>』]', title)
    book = match.group(1).strip() if match else ''
    rest = title[match.end():] if match else title
    extra = re.match(r'\s*(외\s*\d+\s*편)', rest)
    if extra:
        book = f'{book} {extra.group(1)}'
    if '후기 모음' in title:
        return f'{book} 발제자 후기 모음'.strip(), book
    if not book:
        cleaned = redact(title, names)
        cleaned = re.sub(r'\S+(학과|학부|전공|과)\b', '', cleaned)
        book = re.sub(r'\s+', ' ', cleaned.replace('○○○', '')).strip()
    return book, book


def session_date(title, posted):
    full = re.search(r'(\d{2})\s*\.\s*(\d{2})\s*\.\s*(\d{2})', title)
    if full:
        return date(2000 + int(full.group(1)), int(full.group(2)), int(full.group(3)))
    full = re.search(r'(20\d{2})(\d{2})(\d{2})', title)
    if full:
        return date(int(full.group(1)), int(full.group(2)), int(full.group(3)))
    short = re.match(r'^\s*(\d{2})(\d{2})(?!\d)', title)
    if short:
        month, day = int(short.group(1)), int(short.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            year = posted.year - (1 if month > posted.month + 1 else 0)
            return date(year, month, day)
    return None


def same_book(key, history_key):
    if not history_key:
        return None  # session exists but its book title was never filled in
    head = lambda value: re.split(r'외\d|외', value)[0]
    return key in history_key or history_key in key or head(key)[:3] == head(history_key)[:3]


def match_history(history, title_date, book, posted):
    if title_date:
        near = [h for h in history if abs((h['date'] - title_date).days) <= 1]
        if near:
            return min(near, key=lambda h: abs((h['date'] - title_date).days))['id']
    key = norm(book)
    if len(key) < 2:
        return None
    window = [h for h in history if -7 <= (posted - h['date']).days <= 21]
    named = [h for h in window if same_book(key, h['key'])]
    if named:
        return min(named, key=lambda h: abs((posted - h['date']).days))['id']
    blank = [h for h in window if same_book(key, h['key']) is None and h['date'] <= posted]
    if blank and not any(h['key'] for h in window if 0 <= (posted - h['date']).days < (posted - max(blank, key=lambda b: b['date'])['date']).days):
        return max(blank, key=lambda h: h['date'])['id']
    return None


def load_history(path):
    if not path:
        return []
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    rows = data.get('history', data) if isinstance(data, dict) else data
    return [{'id': r['id'], 'date': date.fromisoformat(r['date']), 'key': norm(r.get('book_title'))}
            for r in rows if r.get('date')]


def build_plan(archive, history, public_images):
    index = list(csv.DictReader((archive / 'index.csv').open(encoding='utf-8')))
    names = person_names(index)
    plan, skipped = [], Counter()
    for row in index:
        menu, article = row['menuid'], row['articleid']
        if menu in SKIP_BOARDS:
            skipped[f"제외 게시판: {SKIP_BOARDS[menu]}"] += 1
            continue
        if menu not in BOARD_RULES or row.get('status') != 'ok':
            skipped['규칙 없음/수집 실패'] += 1
            continue
        reason = next((why for (m, needle), why in SKIP_POSTS.items() if m == menu and needle in row['title']), None)
        if reason:
            skipped[reason] += 1
            continue
        folder = archive / 'raw' / menu / article
        meta = read_meta(folder / 'meta.txt')
        attachments = [a for a in (meta.get('attachments') or '').split(';') if a.strip()]
        posted = datetime.strptime(meta['posted'], '%Y.%m.%d. %H:%M').replace(tzinfo=KST)
        slug, prefix = BOARD_RULES[menu]
        public_author = menu in PUBLIC_AUTHOR_BOARDS
        if menu == '18':
            title_core, book = review_title(row['title'], names)
        else:
            title_core = row['title'].strip() if public_author else redact(row['title'], names).replace('○○○', '').strip()
            book = title_core
        title = f'{prefix} {title_core}'.strip()[:200]
        body = clean_body(pdf_text(folder / 'page.pdf'), attachments)
        body = body if public_author else redact(body, names)
        images = sorted(p for p in folder.rglob('*') if p.suffix.lower() in IMAGE_EXT)
        files = [a for a in attachments if Path(a).suffix.lower() not in IMAGE_EXT]
        hidden_images = bool(images) and slug != REVIEW_BOARD and public_images == 'hold'
        byline = f'작성: {public_byline(row["author"])}' if public_author else cohort(row['author'])
        parts = [f"카페에서 옮긴 글 · {byline} · {posted:%Y.%m.%d} 작성", '', body or '(본문 없음)']
        if files:
            parts += ['', '카페 원본 첨부파일 (운영진 보관본):'] + [f'- {f if public_author else redact(f, names)}' for f in files]
        if hidden_images:
            parts += ['', f'카페 원본 사진 {len(images)}장은 운영진 확인 후 올립니다.']
        history_id = None
        if slug == SEMINAR_BOARD:
            history_id = match_history(history, session_date(row['title'], posted.date()), book, posted.date())
        plan.append({
            'source': f'{menu}/{article}', 'board': slug, 'title': title, 'content': '\n'.join(parts)[:50000],
            'created_at': posted.isoformat(), 'history_id': history_id,
            'images': [] if hidden_images else [str(p) for p in images], 'held_images': len(images) if hidden_images else 0,
            'files': len(files), 'unknown_cohort': not public_author and cohort(row['author']).startswith('기수 미상'),
        })
    return plan, skipped


def summarize(plan, skipped, history):
    by_board = Counter(item['board'] for item in plan)
    print('== 옮길 글')
    for board, count in sorted(by_board.items()):
        print(f'  {board}: {count}')
    seminar = [i for i in plan if i['board'] == SEMINAR_BOARD]
    for prefix in ('[발제문]', '[일지]', '[후기]'):
        group = [i for i in seminar if i['title'].startswith(prefix)]
        matched = sum(1 for i in group if i['history_id'])
        print(f'  {SEMINAR_BOARD} {prefix}: {len(group)}개, 회차 연결 {matched}개' + ('' if history else ' (회차 목록 없음)'))
    print('== 제외')
    for reason, count in sorted(skipped.items()):
        print(f'  {reason}: {count}')
    print('== 이미지')
    print(f"  올릴 이미지: {sum(len(i['images']) for i in plan)}장")
    print(f"  공개 게시판 보류(검토 후 --public-images attach): {sum(i['held_images'] for i in plan)}장")
    print(f"  올리지 않는 PDF·HWP·음성 첨부: {sum(i['files'] for i in plan)}개")
    print(f"== 기수 미상 작성자: {sum(i['unknown_cohort'] for i in plan)}개")


def apply(plan, state_path):
    import os
    from supabase import create_client
    from board_content import prepare_image
    db = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    state = json.loads(state_path.read_text()) if state_path.exists() else {'posts': {}, 'objects': []}
    state.setdefault('images_done', [])
    boards = {b['slug']: b['id'] for b in db.table('boards').select('id,slug').execute().data}
    missing = {i['board'] for i in plan} - set(boards)
    author = db.table('members').select('id').eq('social_id', SYSTEM_SOCIAL_ID).execute().data
    if missing or not author:
        raise SystemExit(f'준비 SQL을 먼저 적용하세요. 없는 게시판={sorted(missing)} 시스템 계정={bool(author)}')
    author_id = author[0]['id']
    save = lambda: state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    for item in plan:
        post_id = state['posts'].get(item['source'])
        if not post_id:
            post_id = db.table('posts').insert({
                'board_id': boards[item['board']], 'author_id': author_id, 'title': item['title'],
                'content': item['content'], 'content_format': 'plain', 'history_id': item['history_id'],
                'created_at': item['created_at'], 'updated_at': item['created_at'],
            }).execute().data[0]['id']
            state['posts'][item['source']] = post_id
            save()
        elif item['images'] and item['source'] not in state['images_done']:
            # Second run after officers reviewed the held photos: drop the "later" note.
            db.table('posts').update({'content': item['content']}).eq('id', post_id).execute()
        if item['images'] and item['source'] not in state['images_done']:
            attach_images(db, prepare_image, post_id, item['images'], state, state_path)
            state['images_done'].append(item['source'])
            save()
    print(f"완료: 글 {len(state['posts'])}개, 이미지 {len(state['objects'])}개 (state={state_path})")


def convert_image(path):
    """Shrink oversized camera originals first, then run the site's own WebP/EXIF-strip step."""
    from PIL import Image, ImageOps
    from board_content import prepare_image
    raw = Path(path).read_bytes()
    try:
        return prepare_image(io.BytesIO(raw))
    except ValueError:
        pass
    Image.MAX_IMAGE_PIXELS = 200_000_000
    with Image.open(io.BytesIO(raw)) as image:
        image = ImageOps.exif_transpose(image).convert('RGB')
        image.thumbnail((2400, 2400))
        small = io.BytesIO()
        image.save(small, format='PNG')
    Image.MAX_IMAGE_PIXELS = 89_478_485
    return prepare_image(io.BytesIO(small.getvalue()))


def check_images(plan):
    ok, failed = 0, []
    for item in plan:
        for image in item['images']:
            try:
                convert_image(image)
                ok += 1
            except Exception as exc:  # report every unreadable file instead of stopping
                failed.append((image, str(exc)))
    print(f'== 이미지 변환 확인: 성공 {ok}장, 실패 {len(failed)}장')
    for image, error in failed:
        print(f'  {image}: {error}')


def attach_images(db, prepare_image, post_id, images, state, state_path):
    for order, image in enumerate(images):
        try:
            content, mime, ext = convert_image(image)
        except ValueError as exc:
            print(f'  이미지 건너뜀 {Path(image).name}: {exc}')
            continue
        path = f'posts/{post_id}/{uuid.uuid4().hex}.{ext}'
        db.storage.from_('board-uploads').upload(path, content, {'content-type': mime, 'upsert': 'false'})
        state['objects'].append(path)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1))
        db.table('post_attachments').insert({'post_id': post_id, 'storage_path': path, 'original_name': f'cafe-{order + 1}.{ext}',
                                             'mime_type': mime, 'byte_size': len(content), 'display_order': order}).execute()


def rollback(state_path):
    import os
    from supabase import create_client
    db = create_client(os.environ['SUPABASE_URL'], os.environ['SUPABASE_SERVICE_KEY'])
    state = json.loads(state_path.read_text())
    objects, posts = state['objects'], list(state['posts'].values())
    for start in range(0, len(objects), 100):
        db.storage.from_('board-uploads').remove(objects[start:start + 100])
    for start in range(0, len(posts), 100):
        db.table('posts').delete().in_('id', posts[start:start + 100]).execute()
    print(f'되돌림: 글 {len(posts)}개, 이미지 {len(objects)}개 삭제')


def export_plan(plan, out):
    """Write plan.json plus already converted WebP files so the VM needs no pdftotext or archive."""
    out.mkdir(parents=True, exist_ok=False)
    exported = []
    for item in plan:
        images = []
        for order, image in enumerate(item['images']):
            content, _, ext = convert_image(image)
            target = out / 'images' / item['source'].replace('/', '-') / f'{order + 1:02d}.{ext}'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            images.append(str(target.relative_to(out)))
        exported.append(item | {'images': images})
    (out / 'plan.json').write_text(json.dumps(exported, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'내보냄: {out} (글 {len(exported)}개, 이미지 {sum(len(i["images"]) for i in exported)}장)')


def load_export(folder):
    plan = json.loads((folder / 'plan.json').read_text(encoding='utf-8'))
    for item in plan:
        item['images'] = [str(folder / image) for image in item['images']]
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--archive', type=Path, help='카페 백업 폴더 (index.csv, raw/)')
    parser.add_argument('--export', type=Path, help='plan.json과 변환된 이미지를 쓸 새 폴더')
    parser.add_argument('--from-export', type=Path, help='--export로 만든 폴더에서 읽는다 (VM용)')
    parser.add_argument('--history-json', help='history 목록(JSON: [{id,date,book_title}] 또는 {"history": [...]})')
    parser.add_argument('--public-images', choices=('hold', 'attach'), default='hold')
    parser.add_argument('--preview', type=Path, help='제목·본문 미리보기 JSONL을 쓸 경로 (운영진 검토용)')
    parser.add_argument('--state', type=Path, default=Path('cafe_import_state.json'))
    parser.add_argument('--check-images', action='store_true', help='dry-run에서 이미지 변환까지 시험한다')
    parser.add_argument('--apply', action='store_true', help='실제로 쓴다 (기본은 dry-run)')
    parser.add_argument('--rollback', action='store_true', help='--state에 기록된 글과 이미지를 지운다')
    args = parser.parse_args(argv)
    if args.rollback:
        return rollback(args.state)
    if args.from_export:
        plan = load_export(args.from_export)
        summarize(plan, Counter(), [None])
    else:
        if not args.archive:
            parser.error('--archive 또는 --from-export가 필요합니다')
        history = load_history(args.history_json)
        plan, skipped = build_plan(args.archive, history, args.public_images)
        summarize(plan, skipped, history)
    if args.export:
        export_plan(plan, args.export)
    if args.preview:
        with args.preview.open('w', encoding='utf-8') as out:
            for item in plan:
                out.write(json.dumps({k: v for k, v in item.items() if k != 'images'} | {'images': len(item['images'])},
                                     ensure_ascii=False) + '\n')
    if args.check_images:
        check_images(plan)
    if args.apply:
        apply(plan, args.state)
    else:
        print('dry-run: 아무것도 쓰지 않았습니다.')


if __name__ == '__main__':
    main()
