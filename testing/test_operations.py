import os
os.environ.setdefault('PYTHON_DOTENV_DISABLED','1')
os.environ.setdefault('FLASK_SECRET_KEY','operations-test')
os.environ.setdefault('SUPABASE_URL','http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY','test')
import importlib
import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from testing.test_lms_improvements import WriteDB
from operations import Operations, occurrence_dates, filter_inbox, pending_work
from lms_learning import historical_courses
from notification_delivery import collect_items, reconcile

def fixture():
    members=[dict(id=i,name=f'회원{i}',student_id=str(202500000+i),role='admin' if i==1 else 'member',
                  is_active=True,account_status='active',member_status='active') for i in range(1,7)]
    return dict(members=members, seminar_terms=[dict(id='term',name='26-2학기',start_date='2026-09-01',end_date='2026-12-31',is_active=True,operations_initialized_at='set',roster_initialized_at='set',roster_revision=0)],
      operation_roles=[dict(id='head',label='부장',is_active=True,capabilities=['attendance','tasks']),dict(id='president',label='회장',is_active=True,capabilities=['members','tasks']),dict(id='member',label='부원',is_active=True,capabilities=[])],
      term_officers=[dict(id='a',term_id='term',member_id=2,role_id='president'),dict(id='b',term_id='term',member_id=3,role_id='head'),dict(id='c',term_id='term',member_id=4,role_id='head'),dict(id='d',term_id='term',member_id=5,role_id='member')],
      seminar_sessions=[dict(id='meeting',term_id='term',seminar_week_id='w',day_type='thu',meeting_date='2026-10-22',is_active=True,planned_member_ids=[2,3],roster_updated_at=None,attendance_confirmed_at=None)],
      seminar_weeks=[dict(id='w',term_id='term',week_start='2026-10-19',book_title='책',note='')],history=[],operation_rules=[],operation_tasks=[])

