"""발제문 링크 자동 열기.

다음 세미나의 발제문 링크는 직전 마감(화요일 23:59)이 지난 수요일 00:00(한국시간)부터
자동으로 열린다. 즉 세미나 주차의 마감 화요일 6일 전 수요일부터 그 화요일 23:59까지
접수한다. 이미 이벤트가 있는 주차(직접 연 링크, 수동으로 닫은 링크 포함)는 건드리지
않으며, 도서 제목이 없는 주차와 회차가 모두 숨겨진 주차는 열지 않는다.
스키마 변경 없이 기존 topic_events 행을 같은 형식으로 만든다(주차별 unique index가
중복 생성을 막는다).
"""
import logging
import uuid
from datetime import timedelta

from topic_lifecycle import topic_event_deadline

log = logging.getLogger(__name__)
OPEN_DAYS_BEFORE_DEADLINE = 6  # 화요일 마감 6일 전 = 직전 주 수요일 00:00


def topic_open_date(deadline):
    return deadline - timedelta(days=OPEN_DAYS_BEFORE_DEADLINE) if deadline else None


def due_weeks(weeks, sessions, existing_week_ids, today):
    """오늘 자동으로 열어야 할 (주차, 첫 회차) 목록."""
    by_week = {}
    for row in sessions:
        if row.get('seminar_week_id') and row.get('meeting_date'):
            by_week.setdefault(row['seminar_week_id'], []).append(row)
    due = []
    for week in weeks:
        rows = sorted(by_week.get(week['id'], []), key=lambda r: str(r['meeting_date']))
        if (str(week['id']) in existing_week_ids or not rows or not (week.get('book_title') or '').strip()
                or not any(r.get('is_active', True) is not False for r in rows)):
            continue
        deadline = topic_event_deadline({'session_dates': [r['meeting_date'] for r in rows]})
        if deadline and topic_open_date(deadline) <= today <= deadline:
            due.append((week, rows[0]))
    return due


def open_due_topic_events(db, today):
    """열 때가 된 주차의 발제문 링크를 만든다. 실패해도 화면·알림은 계속 동작한다."""
    try:
        start = today.isoformat()
        end = (today + timedelta(days=OPEN_DAYS_BEFORE_DEADLINE + 8)).isoformat()
        sessions = db.table('seminar_sessions').select('id,seminar_week_id,meeting_date,is_active') \
            .gte('meeting_date', start).lte('meeting_date', end).execute().data or []
        week_ids = sorted({s['seminar_week_id'] for s in sessions if s.get('seminar_week_id')})
        if not week_ids:
            return []
        # 마감 기준은 그 주차의 모든 회차이므로 기간 밖 회차까지 다시 읽는다.
        sessions = db.table('seminar_sessions').select('id,seminar_week_id,meeting_date,is_active') \
            .in_('seminar_week_id', week_ids).execute().data or []
        weeks = db.table('seminar_weeks').select('id,book_title,book_author').in_('id', week_ids).execute().data or []
        existing = db.table('topic_events').select('seminar_week_id').in_('seminar_week_id', week_ids).execute().data or []
        created = []
        for week, first in due_weeks(weeks, sessions, {str(r['seminar_week_id']) for r in existing}, today):
            payload = {
                'meeting_date': str(first['meeting_date'])[:10],
                'book_title': week['book_title'].strip(),
                'book_author': (week.get('book_author') or '').strip() or None,
                'seminar_session_id': first['id'],
                'seminar_week_id': week['id'],
                'share_token': str(uuid.uuid4()),
                'is_active': True,
            }
            try:
                created.extend(db.table('topic_events').insert(payload).execute().data or [])
            except Exception:
                log.info('Topic event for week %s was opened concurrently or rejected', week['id'])
        return created
    except Exception:
        log.exception('Automatic topic event opening failed')
        return []
