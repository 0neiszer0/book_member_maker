"""Kakao roster matching and confirmed, weekly-deduplicated term attendance."""
from collections import defaultdict
from datetime import date
import re
from seminar_cycle import cycle_monday


def match_roster_rows(rows, members):
    """Match IDs/names exactly. Never choose the first ambiguous member."""
    by_name, by_student = defaultdict(list), defaultdict(list)
    for member in members:
        by_name[str(member.get('name') or '').strip()].append(member)
        if member.get('student_id'):
            by_student[str(member['student_id']).strip()].append(member)
    matched, issues, seen = [], [], set()
    for index, row in enumerate(rows, 1):
        parts = [str(cell).strip() for cell in row if str(cell).strip()]
        if not parts or all(p.lower() in {'이름', '성명', '학번', 'name', 'student_id'} for p in parts):
            continue
        student_ids = [p for p in parts if re.fullmatch(r'\d{6,15}', p)]
        names = [p for p in parts if p not in student_ids]
        candidates = by_student.get(student_ids[0], []) if len(student_ids) == 1 else []
        if student_ids:
            if names:
                candidates = [m for m in candidates if str(m.get('name') or '').strip() in names]
        elif len(names) == 1:
            candidates = by_name.get(names[0], [])
        reason = None
        if len(candidates) > 1:
            reason = '동명이인 또는 중복 학번: 이름과 학번을 함께 확인해주세요.'
        elif not candidates:
            reason = '일치하는 회원이 없습니다. 이름과 학번을 확인해주세요.'
        elif int(candidates[0]['id']) in seen:
            reason = '명단에 같은 회원이 두 번 있습니다.'
        if reason:
            issues.append({'line': index, 'input': ' · '.join(parts), 'reason': reason})
        else:
            member = candidates[0]
            seen.add(int(member['id']))
            matched.append(member)
    return matched, issues


def parse_roster_text(text):
    if len(text) > 100000:
        raise ValueError('명단은 100,000자 이하로 입력해주세요.')
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows = []
    for line in lines:
        # A comma-only list is also convenient for Kakao copied names.
        if ',' in line and not re.search(r'\d{6,15}', line):
            rows.extend([[part.strip()] for part in line.split(',') if part.strip()])
        else:
            rows.append(re.split(r'[\t,| ]+', line))
    if len(rows) > 2000:
        raise ValueError('명단은 한 번에 2,000명까지 확인할 수 있습니다.')
    return rows


def expected_member_ids(mode, selected_ids, eligible_ids):
    selected, eligible = {int(i) for i in selected_ids}, {int(i) for i in eligible_ids}
    if selected - eligible:
        raise ValueError('기본 대상 명단에 없는 회원이 포함되어 있습니다.')
    if mode not in {'attendance', 'absence'}:
        raise ValueError('참석/불참 명단 구분이 올바르지 않습니다.')
    return sorted(eligible - selected if mode == 'absence' else selected)


def build_term_attendance(members, histories, sessions, events, event_attendees,
                          brick_sessions, brick_members, start, end, minimum=3, today=None, no_shows=()):
    """Count confirmed actual attendance only; Thu and following Mon are one credit.

    Matrix keeps individual dates, while credit keys are weekly for seminars.
    Legacy names are matched only if unique; ambiguous history names are surfaced.
    """
    today = today or date.today()
    today_iso = today.isoformat()
    minimum = max(1, min(50, int(minimum or 3)))
    by_id = {int(m['id']): m for m in members}
    by_name = defaultdict(list)
    for member in members:
        by_name[member.get('name')].append(int(member['id']))
    session_by_id = {str(s['id']): s for s in sessions}
    excluded_by_session = defaultdict(set)
    for row in no_shows:
        if not row.get('cancelled_at'):
            excluded_by_session[str(row['session_id'])].add(int(row['member_id']))
    matrix, credits = defaultdict(dict), defaultdict(lambda: defaultdict(set))
    columns, warnings = [], set()
    seen_columns = set()

    def in_range(day):
        return bool(day and start <= str(day)[:10] <= end and str(day)[:10] <= today_iso)

    def add(key, day, title, kind, ids, credit_key):
        if not in_range(day) or key in seen_columns:
            return
        seen_columns.add(key)
        columns.append({'key': key, 'date': str(day)[:10], 'title': title, 'kind': kind})
        for mid in set(ids):
            if mid not in by_id:
                continue
            matrix[mid][key] = True
            credits[mid][kind].add(credit_key)

    for item in sessions:
        if item.get('attendance_confirmed_at') and item.get('actual_member_ids') is not None:
            day = item.get('meeting_date')
            if in_range(day):
                add('session:' + str(item['id']), day, item.get('book_title') or '세미나', 'seminar',
                    [int(i) for i in item['actual_member_ids'] if int(i) not in excluded_by_session[str(item['id'])]], 'week:' + cycle_monday(day).isoformat())
    for row in histories:
        if not row.get('attendance_confirmed_at') or not in_range(row.get('date')):
            continue
        linked = session_by_id.get(str(row.get('seminar_session_id')), {})
        if linked.get('attendance_confirmed_at') and linked.get('actual_member_ids') is not None:
            continue
        excluded = excluded_by_session[str(row.get('seminar_session_id'))]
        ids = [int(mid) for mid in row.get('actual_member_ids') or [] if int(mid) not in excluded]
        if row.get('actual_member_ids') is None:
            for name in row.get('present') or []:
                matches = by_name.get(name, [])
                if len(matches) == 1 and matches[0] not in excluded:
                    ids.append(matches[0])
                elif len(matches) > 1:
                    warnings.add(f'{name}: 과거 기록의 동명이인을 확인해주세요.')
        add('history:' + str(row['id']), row['date'], row.get('book_title') or '세미나', 'seminar',
            ids, 'week:' + cycle_monday(row['date']).isoformat())
    event_ids = defaultdict(list)
    for row in event_attendees:
        event_ids[str(row['event_id'])].append(int(row['member_id']))
    for event in events:
        if event.get('counts_toward_attendance') and event.get('attendance_confirmed_at'):
            add('event:' + str(event['id']), event.get('event_date'), event.get('name') or 'OT',
                'ot', event_ids[str(event['id'])], 'event:' + str(event['id']))
    brick_ids = defaultdict(list)
    for row in brick_members:
        brick_ids[str(row['session_id'])].append(int(row['member_id']))
    for item in brick_sessions:
        add('brick:' + str(item['id']), item.get('meeting_date'),
            (item.get('brick_books') or {}).get('title') or '벽돌책', 'brick',
            brick_ids[str(item['id'])], 'brick:' + str(item['id']))
    columns.sort(key=lambda c: (c['date'], c['key']))
    rows = []
    for member in members:
        mid = int(member['id'])
        counts = {kind: len(credits[mid][kind]) for kind in ('seminar', 'ot', 'brick')}
        total = sum(counts.values())
        rows.append({**member, 'counts': counts, 'total': total, 'shortage': max(0, minimum - total),
                     'last_date': max((c['date'] for c in columns if matrix[mid].get(c['key'])), default='')})
    return {'members': rows, 'columns': columns, 'matrix': dict(matrix),
            'minimum': minimum, 'warnings': sorted(warnings)}