class PolicyTests(unittest.TestCase):
    def test_assigned_scope_and_default_recipients(self):
        db=WriteDB(fixture());ops=Operations(db);m=db.rows['members']
        self.assertEqual(ops.recipients(m,'attendance','term'),[3,4])
        self.assertEqual(ops.recipients(m,'members','term'),[2])
        self.assertTrue(ops.can(m[2],'attendance','term'))
        self.assertFalse(ops.can(m[2],'members','term'))
        self.assertFalse(ops.can(m[2],'attendance','other'))
        self.assertFalse(ops.can(m[4],'attendance','term'))
        m[2]['is_active']=False;self.assertFalse(ops.can(m[2],'attendance','term'))

    def test_role_revocation_and_override(self):
        rows=fixture();rows['term_officers'][1]['capabilities']=[];db=WriteDB(rows)
        self.assertFalse(Operations(db).can(rows['members'][2],'attendance','term'))
        db.rows['operation_roles'][0]['is_active']=False
        self.assertEqual(Operations(db).recipients(rows['members'],'attendance','term'),[1])

    def test_calendar_month_end_and_year_boundary(self):
        r=dict(start_date='2026-12-01',end_date='2027-03-01',frequency='monthly',month_day=31)
        self.assertEqual([d.isoformat() for d in occurrence_dates(r,date(2027,3,1))],['2026-12-31','2027-01-31','2027-02-28'])

    def test_past_courses_split_summer_and_winter(self):
        histories=[dict(id=i,date=d,attendance_confirmed_at='yes',actual_member_ids=[1]) for i,d in enumerate(['2025-06-30','2025-07-01','2025-08-31','2025-09-01','2026-01-01','2026-02-28'])]
        found=historical_courses([{'id':1,'name':'가'}],histories,[],1,date(2026,10,29))
        self.assertEqual({c['name']:c['count'] for c in found},{'25-1학기':1,'25-여름학기':2,'25-2학기':1,'25-겨울학기':2})

    def test_task_shared_recipients_and_completion(self):
        db=WriteDB(fixture());ops=Operations(db);now=datetime(2026,10,29,tzinfo=timezone.utc)
        work=pending_work(db,ops,db.rows['members'],now)
        self.assertEqual(work[0]['recipients'],[3,4])
        db.rows['seminar_sessions'][0]['attendance_confirmed_at']='done'
        self.assertEqual(pending_work(db,ops,db.rows['members'],now),[])

    def test_hidden_and_break_meetings_not_tasks(self):
        db=WriteDB(fixture());db.rows['seminar_weeks'][0].update(book_title='',note='휴강')
        self.assertEqual(pending_work(db,Operations(db),db.rows['members'],datetime(2026,10,29,tzinfo=timezone.utc)),[])

    def test_legacy_confirmed_history_does_not_request_confirmation_again(self):
        db=WriteDB(fixture());db.rows['history']=[dict(id='old',date='2026-10-22',book_title='책',attendance_confirmed_at='done')]
        self.assertEqual(pending_work(db,Operations(db),db.rows['members'],datetime(2026,10,29,tzinfo=timezone.utc)),[])

    def test_request_daily_reminder_reaches_membership_officers(self):
        db=WriteDB(fixture());db.rows['seminar_sessions']=[]
        db.rows['notifications']=[dict(id=1,type='new_user_request',status='pending',related_member_id=6,created_at='2026-10-29T00:00:00+00:00')]
        items,_=collect_items(db,datetime(2026,10,29,4,tzinfo=timezone.utc))
        self.assertEqual([i['member_id'] for i in items if i.get('operation_key')=='digest'],[2])

    def test_rule_recipient_revocation_hides_old_notifications(self):
        db=WriteDB(fixture());db.rows['operation_rules']=[dict(id='r',term_id='term',is_active=True,role_ids=['head'],member_ids=[])]
        db.rows['operation_tasks']=[dict(id='t',rule_id='r',completed_at=None)]
        item=dict(id='n',operation_key='custom:t',operation_term_id='term',url='/operations/tasks/t')
        self.assertEqual(filter_inbox(db,Operations(db),db.rows['members'][4],[item]),[])
        self.assertEqual(len(filter_inbox(db,Operations(db),db.rows['members'][2],[item])),1)
        db.rows['operation_tasks'][0]['completed_at']='done'
        self.assertEqual(filter_inbox(db,Operations(db),db.rows['members'][2],[item]),[])

    def test_one_pm_daily_digest_and_dedup(self):
        db=WriteDB(fixture())
        before=datetime(2026,10,29,3,59,tzinfo=timezone.utc)
        items,_=collect_items(db,before)
        self.assertFalse(any(i.get('operation_key')=='digest' for i in items))
        after=datetime(2026,10,29,4,0,tzinfo=timezone.utc)
        items,_=collect_items(db,after)
        self.assertEqual(sum(i.get('operation_key')=='digest' for i in items),2)
        reconcile(db,items,after);count=len(db.rows['member_inbox']);reconcile(db,items,after)
        self.assertEqual(len(db.rows['member_inbox']),count)

