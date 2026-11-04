import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from testing import test_topic_session_workflow as base
from topic_lifecycle import (topic_event_close_at, topic_event_is_expired, topic_event_is_open,
                             topic_event_late_open)

KST = timezone(timedelta(hours=9))
EVENT = {"meeting_date": "2026-08-13", "is_active": True}  # 원래 마감 2026-08-11(화) 23:59


class LateWindowLifecycleTests(unittest.TestCase):
    def test_late_until_keeps_event_open_through_that_day(self):
        event = dict(EVENT, late_until="2026-08-14T14:59:59+00:00")  # 08-14 23:59:59 KST
        self.assertFalse(topic_event_is_expired(event, today=date(2026, 8, 12)))
        self.assertTrue(topic_event_late_open(event, today=date(2026, 8, 14)))
        self.assertTrue(topic_event_is_open(event, today=date(2026, 8, 14)))
        self.assertTrue(topic_event_is_expired(event, today=date(2026, 8, 15)))
        self.assertEqual(topic_event_close_at(event).astimezone(KST),
                         datetime(2026, 8, 14, 23, 59, 59, tzinfo=KST))

    def test_without_late_window_original_rule_is_unchanged(self):
        self.assertTrue(topic_event_is_expired(EVENT, today=date(2026, 8, 12)))
        self.assertFalse(topic_event_late_open(EVENT, today=date(2026, 8, 10)))
        self.assertEqual(topic_event_close_at(EVENT).astimezone(KST).date(), date(2026, 8, 11))

    def test_late_window_before_deadline_is_not_late_yet(self):
        event = dict(EVENT, late_until="2026-08-14T14:59:59+00:00")
        self.assertFalse(topic_event_late_open(event, today=date(2026, 8, 10)))
        self.assertTrue(topic_event_is_open(event, today=date(2026, 8, 10)))


class LateWindowRouteTests(base.TopicSessionWorkflowTests):
    def setUp(self):
        super().setUp()
        with self.client.session_transaction() as s:
            s['sensitive_csrf'] = 'csrf'

    def late(self, body, clock=base.AfterDeadline):
        with patch.object(self.module, 'datetime', clock):
            return self.client.post('/api/admin/topic_events/event-1/late_window', json=body,
                                    headers={'X-App-CSRF': 'csrf'})

    def event(self):
        return self.fake.rows['topic_events'][0]

    def submit(self, clock, topic='늦은 질문', session_id='thu'):
        with patch.object(self.module, 'datetime', clock):
            return self.client.post('/api/topics/submit', json={
                'event_id': 'event-1', 'session_id': session_id, 'topics': [{'topic': topic}],
                'author_name': '늦은발제', 'department': '철학과', 'admission_year': '26', 'pin_code': '1234'})

    def test_reopens_closed_event_for_n_days_and_accepts_late_submission(self):
        self.submit(base.AfterDeadline)  # triggers auto-close
        self.assertFalse(self.event()['is_active'])
        res = self.late({'days': 3})
        self.assertEqual(res.status_code, 200, res.get_data(as_text=True))
        self.assertEqual(res.get_json()['late_until'], '2026-08-15')  # 오늘(08-12)+3
        self.assertTrue(self.event()['is_active'])
        with patch.object(self.module, 'datetime', base.AfterDeadline):
            page = self.client.get('/shared_topics?token=shared-token&session_id=thu')
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('추가 제출 기간입니다', html)
        self.assertIn('2026-08-15 23:59', html)
        self.assertIn('원래 마감: 2026-08-11 23:59', html)

    def test_before_deadline_extends_from_original_deadline(self):
        res = self.late({'days': 1}, clock=base.BeforeDeadline)
        self.assertEqual(res.get_json()['late_until'], '2026-08-12')

    def test_date_picker_and_validation(self):
        self.assertEqual(self.late({'until': '2026-08-20'}).get_json()['late_until'], '2026-08-20')
        self.assertEqual(self.late({'until': '2026-08-11'}).status_code, 400)  # not after original
        self.assertEqual(self.late({'until': '2027-01-01'}).status_code, 400)  # > 30 days
        self.assertEqual(self.late({'days': 0}).status_code, 400)
        self.assertEqual(self.late({'until': 'nope'}).status_code, 400)

    def test_close_early_after_deadline_closes_event(self):
        self.late({'days': 7})
        res = self.late({'action': 'close'})
        self.assertEqual(res.status_code, 200)
        self.assertIsNone(self.event()['late_until'])
        self.assertFalse(self.event()['is_active'])

    def test_original_deadline_record_is_unchanged(self):
        self.late({'days': 3})
        self.assertEqual(self.event()['meeting_date'], '2026-08-13')
        with patch.object(self.module, 'datetime', base.AfterDeadline):
            page = self.client.get('/admin/topics/event-1/view').get_data(as_text=True)
        self.assertIn('2026-08-11 23:59', page)
        self.assertIn('추가 제출 중', page)

    def test_late_submission_is_marked_for_officers(self):
        self.fake.rows['topic_submissions'][0]['created_at'] = '2026-08-12T03:00:00+00:00'
        self.late({'days': 3})
        with patch.object(self.module, 'datetime', base.AfterDeadline):
            page = self.client.get('/admin/topics/event-1/view').get_data(as_text=True)
        self.assertIn('>추가 제출</span>', page)

    def test_requires_admin(self):
        self.fake.rows['members'][0]['role'] = 'member'
        with self.client.session_transaction() as s:
            s['user_role'] = 'member'
        res = self.late({'days': 3})
        self.assertNotEqual(res.status_code, 200)
        self.assertIsNone(self.event().get('late_until'))


for _name in [n for n in dir(base.TopicSessionWorkflowTests) if n.startswith('test_')]:
    setattr(LateWindowRouteTests, _name, None)
del _name
