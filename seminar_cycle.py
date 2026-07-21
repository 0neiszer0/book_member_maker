"""목요일 본 세미나와 다음 월요일 추가 세미나를 한 운영 묶음으로 계산한다."""

from datetime import date, datetime, timedelta


def cycle_monday(value):
    """회차가 속한 운영 묶음의 기준 월요일을 반환한다.

    목요일은 바로 다음 월요일과 묶이고, 월요일은 그 날짜 자체가 기준일이다.
    다른 요일이 들어오면 날짜 이후 가장 가까운 월요일을 사용한다.
    """
    seminar_date = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    if isinstance(seminar_date, datetime):
        seminar_date = seminar_date.date()
    days_until_monday = (7 - seminar_date.weekday()) % 7
    return seminar_date + timedelta(days=days_until_monday)


def next_seminar_cycle(today):
    """현재 진행 중이거나 다음에 시작할 목→월 운영 묶음을 반환한다."""
    if today.weekday() in {3, 4, 5, 6, 0}:
        thursday = today - timedelta(days=(today.weekday() - 3) % 7)
    else:
        thursday = today + timedelta(days=3 - today.weekday())
    return [thursday, thursday + timedelta(days=4)]
