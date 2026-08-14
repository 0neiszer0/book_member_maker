"""발제문 수집 이벤트의 자동 마감 기준."""

from datetime import date, datetime, timedelta


TOPIC_OPEN_DAYS = 7


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
    meeting_date = _meeting_date((event or {}).get("meeting_date"))
    return meeting_date + timedelta(days=TOPIC_OPEN_DAYS) if meeting_date else None


def topic_event_is_expired(event, today=None):
    """모임일부터 7일째 되는 날 00시부터 마감으로 본다."""
    deadline = topic_event_deadline(event)
    return bool(deadline and (today or date.today()) >= deadline)


def topic_event_is_open(event, today=None):
    return bool((event or {}).get("is_active")) and not topic_event_is_expired(event, today=today)
