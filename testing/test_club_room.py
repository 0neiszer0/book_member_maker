import hashlib
import hmac
import importlib
import os
import unittest
from datetime import datetime, timedelta, timezone
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
                         representative='대표 공개', participants='참여자 비공개, 대표 공개', purpose='목적 비공개',
                         knu_email='member@knu.ac.kr')

    def login(self, mid, role):
        with self.client.session_transaction() as state:
            state.update(user_id=mid,user_role=role)

    def post(self, body=None, csrf=True):
        return self.client.post('/api/club-room/bookings/'+self.identifier,json=body or self.body,
                                headers={'X-Room-CSRF':self.csrf} if csrf else {})

    def test_public_form_and_schedule_never_disclose_private_fields(self):
        html = self.client.get('/club-room').get_data(as_text=True)
        self.assertNotIn('data-kind="meeting"', html)
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
        self.assertIn('data-kind="meeting"',self.client.get('/club-room').get_data(as_text=True))
        self.assertEqual(self.post(body).status_code,200)
        self.assertEqual(self.rpc_calls[-1][1]['p_actor'],1)
        data = self.client.get('/api/club-room/staff?date=2099-10-05')
        self.assertEqual(data.status_code,200)
        self.assertIn('참여자 비공개', data.json['bookings'][0]['participants'])
        self.db.rows['members'][0]['is_active'] = False
        self.assertEqual(self.post(body).status_code,403)

    def test_blocked_member_is_not_recognized_as_staff(self):
        self.login(1, 'officer')
        self.assertEqual(self.post({**self.body, 'kind': 'meeting'}).status_code, 200)
        self.db.rows['members'][0]['member_status'] = 'blocked'
        self.assertEqual(self.post({**self.body, 'kind': 'meeting'}).status_code, 403)

    def test_trusted_proxy_prefers_app_client_ip(self):
        self.module.app.config['ORIGIN_AUTH_SECRET'] = 's' * 32
        self.addCleanup(self.module.app.config.update, ORIGIN_AUTH_SECRET='')
        headers = {
            'X-Room-CSRF': self.csrf,
            'X-App-Origin-Auth': 's' * 32,
            'X-App-Client-IP': '203.0.113.9',
            'X-Forwarded-For': '198.51.100.1',
        }
        self.client.post('/api/club-room/bookings/' + self.identifier, json=self.body, headers=headers)
        sent = self.rpc_calls[-1][1]
        expected = hmac.new(b'room-tests-only', b'room-rate:203.0.113.9', hashlib.sha256).hexdigest()
        spoofed = hmac.new(b'room-tests-only', b'room-rate:198.51.100.1', hashlib.sha256).hexdigest()
        self.assertEqual(sent['p_fingerprint'], expected)
        self.assertNotEqual(sent['p_fingerprint'], spoofed)

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

    def test_opening_hours_for_create_update_and_meetings(self):
        for action in ('create', 'update'):
            for start, end in [('00:00','09:00'), ('08:00','10:00'), ('23:00','NEXT01:00')]:
                end_date = '2099-10-06T' if end.startswith('NEXT') else '2099-10-05T'
                result = self.post({**self.body, 'action':action, 'version':1,
                    'starts_at':'2099-10-05T'+start, 'ends_at':end_date+end.replace('NEXT','')})
                self.assertEqual(result.status_code,400)
                self.assertIn('오전 9시',result.json['error'])
        self.assertEqual(self.rpc_calls,[])
        for start in ('09:00','23:00'):
            self.assertEqual(self.post({**self.body,'starts_at':'2099-10-05T'+start,'ends_at':'2099-10-06T00:00'}).status_code,200)
        self.login(1,'officer')
        self.assertEqual(self.post({**self.body,'kind':'meeting','starts_at':'2099-10-05T08:00'}).status_code,400)

    def test_regular_create_requires_school_email(self):
        required = '학교 메일 아이디를 반드시 입력해주세요. 예: 아이디@knu.ac.kr'
        without = {k: v for k, v in self.body.items() if k != 'knu_email'}
        for body in (without, {**without, 'knu_email': '   '}):
            result = self.post(body)
            self.assertEqual(result.status_code, 400)
            self.assertEqual(result.json['error'], required)
        self.assertEqual(self.rpc_calls, [])
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.rpc_calls[-1][1]['p_knu_email'], 'member@knu.ac.kr')

    def test_member_saved_email_still_satisfies_requirement(self):
        self.db.rows['members'].append(dict(id=7, role='member', is_active=True, account_status='active',
            member_status='active', knu_email='saved@knu.ac.kr', knu_email_verified_at='2026-01-01T00:00:00Z'))
        self.login(7, 'member')
        without = {k: v for k, v in self.body.items() if k != 'knu_email'}
        self.assertEqual(self.post(without).status_code, 200)
        self.assertEqual(self.rpc_calls[-1][1]['p_knu_email'], 'saved@knu.ac.kr')

    def test_verified_guest_email_still_satisfies_requirement(self):
        without = {k: v for k, v in self.body.items() if k != 'knu_email'}
        with patch('club_room.get_verified_guest_email', return_value='guest@knu.ac.kr'):
            self.assertEqual(self.post(without).status_code, 200)
        self.assertEqual(self.rpc_calls[-1][1]['p_knu_email'], 'guest@knu.ac.kr')

    def test_staff_meeting_does_not_need_email(self):
        self.login(1, 'officer')
        without = {k: v for k, v in self.body.items() if k != 'knu_email'}
        self.assertEqual(self.post({**without, 'kind': 'meeting'}).status_code, 200)
        self.assertIsNone(self.rpc_calls[-1][1]['p_knu_email'])
        self.assertEqual(self.post({**without, 'kind': 'regular'}).status_code, 400)

    def test_schedule_days_window_clamps_and_redacts(self):
        rows = self.db.rows['club_room_bookings']
        rows[0].update(starts_at='2026-11-01T12:00:00+09:00', ends_at='2026-11-01T14:00:00+09:00')
        rows.append(dict(id=str(uuid4()), kind='regular', starts_at='2026-12-10T12:00:00+09:00',
                         ends_at='2026-12-10T13:00:00+09:00', representative='먼 예약', participants=['x'],
                         purpose='p', version=1, cancelled_at=None, knu_email='a@knu.ac.kr'))
        rows.append(dict(id=str(uuid4()), kind='meeting', starts_at='2026-11-20T18:00:00+09:00',
                         ends_at='2026-11-20T20:00:00+09:00', representative='회의장', participants=['y'],
                         purpose='secret', version=1, cancelled_at=None, knu_email='b@knu.ac.kr'))
        data = self.client.get('/api/club-room/schedule?date=2026-11-01&days=42')
        self.assertEqual(data.status_code, 200)
        kinds = sorted(b['kind'] for b in data.json['bookings'])
        self.assertEqual(kinds, ['blocked', 'regular', 'regular'])
        text = data.get_data(as_text=True)
        for secret in ('secret', '회의장', 'knu_email', 'a@knu.ac.kr', 'b@knu.ac.kr', 'edit_digest', 'participants', 'purpose'):
            self.assertNotIn(secret, text)
        week = self.client.get('/api/club-room/schedule?date=2026-11-01').json['bookings']
        self.assertEqual(len(week), 1)
        self.assertEqual(len(self.client.get('/api/club-room/schedule?date=2026-11-01&days=7').json['bookings']), 1)
        self.assertEqual(len(self.client.get('/api/club-room/schedule?date=2026-11-01&days=999').json['bookings']), 3)
        self.assertEqual(len(self.client.get('/api/club-room/schedule?date=2026-11-01&days=0').json['bookings']), 1)
        self.assertEqual(len(self.client.get('/api/club-room/schedule?date=2026-11-01&days=abc').json['bookings']), 1)

    def test_legacy_night_booking_remains_readable_and_cancellable(self):
        self.db.rows['club_room_bookings'][0]['starts_at']='2099-10-05T02:00:00+09:00'
        self.assertEqual(self.post(dict(action='read',edit_code=self.code)).status_code,200)
        self.assertEqual(self.post(dict(action='cancel',edit_code=self.code,version=1)).status_code,200)


