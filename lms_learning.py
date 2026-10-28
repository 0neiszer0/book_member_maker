"""Member-facing curriculum and attendance views; never mutate attendance on reads."""
from datetime import date


def is_break_week(week):
    note = str(week.get('note') or '')
    return not week.get('book_title') and any(word in note for word in ('휴회', '시험기간', '중간고사', '기말고사'))


def link_legacy_histories(histories, sessions):
    """Read-only association: exact date, unique candidate, no conflicting book."""
    linked = []
    for history in histories:
        history = dict(history)
        if not history.get('seminar_session_id'):
            matches = [s for s in sessions if s.get('meeting_date') == str(history.get('date') or '')[:10]]
            if len(matches) == 1:
                target = matches[0]
                a, b = str(history.get('book_title') or '').strip(), str(target.get('book_title') or '').strip()
                if not a or not b or a == b:
                    history['seminar_session_id'] = target['id']
        linked.append(history)
    return linked


def member_weeks(db, term_id=None):
    from home_overview import load_seminar_context
    context = load_seminar_context(db, term_id)
    sessions = context.get('all_sessions', context['sessions'])
    ids = [s['id'] for s in sessions]
    histories = db.table('history').select('id,seminar_session_id,attendance_confirmed_at').in_('seminar_session_id', ids).execute().data or [] if ids else []
    history_map = {h['seminar_session_id']: h for h in histories}
    review_forms = db.table('seminar_review_forms').select('id,seminar_session_id,share_token').in_('seminar_session_id', ids).execute().data or [] if ids else []
    review_map = {r['seminar_session_id']: r for r in review_forms}
    sessions = [s for s in sessions if s.get('is_active', True) or s['id'] in history_map or s.get('attendance_confirmed_at')]
    weeks = []
    for number, week in enumerate(sorted(context['weeks'].values(), key=lambda w: w['week_start']), 1):
        week = {**week, 'week_number': number}
        week['sessions'] = [{**s, 'history': history_map.get(s['id']), 'review_form': review_map.get(s['id']),
                             'is_past': s['meeting_date'] < context['today'].isoformat()}
                            for s in sessions if s.get('seminar_week_id') == week['id']]
        week['topic_event'] = context['topics'].get(week['id'])
        week['is_past'] = bool(week['sessions']) and all(s['is_past'] for s in week['sessions'])
        if is_break_week(week) and not any(s.get('history') for s in week['sessions']):
            continue
        weeks.append(week)
    return context['terms'], context['term'], weeks, []


def personal_attendance_columns(report, member_id, weeks, today):
    """Keep confirmed absences, pending/future sessions and unmatched legacy records."""
    matrix = report.get('matrix', {}).get(member_id, {})
    columns = [dict(c, status='출석' if matrix.get(c['key']) else ('결석' if c.get('day_type') == 'thu' else '참여 기록 없음')) for c in report.get('columns', [])]
    seen = {str(c.get('session_id')) for c in columns if c.get('session_id')}
    week_map = {str(w['id']): (i, w) for i, w in enumerate(weeks, 1)}
    for s in report.get('sessions', []):
        if str(s['id']) in seen or not s.get('is_active', True):
            continue
        _, week = week_map.get(str(s.get('seminar_week_id')), (None, {}))
        if is_break_week(week):
            continue
        columns.append({'key': 'session:' + str(s['id']), 'session_id': s['id'],
                        'week_id': s.get('seminar_week_id'), 'day_type': s.get('day_type'),
                        'date': s['meeting_date'], 'title': week.get('book_title') or s.get('book_title') or '도서 미정',
                        'kind': 'seminar', 'status': '예정' if s['meeting_date'] > today.isoformat() else '확정 대기'})
    columns.sort(key=lambda c: (c['date'], c['key']))
    for c in columns:
        number, week = week_map.get(str(c.get('week_id')), (None, {}))
        c.update(week_number=number, week_span=1)
        if week.get('book_title'):
            c['title'] = week['book_title']
        if c['kind'] == 'brick' and matrix.get(c['key']):
            c['status'] = '참석 기록'
    previous = None
    for c in columns:
        if previous and c.get('week_number') and c.get('week_id') == previous.get('week_id'):
            previous['week_span'] += 1
            c['week_span'] = 0
        else:
            previous = c
    return columns


def historical_courses(members, histories, terms, member_id, today):
    """Infer participation from confirmed evidence, never synthesize membership rows."""
    from collections import Counter
    names = Counter(m.get('name') for m in members)
    member = next((m for m in members if str(m['id']) == str(member_id)), {})
    found = {}
    for h in histories:
        day = str(h.get('date') or '')[:10]
        try:
            parsed = date.fromisoformat(day)
        except ValueError:
            continue
        if not h.get('attendance_confirmed_at') or parsed > today:
            continue
        ids = h.get('actual_member_ids')
        attended = str(member_id) in {str(i) for i in ids} if ids is not None else (
            names[member.get('name')] == 1 and member.get('name') in (h.get('present') or []))
        if not attended:
            continue
        term = next((t for t in terms if t['start_date'] <= day <= t['end_date']), None)
        if term and term['end_date'] >= today.isoformat():
            continue
        if term:
            key, name, term_id = str(term['id']), term['name'], term['id']
        else:
            half = 1 if parsed.month < 7 else 2
            key, name, term_id = f'legacy-{parsed.year}-{half}', f'{parsed.year}년 {half}학기 기록', None
        course = found.setdefault(key, {'key': key, 'name': name, 'term_id': term_id, 'count': 0, 'last_date': day})
        course['count'] += 1
        course['last_date'] = max(course['last_date'], day)
    return sorted(found.values(), key=lambda c: c['last_date'], reverse=True)
