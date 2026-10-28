import base64
import importlib
import os
import unittest
from datetime import date, datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from PIL import Image
from werkzeug.datastructures import FileStorage
from board_content import clean_html, render_content, prepare_image
from lms_learning import personal_attendance_columns, historical_courses, member_weeks, link_legacy_histories
from member_notifications import subscription_payload
from notification_delivery import collect_items, reconcile, deliver
from testing._fake_supabase import FakeSupabase, FakeQuery
from testing.test_home_overview import fixture


class WriteQuery(FakeQuery):
    def upsert(self, payload, on_conflict=None, ignore_duplicates=False):
        self.payload = payload
        self.conflict = (on_conflict or 'id').split(',')
        self.ignore_duplicates = ignore_duplicates
        self.operation = 'upsert'
        return self

    def execute(self):
        if self.operation == 'insert':
            import uuid
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            saved = [dict(id=str(uuid.uuid4()), created_at='2026-10-28T00:00:00+00:00', **row) if 'id' not in row else dict(row) for row in items]
            self.client.rows.setdefault(self.table_name, []).extend(saved)
            return SimpleNamespace(data=saved)
        if self.operation == 'upsert':
            rows = self.client.rows.setdefault(self.table_name, [])
            match = next((r for r in rows if all(r.get(k) == self.payload.get(k) for k in self.conflict)), None)
            if match is not None:
                if not self.ignore_duplicates:
                    match.update(self.payload)
            else:
                import uuid
                match = {'id': str(uuid.uuid4()), 'created_at': '2026-10-28T00:00:00+00:00', **self.payload}
                rows.append(match)
            return SimpleNamespace(data=[dict(match)])
        return super().execute()


class WriteDB(FakeSupabase):
    def table(self, name):
        return WriteQuery(self, name)


def subscription():
    key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    encode = lambda b: base64.urlsafe_b64encode(b).decode().rstrip('=')
    return {'endpoint': 'https://fcm.googleapis.com/fcm/send/fixture', 'keys': {'p256dh': encode(key), 'auth': encode(b'a'*16)}}


class LearningTests(unittest.TestCase):
    def test_legacy_link_is_read_only_and_never_guesses_ambiguous_dates(self):
        histories=[{'date':'2026-10-20','book_title':'책'}, {'date':'2026-10-21','book_title':'다른 책'}]
        sessions=[{'id':'s','meeting_date':'2026-10-20','book_title':'책'}, {'id':'wrong','meeting_date':'2026-10-21','book_title':'책'}]
        linked=link_legacy_histories(histories,sessions)
        self.assertEqual(linked[0]['seminar_session_id'],'s');self.assertNotIn('seminar_session_id',histories[0])
        self.assertNotIn('seminar_session_id',linked[1])
        self.assertNotIn('seminar_session_id',link_legacy_histories(histories,sessions+[dict(sessions[0],id='second')])[0])

    def test_full_attendance_preserves_pending_future_absent_and_legacy(self):
        weeks = [{'id':'w','week_start':'2026-10-19','book_title':'책'}]
        report = {'matrix': {1:{'legacy':True}}, 'columns': [
            {'key':'legacy','date':'2026-10-01','title':'과거','kind':'seminar'},
            {'key':'confirmed','date':'2026-10-08','kind':'seminar','title':'책','day_type':'thu','session_id':'done'}],
            'sessions':[{'id':'pending','meeting_date':'2026-10-20','seminar_week_id':'w'},
                        {'id':'future','meeting_date':'2026-11-03','seminar_week_id':'w'},
                        {'id':'done','meeting_date':'2026-10-08'},
                        {'id':'off','meeting_date':'2026-10-22','is_active':False}]}
        rows=personal_attendance_columns(report,1,weeks,date(2026,10,28))
        self.assertEqual([r['status'] for r in rows],['출석','결석','확정 대기','예정'])
        self.assertEqual(len(rows),4)

    def test_break_week_removed_without_renumbering(self):
        rows=fixture()
        rows['seminar_weeks']=[{'id':str(i),'term_id':'term','week_start':f'2026-10-{i:02d}', 'book_title':None if i in (5,6) else '책','note':'중간고사 휴회' if i in (5,6) else ''} for i in range(1,8)]
        _,_,weeks,_=member_weeks(FakeSupabase(rows),'term')
        self.assertEqual([w['week_number'] for w in weeks],[1,2,3,4,7])

    def test_historical_participation_requires_confirmed_unambiguous_identity(self):
        members=[{'id':1,'name':'동명'},{'id':2,'name':'동명'}]
        histories=[{'id':'one','date':'2025-04-01','present':['동명'],'attendance_confirmed_at':'ok'},
                   {'id':'two','date':'2025-04-02','present':['동명'],'actual_member_ids':[1],'attendance_confirmed_at':'ok'},
                   {'date':'2024-04-02','actual_member_ids':[1]}]
        courses=historical_courses(members,histories,[],1,date(2026,10,28))
        self.assertEqual(len(courses),1);self.assertEqual(courses[0]['count'],1)