class RoomEmailTests(RoomTests):
    """Friendly school-email management, on top of the unchanged legacy-code behaviour."""
    def setUp(self):
        super().setUp()
        self.row['knu_email'] = 'owner@knu.ac.kr'
        self.db.rows['club_room_bookings'][0]['knu_email'] = 'owner@knu.ac.kr'
        self.db.rows['members'].append(dict(id=3, role='member', is_active=True, account_status='active',
            member_status='active', knu_email='Owner@knu.ac.kr', knu_email_verified_at='2026-01-01T00:00:00Z'))
        self.sent = []
        self.module.app.extensions['email_auth_sender'] = lambda *args: self.sent.append(args)
        self.addCleanup(self.module.app.extensions.pop, 'email_auth_sender', None)
        base_rpc = self.db.rpc
        def rpc(name, args):
            if name == 'reserve_email_auth_code':
                self.db.rows.setdefault('email_auth_codes', []).append({
                    'id': args['p_id'], 'email': args['p_email'], 'purpose': args['p_purpose'],
                    'code_hash': args['p_code_hash'], 'attempts': 0, 'consumed_at': None,
                    'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()})
                return SimpleNamespace(execute=lambda: SimpleNamespace(data=True))
            return base_rpc(name, args)
        self.db.rpc = rpc

    def api(self, path, body, csrf=True):
        return self.client.post(path, json=body, headers={'X-Room-CSRF': self.csrf} if csrf else {})

    def verify_as(self, local):
        with patch('guest_email_verify.secrets.randbelow', return_value=123456):
            self.assertEqual(self.api('/api/club-room/email/request', {'email': local}).status_code, 200)
        return self.api('/api/club-room/email/verify', {'code': '123456'})

    def test_guest_gets_standalone_shell_and_member_gets_lms(self):
        guest = self.client.get('/club-room').get_data(as_text=True)
        self.assertIn('public-shell', guest)
        self.assertNotIn('lms-page', guest)
        self.assertIn('id="cr-share-link"', guest)
        self.assertIn('id="integrated-calendar"', guest)
        self.assertIn('id="cr-email"', guest)
        self.assertNotIn('id="cr-legacy"', guest)
        self.assertNotIn('id="cr-code-details"', guest)
        self.assertIn('class="knu-email-group"', guest)
        self.assertIn('@knu.ac.kr</span>', guest)
        self.assertEqual(guest.count('club_room.js'), 1)
        self.login(2, 'member')
        member = self.client.get('/club-room').get_data(as_text=True)
        self.assertIn('lms-page', member)
        self.assertNotIn('public-shell', member)
        self.assertEqual(member.count('club_room.js'), 1)

    def test_unified_calendar_routes_show_booking_controls_without_login(self):
        for path in ('/calendar', '/club-room'):
            html = self.client.get(path).get_data(as_text=True)
            for marker in ('id="integrated-calendar"', 'id="cr-new"', 'id="cr-my-open"', 'id="cr-dialog"', 'id="cr-email"'):
                self.assertIn(marker, html)
            for marker in ('data-kind="meeting"', 'class="cr-availability"', 'class="cr-staff"'):
                self.assertNotIn(marker, html)
        self.login(1, 'officer')
        for path in ('/calendar', '/club-room'):
            html = self.client.get(path).get_data(as_text=True)
            self.assertIn('data-kind="meeting"', html)
            self.assertIn('id="cr-staff-panel"', html)
        with self.client.session_transaction() as state:
            state['member_preview'] = True
        self.assertNotIn('data-kind="meeting"', self.client.get('/calendar').get_data(as_text=True))

    def test_create_stores_normalized_email_and_still_returns_code(self):
        response = self.post({**self.body, 'knu_email': ' Owner '})
        self.assertEqual(response.status_code, 200)
        sent = self.rpc_calls[-1][1]
        self.assertEqual(sent['p_knu_email'], 'owner@knu.ac.kr')
        self.assertEqual(response.json['edit_code'], self.code)
        self.assertTrue(response.json['has_email'])
        self.assertNotIn('knu_email', response.json['booking'])
        self.assertTrue(self.post(self.body).json['has_email'])
        self.assertEqual(self.post({**self.body, 'knu_email': 'x@gmail.com'}).status_code, 400)
        self.assertEqual(self.post({**self.body, 'knu_email': '한글'}).status_code, 400)

    def test_logged_in_member_email_is_autofilled_and_listed(self):
        self.login(3, 'member')
        page = self.client.get('/club-room').get_data(as_text=True)
        self.assertIn('data-email="owner@knu.ac.kr"', page)
        self.assertIn('data-member="true"', page)
        self.post({k: v for k, v in self.body.items() if k != 'knu_email'})
        self.assertEqual(self.rpc_calls[-1][1]['p_knu_email'], 'owner@knu.ac.kr')
        mine = self.client.get('/api/club-room/my-bookings').json
        self.assertEqual(mine['email'], 'owner@knu.ac.kr')
        self.assertEqual([b['id'] for b in mine['bookings']], [self.identifier])
        self.assertNotIn('edit_digest', mine['bookings'][0])
        self.assertNotIn('knu_email', mine['bookings'][0])

    def test_email_otp_request_verify_and_my_bookings(self):
        self.assertEqual(self.client.get('/api/club-room/my-bookings').json, {'email': '', 'bookings': []})
        self.assertEqual(self.api('/api/club-room/email/request', {'email': 'owner'}, csrf=False).status_code, 403)
        self.assertEqual(self.api('/api/club-room/email/request', {'email': 'a@gmail.com'}).status_code, 400)
        self.assertEqual(self.api('/api/club-room/email/verify', {'code': '123456'}).status_code, 400)
        result = self.verify_as('owner')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['email'], 'owner@knu.ac.kr')
        self.assertEqual([b['id'] for b in result.json['bookings']], [self.identifier])
        self.assertEqual(self.sent[0][0], 'owner@knu.ac.kr')
        self.assertEqual(self.sent[0][2], '동아리방 예약 관리')
        self.assertEqual(self.client.get('/api/club-room/my-bookings').json['email'], 'owner@knu.ac.kr')
        self.assertIn('data-email="owner@knu.ac.kr"', self.client.get('/club-room').get_data(as_text=True))

    def test_wrong_code_does_not_verify(self):
        with patch('guest_email_verify.secrets.randbelow', return_value=123456):
            self.api('/api/club-room/email/request', {'email': 'owner'})
        self.assertEqual(self.api('/api/club-room/email/verify', {'code': '000000'}).status_code, 400)
        self.assertEqual(self.client.get('/api/club-room/my-bookings').json['email'], '')

    def test_verified_email_authorizes_read_update_cancel_without_code(self):
        self.assertEqual(self.post({'action': 'read'}).status_code, 400)
        self.verify_as('owner')
        read = self.post({'action': 'read'})
        self.assertEqual(read.status_code, 200)
        self.assertNotIn('edit_digest', read.json['booking'])
        update = {**self.body, 'action': 'update', 'edit_code': '', 'version': 1}
        self.assertEqual(self.post(update).status_code, 200)
        sent = self.rpc_calls[-1][1]
        self.assertEqual((sent['p_digest'], sent['p_verified_email']), ('', 'owner@knu.ac.kr'))
        self.assertEqual(self.post({'action': 'cancel', 'version': 1}).status_code, 200)
        self.assertEqual(self.rpc_calls[-1][1]['p_action'], 'cancel')

    def test_different_verified_email_is_rejected(self):
        self.verify_as('someone')
        self.assertEqual(self.post({'action': 'read'}).status_code, 403)
        self.assertEqual(self.client.get('/api/club-room/my-bookings').json['bookings'], [])
        self.rpc_result = {'status': 'forbidden'}
        self.assertEqual(self.post({'action': 'cancel', 'version': 1}).status_code, 403)
        self.assertEqual(self.rpc_calls[-1][1]['p_verified_email'], 'someone@knu.ac.kr')

    def test_legacy_code_flow_unchanged_when_email_present(self):
        self.assertEqual(self.post(dict(action='read', edit_code=self.code)).status_code, 200)
        self.assertEqual(self.post(dict(action='read', edit_code='b' * 43)).status_code, 403)
        self.assertEqual(self.post(dict(action='cancel', edit_code=self.code, version=1)).status_code, 200)
        self.assertIsNone(self.rpc_calls[-1][1]['p_verified_email'])


if __name__ == '__main__':
    unittest.main()
