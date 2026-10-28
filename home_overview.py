"""Read-only home summaries. Never turn a failed lookup into an empty count."""
from datetime import date, datetime, timedelta, timezone
from topic_lifecycle import topic_event_deadline, topic_event_is_open
from attendance_workflow import attendance_is_confirmed, confirmed_history_session_ids

KST = timezone(timedelta(hours=9))


def date_label(value):
    try:
        day = date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return str(value or '')
    return f"{day.isoformat()} ({'월화수목금토일'[day.weekday()]})"


def load_seminar_context(db, term_id=None, today=None):
    today = today or datetime.now(KST).date()
    terms = db.table('seminar_terms').select('*').order('start_date', desc=True).execute().data or []
    term = (next((t for t in terms if str(t['id']) == str(term_id)), None)
            or next((t for t in terms if t['start_date'] <= today.isoformat() <= t['end_date']), None)
            or next((t for t in terms if t.get('is_active')), terms[0] if terms else None))
    result = {'terms': terms, 'term': term, 'sessions': [], 'weeks': {}, 'topics': {}}
    if not term:
        return result
    sessions = db.table('seminar_sessions').select('*').eq('term_id', term['id']).order('meeting_date').execute().data or []
    sessions = [s for s in sessions if s.get('is_active', True)]
    weeks = db.table('seminar_weeks').select('*').eq('term_id', term['id']).execute().data or []
    week_ids = [w['id'] for w in weeks]
    topics = db.table('topic_events').select('id,seminar_week_id,seminar_session_id,meeting_date,is_active,share_token,created_at').in_('seminar_week_id', week_ids).order('created_at', desc=True).execute().data or [] if week_ids else []
    topics_by_week = {}
    for event in topics:
        event['session_dates'] = [s['meeting_date'] for s in sessions if s.get('seminar_week_id') == event.get('seminar_week_id')]
        event['open'] = topic_event_is_open(event, today=today)
        deadline = topic_event_deadline(event)
        event['deadline_label'] = date_label(deadline) + ' 00:00' if deadline else ''
        topics_by_week.setdefault(event['seminar_week_id'], event)
    result.update(sessions=sessions, weeks={w['id']: w for w in weeks}, topics=topics_by_week)
    return result


def session_summary(context, target):
    if not target:
        return None
    week = context['weeks'].get(target.get('seminar_week_id'), {})
    return {**target, 'book_title': week.get('book_title') or target.get('book_title') or '도서 미정',
            'kind_label': '본 세미나' if target.get('day_type') == 'thu' else '추가 세미나',
            'topic': context['topics'].get(target.get('seminar_week_id'))}


def decorate_topic_submission_states(db, member_id, events, today=None):
    """Attach personal, read-only state without loading any submission text."""
    today = today or datetime.now(KST).date()
    ids = [event['id'] for event in events]
    submitted = set()
    if member_id is not None and ids:
        rows = db.table('topic_submissions').select('id,event_id').in_('event_id', ids).eq('member_id', member_id).execute().data or []
        submitted.update(row['event_id'] for row in rows)
        members = db.table('members').select('student_id').eq('id', member_id).limit(1).execute().data or []
        sid = str((members[0] if members else {}).get('student_id') or '').strip()
        if sid:
            rows = db.table('topic_submissions').select('id,event_id').in_('event_id', ids).eq('student_id', sid).is_('member_id', 'null').execute().data or []
            submitted.update(row['event_id'] for row in rows)
    for event in events:
        event['submitted'] = event['id'] in submitted
        event['open'] = topic_event_is_open(event, today=today)
        deadline = topic_event_deadline(event)
        event['deadline_label'] = date_label(deadline) + ' 00:00' if deadline else ''
        event['status'] = 'submitted' if event['submitted'] else ('open' if event['open'] else 'closed')
        event['status_label'] = '제출 완료' if event['submitted'] else ('미제출 · 접수 중' if event['open'] else '미제출 · 접수 마감')
    return events


def member_seminar_summary(db, member_id, today=None):
    today = today or datetime.now(KST).date()
    context = load_seminar_context(db, today=today)
    events = decorate_topic_submission_states(db, member_id, list(context['topics'].values()), today)
    target = next((s for s in context['sessions'] if s['meeting_date'] >= today.isoformat()), None)
    seminar = session_summary(context, target)
    tasks = []
    for event in events:
        if event['open'] and not event['submitted']:
            week = context['weeks'].get(event.get('seminar_week_id'), {})
            tasks.append({**event, 'book_title': week.get('book_title') or '도서 미정'})
    tasks.sort(key=lambda event: (str(topic_event_deadline(event) or date.max), str(event['id'])))
    return {'term': context['term'], 'seminar': seminar,
            'submitted': bool(seminar and seminar['topic'] and seminar['topic']['submitted']),
            'tasks': tasks, 'curriculum': list(context['weeks'].values())}


def operations_summary(db, term_id=None, session_id=None, today=None):
    today = today or datetime.now(KST).date()
    context = load_seminar_context(db, term_id, today)
    sessions = context['sessions']
    target = next((s for s in sessions if str(s['id']) == str(session_id)), None)
    if not target:
        target = next((s for s in sessions if s['meeting_date'] >= today.isoformat()), sessions[-1] if sessions else None)
    ids = [s['id'] for s in sessions]
    histories = db.table('history').select('id,seminar_session_id,groups,attendance_confirmed_at').in_('seminar_session_id', ids).execute().data or [] if ids else []
    confirmed_sessions = confirmed_history_session_ids(histories)
    grouped_sessions = {h['seminar_session_id'] for h in histories if any(h.get('groups') or [])}
    result = {**context, 'selected': session_summary(context, target), 'tasks': [], 'pending_attendance': []}
    for item in sessions:
        if item['meeting_date'] < today.isoformat() and not attendance_is_confirmed(item, confirmed_sessions):
            result['pending_attendance'].append(session_summary(context, item))
    if target:
        title = result['selected']['book_title']
        event = result['selected']['topic']
        tasks = [
            {'key': 'book', 'label': '도서 입력', 'done': title != '도서 미정', 'action': '도서·사회자 편집'},
            {'key': 'moderator', 'label': '사회자 입력', 'done': bool(str(target.get('moderator_name') or '').strip()), 'action': '사회자 입력'},
            {'key': 'topics', 'label': '발제문 수집 준비', 'done': bool(event), 'action': '발제문 수집 열기'},
            {'key': 'roster', 'label': '카카오톡 참석·불참 명단 반영', 'done': bool(target.get('roster_updated_at')), 'action': '명단 반영'},
            {'key': 'groups', 'label': '조 편성 저장', 'done': target['id'] in grouped_sessions, 'action': '조 편성'},
        ]
        if target['meeting_date'] <= today.isoformat():
            tasks.append({'key': 'attendance', 'label': '실제 출석 확정', 'done': attendance_is_confirmed(target, confirmed_sessions), 'action': '출석 확정'})
        result['tasks'] = tasks
    return result
