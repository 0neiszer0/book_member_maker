import unittest
from datetime import date
from pathlib import Path

from topic_lifecycle import topic_event_deadline, topic_event_is_expired, topic_event_is_open


ROOT = Path(__file__).resolve().parents[1]


class TopicLifecycleTest(unittest.TestCase):
    def test_event_closes_on_the_seventh_day_after_meeting(self):
        event = {"meeting_date": "2026-08-13", "is_active": True}
        self.assertEqual(topic_event_deadline(event), date(2026, 8, 20))
        self.assertFalse(topic_event_is_expired(event, today=date(2026, 8, 19)))
        self.assertTrue(topic_event_is_expired(event, today=date(2026, 8, 20)))
        self.assertFalse(topic_event_is_open(event, today=date(2026, 8, 20)))

    def test_manual_close_remains_closed_before_deadline(self):
        event = {"meeting_date": "2026-08-13", "is_active": False}
        self.assertFalse(topic_event_is_open(event, today=date(2026, 8, 14)))

    def test_app_checks_deadline_on_page_load_and_submission(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("def _auto_close_topic_events", source)
        self.assertIn("event_data = _auto_close_topic_events([event_data])[0]", source)
        self.assertGreaterEqual(source.count("모임일부터 7일이 지나 발제문 제출이 마감되었습니다."), 2)
        self.assertIn("자동 마감되어 다시 열 수 없습니다.", source)


if __name__ == "__main__":
    unittest.main()
