import importlib
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from club_room import booking_payload, edit_digest, public_booking
from testing._fake_supabase import FakeSupabase

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'room-tests-only')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'room-tests-only')


class RoomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')
        cls.module.app.config.update(TESTING=True, SECRET_KEY='room-tests-only')

    def setUp(self):
        self.identifier = str(uuid4())
        self.code = 'a' * 43
        self.row = dict(id=self.identifier, kind='regular', starts_at='2099-10-05T12:00:00+09:00',
                        ends_at='2099-10-05T14:00:00+09:00', representative='대표 공개',
                        participants=['대표 공개', '참여자 비공개'], purpose='목적 비공개', version=1,
                        cancelled_at=None, edit_digest=edit_digest(self.code, 'room-tests-only'), request_fingerprint='ip-private')
        self.db = FakeSupabase({'club_room_bookings': [self.row], 'members': [
            dict(id=1,role='officer',is_active=True,account_status='active',member_status='active'),
            dict(id=2,role='member',is_active=True,account_status='active',member_status='active')]})
        self.rpc_calls = []
        self.rpc_result = {'status':'success', 'booking':self.row}
        def rpc(name, args):
            self.rpc_calls.append((name,args))
            return SimpleNamespace(execute=lambda:SimpleNamespace(data=self.rpc_result))
        self.db.rpc = rpc
        self.db_patch = patch.object(self.module,'supabase',self.db)
        self.db_patch.start(); self.addCleanup(self.db_patch.stop)
        self.client = self.module.app.test_client()
        self.client.get('/club-room')
        with self.client.session_transaction() as state:
            self.csrf = state['room_csrf']
        self.body = dict(action='create', edit_code=self.code, kind='regular',
                         starts_at='2099-10-05T12:00', ends_at='2099-10-05T14:00',
                         representative='대표 공개', participants='참여자 비공개, 대표 공개', purpose='목적 비공개')

    def login(self, mid, role):
        with self.client.session_transaction() as state:
            state.update(user_id=mid,user_role=role)

    def post(self, body=None, csrf=True):
        return self.client.post('/api/club-room/bookings/'+self.identifier,json=body or self.body,
                                headers={'X-Room-CSRF':self.csrf} if csrf else {})

    def test_public_form_and_schedule_never_disclose_private_fields(self):
        html = self.client.get('/club-room').get_data(as_text=True)
        self.assertNotIn('id="cr-meeting"', html)
        self.assertNotIn('id="cr-staff-panel"', html)
        data = self.client.get('/api/club-room/schedule?date=2099-10-05')
        self.assertEqual(data.status_code,200)
        content = data.get_data(as_text=True)
        self.assertIn('대표 공개', data.json['bookings'][0]['representative'])
        for forbidden in ('participants','purpose','edit_digest','request_fingerprint','created_by'):
            self.assertNotIn(forbidden,content)
        self.assertEqual(data.headers['Cache-Control'],'no-store')
        self.row['kind'] = 'meeting'
        self.db.rows['club_room_bookings'][0]['kind'] = 'meeting'
        hidden = self.client.get('/api/club-room/schedule?date=2099-10-05').json['bookings'][0]
        self.assertEqual(set(hidden),{'kind','starts_at','ends_at'})
        self.assertEqual(hidden['kind'],'blocked')

    def test_csrf_anonymous_create_and_secret_redaction(self):
        self.assertEqual(self.post(csrf=False).status_code,403)
        response = self.post()
        self.assertEqual(response.status_code,200)
        sent = self.rpc_calls[-1][1]
        self.assertIsNone(sent['p_actor'])
        self.assertNotEqual(sent['p_digest'],self.code)
        self.assertFalse(sent['p_ack'])
        self.assertEqual(sent['p_payload']['participants'],['대표 공개','참여자 비공개'])
        self.assertNotIn('edit_digest',response.json['booking'])
        self.assertNotIn('request_fingerprint',response.json['booking'])

    def test_only_current_officers_can_create_and_manage_meetings(self):
        body = {**self.body,'kind':'meeting'}
        self.assertEqual(self.post(body).status_code,403)
        self.login(2,'officer')
        self.assertEqual(self.post(body).status_code,403, 'stale claimed role is not authority')
        self.assertEqual(self.client.get('/api/club-room/staff').status_code,403)
        self.login(1,'officer')
        self.assertIn('id="cr-meeting"',self.client.get('/club-room').get_data(as_text=True))
        self.assertEqual(self.post(body).status_code,200)
        self.assertEqual(self.rpc_calls[-1][1]['p_actor'],1)
        data = self.client.get('/api/club-room/staff?date=2099-10-05')
        self.assertEqual(data.status_code,200)
        self.assertIn('참여자 비공개', data.json['bookings'][0]['participants'])
        self.db.rows['members'][0]['is_active'] = False
        self.assertEqual(self.post(body).status_code,403)

    def test_manage_code_and_meeting_privacy(self):
        read = dict(action='read',edit_code='b'*43)
        self.assertEqual(self.post(read).status_code,403)
        read['edit_code']=self.code
        self.assertEqual(self.post(read).status_code,200)
        self.db.rows['club_room_bookings'][0]['kind']='meeting'
        self.assertEqual(self.post(read).status_code,403)

    def test_overlap_and_blocking_are_decided_by_transaction(self):
        self.rpc_result={'status':'overlap','conflicts':[self.row]}
        result=self.post()
        self.assertEqual(result.status_code,409)
        self.assertNotIn('participants',result.json['conflicts'][0])
        self.rpc_result={'status':'blocked'}
        self.assertEqual(self.post({**self.body,'acknowledge_overlap':True}).status_code,409)
        self.assertTrue(self.rpc_calls[-1][1]['p_ack'])
        self.rpc_result={'status':'stale'}
        self.assertEqual(self.post({**self.body,'action':'update','version':1}).status_code,409)

    def test_validation_and_storage_outage(self):
        for changes in ({'participants':''},{'starts_at':'2099-10-05T12:30'},
                        {'ends_at':'2099-10-05T11:00'},{'kind':'admin'}, {'edit_code':'short'}):
            self.assertEqual(self.post({**self.body,**changes}).status_code,400)
        with patch.object(self.db,'rpc',side_effect=RuntimeError('private database detail')):
            response=self.post()
        self.assertEqual(response.status_code,503)
        self.assertNotIn('private database detail',response.get_data(as_text=True))
        with patch.object(self.db,'table',side_effect=RuntimeError('private database detail')):
            result=self.client.get('/api/club-room/schedule')
        self.assertEqual(result.status_code,503)
        self.assertNotIn('bookings',result.json)

    def test_overnight_and_representative_participant_normalization(self):
        value=booking_payload({**self.body,'ends_at':'2099-10-06T03:00','participants':'대표 공개\n참여자 비공개, 참여자 비공개'})
        self.assertEqual(value['ends_at'],'2099-10-06T03:00:00+09:00')
        self.assertEqual(value['participants'],['대표 공개','참여자 비공개'])

    def test_existing_applicant_boundary_is_preserved(self):
        with self.client.session_transaction() as state:
            state['applicant_portal_token']='test-portal'
        self.assertEqual(self.client.get('/club-room').status_code,303)
        self.assertEqual(self.client.get('/api/club-room/schedule').status_code,403)


if __name__ == '__main__':
    unittest.main()
