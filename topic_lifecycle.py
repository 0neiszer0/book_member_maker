"""발제문 수집 이벤트의 자동 마감 기준."""

from datetime import date, datetime, timedelta, timezone

from seminar_cycle import cycle_monday


KST = timezone(timedelta(hours=9))


def _meeting_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def topic_event_deadline(event):
    """공유 질문은 마지막 회차, 회차 지정 링크는 그 회차 다음 날 마감한다."""
    event = event or {}
    meeting_date = _meeting_date(event.get("submission_meeting_date"))
    if not meeting_date:
        session_dates = [_meeting_date(value) for value in event.get("session_dates", [])]
        session_dates = [value for value in session_dates if value]
        meeting_date = max(session_dates) if session_dates else _meeting_date(event.get("meeting_date"))
        # 연결 회차가 없는 과거 주차도 목→월 공유 발제문으로 해석한다.
        if not session_dates and meeting_date and event.get("seminar_week_id"):
            meeting_date = cycle_monday(meeting_date)
    return meeting_date + timedelta(days=1) if meeting_date else None


def topic_event_is_expired(event, today=None):
    """한국시간 기준 해당 회차 다음 날 00시부터 마감으로 본다."""
    deadline = topic_event_deadline(event)
    current = today if today is not None else datetime.now(KST)
    if isinstance(current, datetime):
        current = current.astimezone(KST).date() if current.tzinfo else current.date()
    return bool(deadline and current >= deadline)


def topic_event_is_open(event, today=None):
    return bool((event or {}).get("is_active")) and not topic_event_is_expired(event, today=today)
