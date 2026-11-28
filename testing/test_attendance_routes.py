import importlib
import os
from datetime import date
from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from testing._fake_supabase import FakeSupabase

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'attendance-route-test')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'attendance-route-test')


class AttendanceRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')
        cls.module.app.config['TESTING'] = True

    def setUp(self):
        self.original = self.module.supabase
        self.fake = FakeSupabase({'members': [
            {'id': 1, 'name': '운영', 'student_id': '202600001', 'role': 'admin', 'is_active': True, 'member_status': 'active', 'account_status': 'active'},
            {'id': 2, 'name': '호반', 'student_id': '202600002', 'is_active': True}],
            'seminar_terms': [{'id': 'term', 'name': '학기', 'start_date': '2026-08-01', 'end_date': '2026-08-31', 'is_active': True}],
            'seminar_sessions': [{'id': 'thu', 'term_id': 'term', 'day_type': 'thu', 'meeting_date': '2026-08-13', 'planned_member_ids': None},
                                 {'id': 'mon', 'term_id': 'term', 'day_type': 'mon', 'meeting_date': '2026-08-17', 'planned_member_ids': []}]})
        self.module.supabase = self.fake
        self.client = self.module.app.test_client()
        with self.client.session_transaction() as state:
            state.update(user_id=1, user_role='admin', user_name='운영', attendance_csrf='csrf')
        self.headers = {'X-CSRF-Token': 'csrf'}

    def tearDown(self):
        self.module.supabase = self.original

    def test_new_pages_render_and_self_page_has_no_other_member(self):
        for path in ['/admin/seminar_sessions/thu/roster', '/admin/term_attendance?term_id=term', '/my/term_attendance?term_id=term']:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
        text = self.client.get('/my/term_attendance?term_id=term').get_data(as_text=True)
        self.assertNotIn('202600002', text)

    def test_preview_rejects_csrf(self):
        response = self.client.post('/api/admin/seminar_sessions/thu/roster/preview', json={'method': 'selected', 'member_ids': [2]})
        self.assertEqual(response.status_code, 403)

    def test_preview_token_applies_through_atomic_rpc(self):
        preview = self.client.post('/api/admin/seminar_sessions/thu/roster/preview', headers=self.headers, json={'method': 'text', 'text': '호반 202600002'}).get_json()
        captured = {}
        def rpc(name, params):
            captured.update(name=name, params=params)
            return SimpleNamespace(execute=lambda: SimpleNamespace(data={'accepted': True}))
        self.fake.rpc = rpc
        response = self.client.post('/api/admin/seminar_sessions/thu/roster/apply', headers=self.headers, json={'token': preview['token']})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured['name'], 'apply_seminar_roster_for_term')
        self.assertEqual(captured['params']['p_term_revision'], 0)
        self.assertEqual(captured['params']['p_member_ids'], [2])
        self.assertEqual(captured['params']['p_expected_member_ids'], [2])
        self.assertEqual(captured['params']['p_previous_member_ids'], [])
        self.assertEqual(captured['params']['p_mode'], 'attendance')

    def test_thursday_undo_uses_the_previous_attendance_list_from_legacy_audit(self):
        self.fake.rows['seminar_sessions'][0]['planned_member_ids'] = [2, 1]
        self.fake.rows['seminar_roster_imports'] = [{
            'session_id': 'thu', 'mode': 'absence', 'member_ids': [],
            'expected_member_ids': [2, 1], 'previous_member_ids': [1],
            'created_at': '2026-08-12T06:00:00+00:00',
        }]
        html = self.client.get('/admin/seminar_sessions/thu/roster').get_data(as_text=True)
        self.assertIn('본 세미나 참석 명단', html)
        self.assertIn('불참 (이전 방식)', html)
        with patch.object(self.fake, 'rpc', create=True) as rpc:
            rpc.return_value.execute.return_value.data = {'accepted': True}
            result = self.client.post('/api/admin/seminar_sessions/thu/roster/undo', headers=self.headers)
        self.assertEqual(result.status_code, 200)
        params = rpc.call_args.args[1]
        self.assertEqual((params['p_mode'], params['p_member_ids'], params['p_expected_member_ids']),
                         ('attendance', [1], [1]))
        self.assertEqual(params['p_previous_member_ids'], [2, 1])

    def test_thursday_and_monday_creation_use_opt_in(self):
        for day_type, day in [('thu', date(2026, 8, 13)), ('mon', date(2026, 8, 17))]:
            with self.subTest(day_type=day_type):
                weeks = {self.module._week_start(day).isoformat(): 'week'}
                payload = self.module._session_payload('term', day, day_type, weeks)
                self.assertEqual(payload['participation_mode'], 'opt_in')
                self.assertEqual(payload['is_active'], day_type == 'thu')

    def test_no_show_recording_uses_votes_and_confirmed_actual_attendance(self):
        for target in self.fake.rows['seminar_sessions']:
            with self.subTest(day=target['day_type']):
                session_id = target['id']
                url = f'/api/admin/seminar_sessions/{session_id}/no_shows'
                target.update(participation_mode='opt_in', planned_member_ids=None)
                self.fake.rows['seminar_votes'] = [{'session_id': session_id, 'member_id': 2, 'attending': True}]
                self.fake.rows['seminar_no_shows'] = []
                with patch.object(self.module, '_rebuild_matrix_for_session') as rebuild:
                    self.assertEqual(self.client.post(url, json={'member_ids': [1]}).status_code, 400)
                    added = self.client.post(url, json={'member_ids': [2], 'note': 'test'})
                    self.assertEqual(added.get_json()['added_count'], 1)
                    self.fake.rows['seminar_no_shows'] = self.fake.rows['seminar_no_shows'][0]
                    self.assertEqual(self.client.delete(f'{url}/2').status_code, 200)
                    self.assertEqual(rebuild.call_count, 2)

                    target.update(actual_member_ids=[1], attendance_confirmed_at='2026-08-20T00:00:00+00:00')
                    self.assertEqual(self.client.post(url, json={'member_ids': [2]}).status_code, 400)
                    self.assertEqual(self.client.post(url, json={'member_ids': [1]}).get_json()['added_count'], 1)
                    self.assertEqual(target['actual_member_ids'], [])

    def test_no_show_without_attendance_list_can_use_active_roster(self):
        target = self.fake.rows['seminar_sessions'][0]
        target['participation_mode'] = 'opt_in'
        url = '/api/admin/seminar_sessions/thu/no_shows'
        self.fake.rows['members'].append({'id': 3, 'name': 'Declined', 'is_active': True})
        self.fake.rows['seminar_votes'] = [{'session_id': 'thu', 'member_id': 3, 'attending': False}]
        self.fake.rows['seminar_absences'] = [{'session_id': 'thu', 'member_id': 2, 'cancelled_at': None}]
        self.assertEqual(self.client.post(url, json={'member_ids': [2]}).status_code, 400)
        self.assertEqual(self.client.post(url, json={'member_ids': [3]}).status_code, 400)
        with patch.object(self.module, '_rebuild_matrix_for_session'):
            self.assertEqual(self.client.post(url, json={'member_ids': [1]}).get_json()['added_count'], 1)
        legacy = '/api/admin/seminar_sessions/thu/absences'
        self.assertEqual(self.client.post(legacy, json={'member_ids': [1]}).status_code, 410)
        self.assertEqual(self.client.delete(f'{legacy}/2').status_code, 410)
        self.assertIsNone(self.fake.rows['seminar_absences'][0]['cancelled_at'])

    def test_unknown_names_prevent_partial_apply_token(self):
        result = self.client.post('/api/admin/seminar_sessions/mon/roster/preview', headers=self.headers, json={'method': 'text', 'text': '운영\n모르는사람'}).get_json()
        self.assertIsNone(result['token'])
        self.assertEqual(len(result['issues']), 1)

    def test_xlsx_preview_and_export(self):
        from openpyxl import Workbook, load_workbook
        wb = Workbook(); wb.active.append(['이름', '학번']); wb.active.append(['호반', '202600002'])
        buf = BytesIO(); wb.save(buf); buf.seek(0)
        response = self.client.post('/api/admin/seminar_sessions/mon/roster/preview', headers=self.headers,
                                    data={'method': 'file', 'file': (buf, 'roster.xlsx')})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['expected_count'], 1)
        exported = self.client.get('/admin/term_attendance/export?term_id=term')
        self.assertEqual(exported.status_code, 200)
        sheet = load_workbook(BytesIO(exported.data)).active
        self.assertEqual(sheet.cell(2, 8).value, 0)

    def test_conflicting_rpc_does_not_claim_success(self):
        preview = self.client.post('/api/admin/seminar_sessions/thu/roster/preview', headers=self.headers, json={'method': 'selected', 'member_ids': []}).get_json()
        self.fake.rpc = lambda *args: SimpleNamespace(execute=lambda: SimpleNamespace(data={'accepted': False}))
        result = self.client.post('/api/admin/seminar_sessions/thu/roster/apply', headers=self.headers, json={'token': preview['token']})
        self.assertEqual(result.status_code, 409)

    def checked_actual(self, html):
        import re
        return {int(v) for v in re.findall(r'class="actual-choice" type="checkbox" value="(\d+)" checked', html)}

    def add_group_plan(self):
        self.fake.rows['members'].append({'id': 3, 'name': '불참자', 'student_id': '202600003', 'is_active': True})
        self.fake.rows['history'] = [{'id': 10, 'date': '2026-08-13', 'seminar_session_id': 'thu',
                                      'groups': [['호반', '불참자'], ['모르는사람']], 'present': ['호반', '불참자', '모르는사람']}]
        self.fake.rows['seminar_absences'] = [{'session_id': 'thu', 'member_id': 3, 'cancelled_at': None}]

    def test_group_plan_is_the_default_when_no_kakao_roster_was_applied(self):
        self.add_group_plan()
        self.fake.calls.clear()
        html = self.client.get('/admin/seminar_sessions/thu/roster').get_data(as_text=True)
        self.assertEqual(self.checked_actual(html), {2})  # not the whole eligible roster
        self.assertIn('예정 0명 / 조 편성 1명 · 기본 선택: 조 편성 명단', html)
        self.assertIn('id="use-grouped" data-ids="[2]"', html)
        self.assertIn('모르는사람(회원 명단에 없음)', html)
        self.assertIn('불참으로 기록돼 선택하지 않은 사람: 불참자', html)
        self.assertFalse(any(call[0] in {'update', 'insert', 'delete', 'upsert', 'rpc'} for call in self.fake.calls))

    def test_applied_kakao_roster_stays_default_but_group_list_is_selectable(self):
        self.add_group_plan()
        self.fake.rows['seminar_sessions'][0]['planned_member_ids'] = [1]
        html = self.client.get('/admin/seminar_sessions/thu/roster').get_data(as_text=True)
        self.assertEqual(self.checked_actual(html), {1})
        self.assertIn('기본 선택: 참석 예정 명단', html)
        self.assertIn('조 편성 명단으로 선택', html)

    def test_thursday_without_a_roster_uses_explicit_attendance_votes_only(self):
        html = self.client.get('/admin/seminar_sessions/thu/roster').get_data(as_text=True)
        self.assertIn('조 편성 없음', html)
        self.assertNotIn('id="use-grouped"', html)
        self.assertEqual(self.checked_actual(html), set())
        self.fake.rows['seminar_votes'] = [
            {'session_id': 'thu', 'member_id': 1, 'attending': False},
            {'session_id': 'thu', 'member_id': 2, 'attending': True},
        ]
        html = self.client.get('/admin/seminar_sessions/thu/roster').get_data(as_text=True)
        self.assertEqual(self.checked_actual(html), {2})

    def test_confirmed_attendance_is_not_replaced_by_group_plan(self):
        self.add_group_plan()
        self.fake.rows['seminar_sessions'][0].update(attendance_confirmed_at='2026-08-13T12:00:00+00:00', actual_member_ids=[1])
        html = self.client.get('/admin/seminar_sessions/thu/roster').get_data(as_text=True)
        self.assertEqual(self.checked_actual(html), {1})
        self.assertIn('기본 선택: 확정된 실제 출석', html)

    def test_bulk_shows_basis_and_disables_sessions_without_data(self):
        self.fake.rows['members'][1]['name'] = '호반'
        self.fake.rows['history'] = [{'id': 10, 'date': '2026-08-13', 'seminar_session_id': 'thu', 'groups': [['호반']], 'present': ['호반']}]
        self.fake.rows['seminar_sessions'].append({'id': 'empty', 'term_id': 'term', 'day_type': 'thu', 'meeting_date': '2026-08-20', 'planned_member_ids': None})
        with patch('attendance_routes.scope_members', side_effect=lambda db, members, term=None: members):
            html = self.client.get('/admin/term_attendance?term_id=term').get_data(as_text=True)
            self.assertIn('조 편성 1명', html)
            self.assertIn('카카오 명단 0명', html)
            self.assertIn('value="empty" disabled', html)
            self.assertIn('선택 불가 · 저장된 참석 명단과 조 편성이 없습니다', html)
            result = self.client.post('/api/admin/term_attendance/term/preview', headers=self.headers, json={'session_ids': ['thu', 'mon']})
            self.assertEqual(result.status_code, 200)
            items = {item['date']: item for item in result.get_json()['items']}
            self.assertEqual((items['2026-08-13']['basis'], items['2026-08-13']['count']), ('조 편성', 1))
            self.assertEqual(items['2026-08-17']['basis'], '카카오 명단')
            forced = self.client.post('/api/admin/term_attendance/term/preview', headers=self.headers, json={'session_ids': ['thu', 'empty']})
            self.assertEqual(forced.status_code, 409)
        self.assertFalse(any(call[0] in {'update', 'insert', 'delete', 'upsert', 'rpc'} for call in self.fake.calls))

    def test_legacy_signup_routes_are_retired_without_data_reads(self):
        for path in ['/api/seminar_vote/verify', '/api/seminar_vote/submit', '/api/attendance']:
            result = self.client.post(path, json={})
            self.assertEqual(result.status_code, 410)
        self.assertEqual(self.client.get('/api/seminar_vote/counts').status_code, 410)
        self.assertFalse(any(call[0] in {'update', 'insert', 'delete'} for call in self.fake.calls))

    def test_individual_and_bulk_group_matching_agree_on_scoped_homonyms(self):
        self.fake.rows['members'] = [
            {'id': 1, 'name': '운영', 'student_id': '202600001', 'role': 'admin', 'is_active': True, 'member_status': 'active', 'account_status': 'active'},
            {'id': 2, 'name': '동명', 'student_id': '202600002', 'is_active': True},
            {'id': 3, 'name': '동명', 'student_id': '202600003', 'is_active': True},
        ]
        self.fake.rows['seminar_terms'][0]['roster_initialized_at'] = '2026-08-01T00:00:00Z'
        self.fake.rows['seminar_term_members'] = [
            {'term_id': 'term', 'member_id': 1, 'status': 'active'},
            {'term_id': 'term', 'member_id': 2, 'status': 'active'},
            {'term_id': 'term', 'member_id': 3, 'status': 'left'},
        ]
        self.fake.rows['history'] = [
            {'id': 10, 'date': '2026-08-13', 'seminar_session_id': 'thu', 'groups': [['동명']], 'present': ['동명']},
        ]
        html = self.client.get('/admin/seminar_sessions/thu/roster').get_data(as_text=True)
        self.assertEqual(self.checked_actual(html), {2})
        self.assertIn('id="use-grouped" data-ids="[2]"', html)
        preview = self.client.post('/api/admin/term_attendance/term/preview', headers=self.headers, json={'session_ids': ['thu']})
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.get_json()['items'][0]['names'], ['동명'])

    def test_pending_sessions_excludes_inactive_and_break_weeks(self):
        self.fake.rows['seminar_weeks'] = [
            {'id': 'w-normal', 'term_id': 'term', 'book_title': '정상 책', 'note': ''},
            {'id': 'w-break', 'term_id': 'term', 'book_title': '', 'note': '중간고사 휴회'},
        ]
        self.fake.rows['seminar_sessions'] = [
            {'id': 'thu', 'term_id': 'term', 'seminar_week_id': 'w-normal', 'day_type': 'thu', 'meeting_date': '2026-08-13', 'is_active': True, 'planned_member_ids': [1]},
            {'id': 'inactive-s', 'term_id': 'term', 'seminar_week_id': 'w-normal', 'day_type': 'mon', 'meeting_date': '2026-08-10', 'is_active': False, 'planned_member_ids': [1]},
            {'id': 'break-s', 'term_id': 'term', 'seminar_week_id': 'w-break', 'day_type': 'thu', 'meeting_date': '2026-08-20', 'is_active': True, 'planned_member_ids': [1]},
        ]
        html = self.client.get('/admin/term_attendance?term_id=term').get_data(as_text=True)
        self.assertIn('value="thu"', html)
        self.assertNotIn('value="inactive-s"', html)
        self.assertNotIn('value="break-s"', html)
        for skipped in ('inactive-s', 'break-s'):
            res = self.client.post('/api/admin/term_attendance/term/preview', headers=self.headers, json={'session_ids': [skipped]})
            self.assertEqual(res.status_code, 409)


    def test_group_cards_render_absence_picker_without_duplicate_checkboxes(self):
        import re
        self.add_group_plan()
        self.fake.rows['history'][0].update(facilitators=['호반'], group_editor_state={'group_names': ['토론조']})
        html = self.client.get('/admin/seminar_sessions/thu/roster').get_data(as_text=True)
        self.assertIn('class="attendance-group-grid"', html)
        self.assertIn('<h3>토론조</h3>', html)
        self.assertIn('조 편성 화면에서 실제로 불참한 사람만 눌러 체크를 해제해 주세요.', html)
        self.assertIn('id="absent-summary"', html)
        self.assertIn('attendance-pre-absent-tag">사전 불참', html)
        self.assertIn('attendance-role-tag">발제', html)
        self.assertIn('모르는사람</strong><small>(회원 명단에 없음)', html)
        values = re.findall(r'class="actual-choice" type="checkbox" value="(\d+)"', html)
        self.assertEqual(sorted(values), ['1', '2', '3'])
        self.assertEqual(self.checked_actual(html), {2})
        self.assertIn('조 편성 외 회원 추가 선택', html)
        self.assertLess(html.index('id="actual-attendance"'), html.index('id="roster-text"'))
        self.assertNotIn('id="actual-confirmed-view"', html)
        self.assertIn('>실제 출석 확정</button>', html)

    def test_confirmed_attendance_shows_completion_and_asks_to_edit(self):
        self.add_group_plan()
        self.fake.rows['seminar_sessions'][0].update(attendance_confirmed_at='2026-08-13T12:00:00+00:00', actual_member_ids=[1, 2])
        html = self.client.get('/admin/seminar_sessions/thu/roster').get_data(as_text=True)
        self.assertIn('실제 참석 반영이 완료되었습니다.', html)
        self.assertIn('실제 참석 2명 · 반영 시각 2026-08-13 21:00 (한국시간)', html)
        self.assertIn('참석 명단을 수정하시겠어요?', html)
        self.assertIn('id="edit-actual-attendance"', html)
        self.assertIn('<div id="actual-editor" hidden>', html)
        self.assertIn('id="cancel-edit-actual"', html)
        self.assertIn('실제 참석 반영 수정 완료', html)
        self.assertIn('attendance-absent-tag">불참', html)  # 불참자 in the group summary
        self.assertEqual(self.checked_actual(html), {1, 2})
        self.assertIn('<details class="attendance-panel attendance-roster-import">', html)


if __name__ == '__main__':
    unittest.main()