class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module=importlib.import_module('app');cls.module.app.config['TESTING']=True
    def setUp(self):
        self.db=WriteDB(fixture());self.old=self.module.supabase;self.module.supabase=self.db;self.client=self.module.app.test_client();self.login(3)
    def tearDown(self):self.module.supabase=self.old
    def login(self,mid):
        with self.client.session_transaction() as s:s.clear();s.update(user_id=mid,user_role='admin' if mid==1 else 'member',sensitive_csrf='csrf',attendance_csrf='csrf')
    def test_head_can_attend_not_members_or_global_settings(self):
        self.assertEqual(self.client.get('/admin/seminar_sessions/meeting/roster').status_code,200)
        self.assertEqual(self.client.post('/api/admin/term_members/term',json={},headers={'X-CSRF-Token':'csrf'}).status_code,403)
        self.assertEqual(self.client.get('/operations/settings').status_code,403)
        self.assertEqual(self.client.get('/operations/terms/term/rules').status_code,200)
        self.assertEqual(self.client.get('/operations/terms/term/officers').status_code,200)
        html=self.client.get('/admin/term_attendance?term_id=term').get_data(as_text=True)
        self.assertNotIn('id="save-minimum"',html)
        self.assertNotIn('OT 참석 인정 설정',html)

    def test_single_confirmation_binds_actor_snapshot_and_checks_noshows(self):
        from html import unescape
        import re
        calls=[]
        self.db.rpc=lambda name,params:(calls.append((name,params)) or SimpleNamespace(execute=lambda:SimpleNamespace(data={'accepted':True})))
        html=self.client.get('/admin/seminar_sessions/meeting/roster').get_data(as_text=True)
        token=unescape(re.search('data-confirmation-token="([^"]+)"',html)[1])
        body={'confirmation_token':token,'member_ids':[2,3]}
        self.login(4)
        self.assertEqual(self.client.post('/api/admin/seminar_sessions/meeting/attendance/confirm',json=body,headers={'X-CSRF-Token':'csrf'}).status_code,400)
        self.assertEqual(calls,[])
        self.login(3)
        self.db.rows['seminar_no_shows']=[dict(session_id='meeting',member_id=2,cancelled_at=None)]
        self.assertEqual(self.client.post('/api/admin/seminar_sessions/meeting/attendance/confirm',json=body,headers={'X-CSRF-Token':'csrf'}).status_code,400)
        self.db.rows['seminar_no_shows']=[]
        with patch.object(self.module,'_rebuild_matrix_for_session',return_value=None):
            self.assertEqual(self.client.post('/api/admin/seminar_sessions/meeting/attendance/confirm',json=body,headers={'X-CSRF-Token':'csrf'}).status_code,200)
        self.assertEqual(calls[0][1]['p_entries'][0]['expected_term_revision'],0)
    def test_primary_admin_can_render_assignment_and_structure(self):
        self.login(1)
        for p in ['/operations','/operations/settings','/operations/terms/term/officers','/operations/terms/term/rules']:
            self.assertEqual(self.client.get(p).status_code,200,p)
    def test_staff_can_not_escalate_assignments(self):
        r=self.client.post('/api/operations/terms/term/officers',json={'entries':[],'revision':0},headers={'X-App-CSRF':'csrf'})
        self.assertEqual(r.status_code,403)
    def test_bulk_preview_is_actor_bound_and_calls_atomic_rpc(self):
        self.db.rpc=lambda name,params:SimpleNamespace(execute=lambda:SimpleNamespace(data={'accepted':True}))
        result=self.client.post('/api/admin/term_attendance/term/preview',json={'session_ids':['meeting']},headers={'X-CSRF-Token':'csrf'})
        self.assertEqual(result.status_code,200);token=result.get_json()['token']
        self.login(4)
        self.assertEqual(self.client.post('/api/admin/term_attendance/term/confirm',json={'token':token},headers={'X-CSRF-Token':'csrf'}).status_code,403)
        self.login(3)
        with patch.object(self.module,'_rebuild_matrix_for_session',return_value=None):
            self.assertEqual(self.client.post('/api/admin/term_attendance/term/confirm',json={'token':token},headers={'X-CSRF-Token':'csrf'}).status_code,200)
    def test_bulk_never_guesses_unsaved_historical_roster(self):
        self.db.rows['seminar_sessions'][0]['planned_member_ids']=None
        r=self.client.post('/api/admin/term_attendance/term/preview',json={'session_ids':['meeting']},headers={'X-CSRF-Token':'csrf'})
        self.assertEqual(r.status_code,409)
    def test_read_and_dismiss_are_owned_and_csrf_protected(self):
        self.db.rows['member_inbox']=[dict(id='a',member_id=3),dict(id='b',member_id=4)]
        self.assertEqual(self.client.post('/api/member-notifications/a/dismiss').status_code,403)
        self.client.post('/api/member-notifications/b/dismiss',headers={'X-App-CSRF':'csrf'})
        self.assertNotIn('dismissed_at',self.db.rows['member_inbox'][1])
        self.client.post('/api/member-notifications/a/dismiss',headers={'X-App-CSRF':'csrf'})
        self.assertIsNotNone(self.db.rows['member_inbox'][0]['dismissed_at'])
        self.client.post('/api/member-notifications/read-all',headers={'X-App-CSRF':'csrf'})
        self.assertIsNotNone(self.db.rows['member_inbox'][0]['read_at']);self.assertNotIn('read_at',self.db.rows['member_inbox'][1])

if __name__=='__main__':unittest.main()
