import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from topic_lifecycle import topic_event_deadline, topic_event_is_expired, topic_event_is_open


ROOT = Path(__file__).resolve().parents[1]


class TopicLifecycleTest(unittest.TestCase):
    def test_standalone_event_closes_after_its_meeting_date(self):
        event = {"meeting_date": "2026-08-13", "is_active": True}
        self.assertEqual(topic_event_deadline(event), date(2026, 8, 14))
        self.assertFalse(topic_event_is_expired(event, today=date(2026, 8, 13)))
        self.assertTrue(topic_event_is_expired(event, today=date(2026, 8, 14)))
        self.assertFalse(topic_event_is_open(event, today=date(2026, 8, 14)))

    def test_shared_questions_remain_open_through_following_monday(self):
        event = {"meeting_date": "2026-08-13", "seminar_week_id": "week-1", "is_active": True,
                 "session_dates": ["2026-08-13", "2026-08-17"]}
        self.assertEqual(topic_event_deadline(event), date(2026, 8, 18))
        self.assertTrue(topic_event_is_open(event, today=date(2026, 8, 17)))
        self.assertFalse(topic_event_is_open(event, today=date(2026, 8, 18)))

    def test_session_link_has_its_own_deadline_without_changing_shared_pool(self):
        event = {"meeting_date": "2026-08-13", "session_dates": ["2026-08-13", "2026-08-17"],
                 "submission_meeting_date": "2026-08-13"}
        self.assertEqual(topic_event_deadline(event), date(2026, 8, 14))

    def test_midnight_is_korean_time_not_utc(self):
        event = {"meeting_date": "2026-08-13", "is_active": True}
        self.assertTrue(topic_event_is_open(event, datetime(2026, 8, 13, 14, 59, 59, tzinfo=timezone.utc)))
        self.assertFalse(topic_event_is_open(event, datetime(2026, 8, 13, 15, 0, tzinfo=timezone.utc)))

    def test_shared_legacy_row_without_linked_sessions_uses_following_monday(self):
        event = {"meeting_date": "2026-08-13", "seminar_week_id": "week-1"}
        self.assertEqual(topic_event_deadline(event), date(2026, 8, 18))

    def test_manual_close_remains_closed_before_deadline(self):
        event = {"meeting_date": "2026-08-13", "is_active": False}
        self.assertFalse(topic_event_is_open(event, today=date(2026, 8, 14)))

    def test_app_checks_deadline_on_page_load_and_submission(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("def _auto_close_topic_events", source)
        self.assertIn("event_data = _topic_event_for_submission([event_data], request.args.get('session_id'))", source)
        self.assertGreaterEqual(source.count("해당 세미나 날짜가 지나 발제문 제출이 마감되었습니다."), 2)
        self.assertIn("자동 마감되어 다시 열 수 없습니다.", source)


if __name__ == "__main__":
    unittest.main()
