import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from topic_lifecycle import KST, topic_event_close_at, topic_event_deadline, topic_event_is_expired, topic_event_is_open


ROOT = Path(__file__).resolve().parents[1]


class TopicLifecycleTest(unittest.TestCase):
    def test_thursday_seminar_closes_after_tuesday_of_the_same_week(self):
        event = {"meeting_date": "2026-08-13", "is_active": True}  # 목요일 18:30 세미나
        self.assertEqual(topic_event_deadline(event), date(2026, 8, 11))
        self.assertEqual(topic_event_close_at(event), datetime(2026, 8, 11, 23, 59, 59, tzinfo=KST))
        self.assertTrue(topic_event_is_open(event, today=date(2026, 8, 11)))
        self.assertTrue(topic_event_is_expired(event, today=date(2026, 8, 12)))
        self.assertFalse(topic_event_is_open(event, today=date(2026, 8, 13)))

    def test_shared_questions_with_monday_session_use_the_same_tuesday(self):
        event = {"meeting_date": "2026-08-13", "seminar_week_id": "week-1", "is_active": True,
                 "session_dates": ["2026-08-17", "2026-08-13"]}
        self.assertEqual(topic_event_deadline(event), date(2026, 8, 11))
        self.assertTrue(topic_event_is_open(event, today=date(2026, 8, 11)))
        self.assertFalse(topic_event_is_open(event, today=date(2026, 8, 12)))

    def test_session_links_for_thursday_and_monday_share_the_cycle_tuesday(self):
        for session_date in ("2026-08-13", "2026-08-17"):
            event = {"meeting_date": "2026-08-13", "session_dates": ["2026-08-13", "2026-08-17"],
                     "submission_meeting_date": session_date}
            self.assertEqual(topic_event_deadline(event), date(2026, 8, 11), session_date)

    def test_other_weekdays_never_close_after_the_meeting(self):
        expected = {"2026-08-10": "2026-08-04", "2026-08-11": "2026-08-04", "2026-08-12": "2026-08-11",
                    "2026-08-14": "2026-08-11", "2026-08-16": "2026-08-11"}
        for meeting, deadline in expected.items():
            self.assertEqual(topic_event_deadline({"meeting_date": meeting}), date.fromisoformat(deadline), meeting)
            self.assertLess(topic_event_deadline({"meeting_date": meeting}), date.fromisoformat(meeting))

    def test_cutoff_is_korean_time_not_utc(self):
        event = {"meeting_date": "2026-08-13", "is_active": True}
        self.assertTrue(topic_event_is_open(event, datetime(2026, 8, 11, 14, 59, 59, tzinfo=timezone.utc)))
        self.assertFalse(topic_event_is_open(event, datetime(2026, 8, 11, 15, 0, tzinfo=timezone.utc)))

    def test_shared_legacy_row_without_linked_sessions_uses_its_week_tuesday(self):
        event = {"meeting_date": "2026-08-13", "seminar_week_id": "week-1"}
        self.assertEqual(topic_event_deadline(event), date(2026, 8, 11))

    def test_manual_close_remains_closed_before_deadline(self):
        event = {"meeting_date": "2026-08-13", "is_active": False}
        self.assertFalse(topic_event_is_open(event, today=date(2026, 8, 10)))

    def test_app_checks_deadline_on_page_load_and_submission(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("def _auto_close_topic_events", source)
        self.assertIn("event_data = _topic_event_for_submission([event_data], request.args.get('session_id'))", source)
        self.assertGreaterEqual(source.count("발제문 제출 마감(세미나 주 화요일 23:59)이 지나 제출이 마감되었습니다."), 2)
        self.assertIn("‘추가 제출’ 버튼으로 며칠 더 열 수 있습니다.", source)


if __name__ == "__main__":
    unittest.main()