class BoardContentTests(unittest.TestCase):
    def test_sanitized_rich_text_and_escaped_legacy(self):
        value='<h2>제목</h2><script>alert(1)</script><a href="javascript:alert(1)" onclick="x">링크</a><img src=x onerror=x>'
        html=clean_html(value)
        self.assertIn('<h2>제목</h2>',html)
        self.assertNotIn('javascript:',html);self.assertNotIn('<script',html);self.assertNotIn('<img',html)
        self.assertNotIn('<h2>',str(render_content('<h2>old</h2>','plain')))

    def test_rejects_masquerading_file_and_downsizes_real_image(self):
        with self.assertRaises(ValueError):
            prepare_image(FileStorage(stream=BytesIO(b'<svg onload=evil>'),filename='fake.png',content_type='image/png'))
        data=BytesIO();Image.new('RGB',(3000,20)).save(data,format='JPEG');data.seek(0)
        value,mime,ext=prepare_image(FileStorage(stream=data,filename='picture.jpg'))
        self.assertEqual(mime,'image/webp');self.assertEqual(ext,'webp')
        with Image.open(BytesIO(value)) as image:self.assertEqual(image.width,2400);self.assertFalse(image.getexif())


class PushTests(unittest.TestCase):
    def test_review_task_only_for_confirmed_participant_and_resolves_after_submit(self):
        rows=fixture();rows['seminar_review_forms']=[dict(id='review',seminar_session_id='past',share_token='token',status='open')]
        db=WriteDB(rows);now=datetime(2026,9,23,tzinfo=timezone.utc)
        items,_=collect_items(db,now)
        reviews=[r for r in items if r['event_key']=='review:review']
        self.assertEqual([r['member_id'] for r in reviews],[1])
        db.rows['seminar_reviews']=[dict(id='submitted',form_id='review',member_id=1,deleted_at=None)]
        items,_=collect_items(db,now)
        self.assertFalse(any(r['event_key']=='review:review' for r in items))

    def test_subscription_rejects_internal_and_lookalike_hosts_and_bad_keys(self):
        value=subscription();self.assertEqual(len(subscription_payload(value)['endpoint_hash']),64)
        for endpoint in ['http://fcm.googleapis.com/x','https://127.0.0.1/x','https://fcm.googleapis.com.evil.test/x','https://fcm.googleapis.com@evil.test/x','https://fcm.googleapis.com:444/x']:
            with self.subTest(endpoint=endpoint),self.assertRaises(ValueError):subscription_payload({**value,'endpoint':endpoint})
        with self.assertRaises(ValueError):subscription_payload({**value,'keys':{'auth':'x','p256dh':'x'}})

    def test_inbox_reconcile_deduplicates_and_resolves_completed_activity(self):
        db=WriteDB();now=datetime(2026,10,28,tzinfo=timezone.utc)
        item={'member_id':1,'event_key':'topic:e','title':'발제문','body':'작성','url':'/seminars'}
        reconcile(db,[item],now);db.rows['member_inbox'][0]['read_at']='read'
        reconcile(db,[item],now)
        self.assertEqual(len(db.rows['member_inbox']),1);self.assertEqual(db.rows['member_inbox'][0]['read_at'],'read')
        reconcile(db,[],now);self.assertIsNotNone(db.rows['member_inbox'][0]['resolved_at'])

    def test_worker_submission_matching_respects_owner(self):
        rows=fixture();rows['topic_submissions']=[{'event_id':'event','member_id':2,'student_id':'202600001'}]
        items,_=collect_items(WriteDB(rows),datetime(2026,9,23,tzinfo=timezone.utc))
        self.assertTrue(any(r['member_id']==1 and r['event_key']=='topic:event' for r in items))
        self.assertFalse(any(r['member_id']==2 and r['event_key']=='topic:event' for r in items))

    def test_success_not_resent_and_revoked_subscription_removed(self):
        sub={**subscription_payload(subscription()),'member_id':1}
        db=WriteDB({'member_inbox':[{'id':'n','member_id':1,'url':'/seminars','created_at':'2026-10-28','resolved_at':None,'read_at':None}], 'push_subscriptions':[sub]})
        now=datetime(2026,10,28,tzinfo=timezone.utc)
        with patch.dict(os.environ,{'WEB_PUSH_PRIVATE_KEY':'fixture'}):
            with patch('pywebpush.webpush') as send:
                self.assertEqual(deliver(db,[{'id':1}],now,send)['sent'],1)
                self.assertEqual(deliver(db,[{'id':1}],now,send)['sent'],0)
                self.assertEqual(send.call_count,1)
            db.rows['push_deliveries']=[]
            error=RuntimeError();error.response=SimpleNamespace(status_code=410)
            with patch('pywebpush.webpush',side_effect=error) as send:
                deliver(db,[{'id':1}],now,send)
                self.assertEqual(db.rows['push_subscriptions'],[])


class MemberRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module=importlib.import_module('app');cls.module.app.config['TESTING']=True

    def setUp(self):
        self.db=WriteDB(fixture());self.original=self.module.supabase;self.module.supabase=self.db
        self.client=self.module.app.test_client()
        with self.client.session_transaction() as state:state.update(user_id=1,user_role='member',sensitive_csrf='csrf')

    def tearDown(self):self.module.supabase=self.original

    def test_signed_out_notification_preserves_action_through_login(self):
        from urllib.parse import urlsplit, parse_qs
        with self.client.session_transaction() as state:state.clear()
        response=self.client.get('/seminars/topics/event')
        self.assertEqual(response.status_code,302)
        self.assertEqual(parse_qs(urlsplit(response.location).query)['next'],['/seminars/topics/event'])

    def test_closed_topic_readable_without_identity_or_writes(self):
        self.db.rows['topic_events'][0]['is_active']=False
        self.db.rows['topic_submissions']=[{'event_id':'event','created_at':'x','student_id':'secret-student','author_name':'secret-name','topics':[{'topic':'읽을 발제','reference':'인용','page':'32'}]}]
        response=self.client.get('/seminars/topics/event')
        self.assertEqual(response.status_code,200)
        self.assertIn('읽을 발제',response.get_data(as_text=True));self.assertNotIn('secret-',response.get_data(as_text=True))
        self.assertFalse(any(c[0] in ('update','delete','insert') for c in self.db.calls))

    def test_cross_member_read_and_preferences_are_scoped_and_csrf_checked(self):
        self.db.rows['member_inbox']=[{'id':'other','member_id':2,'title':'private','body':'private','url':'/seminars','created_at':'x'}]
        self.assertEqual(self.client.get('/api/member-notifications').get_json()['items'],[])
        self.assertEqual(self.client.post('/api/member-notifications/other/read').status_code,403)
        self.client.post('/api/member-notifications/other/read',headers={'X-App-CSRF':'csrf'})
        self.assertNotIn('read_at',self.db.rows['member_inbox'][0])
        self.assertEqual(self.client.post('/api/my/courses/visibility',json={'key':'k','hidden':True},headers={'X-App-CSRF':'csrf'}).status_code,200)
        self.assertEqual(self.db.rows['member_preferences'][0]['member_id'],1)

    def test_revoked_account_cannot_read_or_enroll(self):
        self.db.rows['members'][0]['account_status']='pending'
        self.assertEqual(self.client.get('/api/member-notifications').status_code,403)

    def test_push_enrollment_is_csrf_protected_owned_and_never_returns_private_key(self):
        with patch.dict(os.environ,{'WEB_PUSH_PRIVATE_KEY':'private-fixture','WEB_PUSH_PUBLIC_KEY':'public-fixture'}):
            self.assertEqual(self.client.post('/api/push/subscription',json=subscription()).status_code,403)
            self.assertEqual(self.client.post('/api/push/subscription',json=subscription(),headers={'X-App-CSRF':'csrf'}).status_code,200)
            self.assertEqual(self.db.rows['push_subscriptions'][0]['member_id'],1)
            self.assertNotIn('private-fixture',self.client.get('/api/push/config').get_data(as_text=True))


if __name__=='__main__':unittest.main()
