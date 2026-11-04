"""발제문 수집 이벤트의 자동 마감 기준.

세미나는 목요일 18:30에 시작하고, 발제문은 그 주 화요일 23:59(한국시간)까지 받는다.
같은 주차의 월요일 추가 세미나도 목요일 본 세미나와 같은 발제문을 쓰므로 같은 마감을 따른다.
"""

from datetime import date, datetime, time, timedelta, timezone


KST = timezone(timedelta(hours=9))
DEADLINE_TIME = time(23, 59)
DEADLINE_LABEL = "23:59"


def _meeting_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def tuesday_before(value):
    """회차 날짜보다 앞선 가장 가까운 화요일(회차가 화요일이면 1주 전)."""
    return value - timedelta(days=(value.weekday() - 1) % 7 or 7)


def topic_event_deadline(event):
    """세미나 직전 화요일(이 날 23:59까지 접수)을 반환한다.

    공유 발제문은 연결 회차 중 가장 이른 회차(목요일 본 세미나), 회차 지정 링크는 그
    회차를 기준으로 한다. 목요일 세미나는 이틀 전 화요일, 같은 묶음의 다음 월요일
    추가 세미나도 같은 화요일이 된다.
    """
    event = event or {}
    meeting_date = _meeting_date(event.get("submission_meeting_date"))
    if not meeting_date:
        session_dates = [_meeting_date(value) for value in event.get("session_dates", [])]
        session_dates = [value for value in session_dates if value]
        meeting_date = min(session_dates) if session_dates else _meeting_date(event.get("meeting_date"))
    if not meeting_date:
        return None
    return tuesday_before(meeting_date)


def topic_event_late_until(event):
    """운영진이 연 추가 제출 마감(timezone 포함 datetime) 또는 None."""
    value = (event or {}).get("late_until")
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


def late_until_end_of_day(day):
    """추가 제출은 고른 날의 23:59:59(한국시간)까지 받는다."""
    return datetime.combine(day, time(23, 59, 59), KST)


def _current_date(today):
    current = today if today is not None else datetime.now(KST)
    if isinstance(current, datetime):
        current = current.astimezone(KST).date() if current.tzinfo else current.date()
    return current


def topic_event_close_at(event):
    """실제 마감 시각(추가 제출 기간이 더 늦으면 그 시각, 한국시간)."""
    deadline = topic_event_deadline(event)
    original = datetime.combine(deadline, time(23, 59, 59), KST) if deadline else None
    late = topic_event_late_until(event)
    if late and (original is None or late > original):
        return late
    return original


def topic_event_original_expired(event, today=None):
    """원래 마감(화요일 23:59)이 지났는지. 추가 제출 기간과 무관."""
    deadline = topic_event_deadline(event)
    return bool(deadline and _current_date(today) > deadline)


def topic_event_late_open(event, today=None):
    """원래 마감은 지났지만 추가 제출 기간 안인지."""
    late = topic_event_late_until(event)
    return bool(late and topic_event_original_expired(event, today)
                and _current_date(today) <= late.astimezone(KST).date())


def topic_event_is_expired(event, today=None):
    """한국시간 기준 마감 화요일이 지난 수요일 00시부터 마감으로 본다.

    운영진이 추가 제출 기간(late_until)을 열었다면 그 날짜가 끝날 때까지는 열려 있다.
    """
    if not topic_event_original_expired(event, today):
        return False
    return not topic_event_late_open(event, today)


def topic_event_is_open(event, today=None):
    return bool((event or {}).get("is_active")) and not topic_event_is_expired(event, today=today)
