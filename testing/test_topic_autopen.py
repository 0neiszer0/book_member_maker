import unittest
from datetime import date
from unittest.mock import patch

from testing._fake_supabase import FakeSupabase
from topic_autopen import open_due_topic_events
from topic_lifecycle import topic_event_deadline


def rows():
    return {
        'seminar_weeks': [dict(id='w1', book_title='다음 책', book_author='저자'),
                          dict(id='w2', book_title='그다음 책')],
        'seminar_sessions': [
            dict(id='thu', seminar_week_id='w1', meeting_date='2026-11-05', is_active=True),
            dict(id='mon', seminar_week_id='w1', meeting_date='2026-11-09', is_active=True),
            dict(id='thu2', seminar_week_id='w2', meeting_date='2026-11-12', is_active=True)],
        'topic_events': [],
    }


class TopicAutoOpenTests(unittest.TestCase):
    def test_link_opens_wednesday_after_previous_deadline_until_tuesday(self):
        for today, expected in [(date(2026, 10, 27), []), (date(2026, 10, 28), ['w1']),
                                (date(2026, 11, 3), ['w1']), (date(2026, 11, 4), ['w2'])]:
            with self.subTest(today=today):
                db = FakeSupabase(rows())
                open_due_topic_events(db, today)
                self.assertEqual([e['seminar_week_id'] for e in db.rows['topic_events']], expected)

    def test_created_event_matches_manual_link_and_is_not_duplicated(self):
        db = FakeSupabase(rows())
        open_due_topic_events(db, date(2026, 10, 28))
        open_due_topic_events(db, date(2026, 10, 29))
        self.assertEqual(len(db.rows['topic_events']), 1)
        event = db.rows['topic_events'][0]
        self.assertEqual((event['seminar_session_id'], event['meeting_date'], event['book_title'], event['book_author']),
                         ('thu', '2026-11-05', '다음 책', '저자'))
        self.assertTrue(event['is_active']); self.assertTrue(event['share_token'])
        self.assertEqual(topic_event_deadline(dict(event, session_dates=['2026-11-05', '2026-11-09'])), date(2026, 11, 3))

    def test_existing_closed_untitled_or_hidden_weeks_are_left_alone(self):
        for change in ('closed', 'untitled', 'hidden'):
            with self.subTest(change=change):
                db = FakeSupabase(rows())
                if change == 'closed':
                    db.rows['topic_events'] = [dict(id='manual', seminar_week_id='w1', is_active=False)]
                if change == 'untitled':
                    db.rows['seminar_weeks'][0]['book_title'] = '  '
                if change == 'hidden':
                    for s in db.rows['seminar_sessions'][:2]:
                        s['is_active'] = False
                open_due_topic_events(db, date(2026, 10, 28))
                self.assertEqual(len([e for e in db.rows['topic_events'] if e.get('id') != 'manual']), 0)

    def test_database_failure_never_breaks_the_caller(self):
        db = FakeSupabase(rows())
        with patch.object(db, 'table', side_effect=RuntimeError('offline')):
            self.assertEqual(open_due_topic_events(db, date(2026, 10, 28)), [])

    def test_monday_extra_seminar_pairs_with_preceding_thursday(self):
        # 목(11/5) → 다음 월(11/9) 추가 세미나는 같은 책·같은 마감(11/3 화 23:59).
        self.assertEqual(topic_event_deadline({'submission_meeting_date': '2026-11-09'}), date(2026, 11, 3))
        self.assertEqual(topic_event_deadline({'meeting_date': '2026-11-09'}), date(2026, 11, 3))
        self.assertEqual(topic_event_deadline({'session_dates': ['2026-11-09']}), date(2026, 11, 3))
        # 다음 주 목요일(11/12)과 묶이지 않는다.
        self.assertNotEqual(topic_event_deadline({'meeting_date': '2026-11-09'}), date(2026, 11, 10))


if __name__ == '__main__':
    unittest.main()
