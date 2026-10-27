import importlib
import os
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch
from flask import Flask
from testing._fake_supabase import FakeSupabase
from engagement import init_engagement_routes
from minipc_security import install_security

os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'synthetic-security-test')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'synthetic-security-test')
TOKEN = '11111111-1111-1111-1111-111111111111'

def member(mid, role='member'):
    return dict(id=mid, name=f'test-{mid}', role=role, is_active=True,
                member_status='active', account_status='active', social_id=f'fake-{mid}', student_id=f'100{mid}')

class SecurityRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')

    def setUp(self):
        self.fake = FakeSupabase({'members': [member(1,'admin'),member(2,'officer'),member(3)]})
        self.original = self.module.supabase
        self.module.supabase = self.fake
        self.app = self.module.app
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        self.headers = {'X-App-CSRF': 'test-csrf'}

    def tearDown(self):
        self.module.supabase = self.original
        self.app.config.update(REQUIRE_ORIGIN_AUTH=False, ORIGIN_AUTH_SECRET='')

    def login(self, mid=2):
        with self.client.session_transaction() as state:
            state.update(user_id=mid,user_role=self.fake.rows['members'][mid-1]['role'],
                         auth_provider='kakao',sensitive_csrf='test-csrf')

    def test_officer_cannot_change_admin_before_any_write(self):
        self.login()
        for action, payload in [('delete',{}),('set_status',{'member_status':'inactive'}),('edit',{'name':'changed'})]:
            self.assertEqual(self.client.post(f'/api/admin/members/1/{action}',json=payload,headers=self.headers).status_code,403)
        for source,target in [(1,3),(3,1)]:
            self.assertEqual(self.client.post('/api/admin/members/merge',json={'source_id':source,'target_id':target},headers=self.headers).status_code,403)
        self.assertFalse(any(c[0] in {'update','delete','insert'} for c in self.fake.calls))

    def test_csrf_missing_and_forged_rejected(self):
        self.login()
        for headers in [{},{'X-App-CSRF':'wrong'}]:
            self.assertEqual(self.client.post('/api/admin/members/3/delete',json={},headers=headers).status_code,403)

    def test_general_member_mutation_uses_atomic_rpc(self):
        self.login()
        seen=[]
        self.fake.rpc=lambda name,args: SimpleNamespace(execute=lambda: (seen.append((name,args)) or SimpleNamespace(data={'accepted':True})))
        self.assertEqual(self.client.post('/api/admin/members/3/set_status',json={'member_status':'dormant'},headers=self.headers).status_code,200)
        self.assertEqual(seen[0][0],'protected_member_mutate')
        self.assertEqual(seen[0][1]['p_actor_id'],2)

    def test_link_request_preserves_members_and_does_not_login(self):
        before=deepcopy(self.fake.rows['members'])
        seen=[]
        self.fake.rpc=lambda name,args: SimpleNamespace(execute=lambda: (seen.append((name,args)) or SimpleNamespace(data={'accepted':True})))
        with self.client.session_transaction() as state:
            state.update(temp_social_data={'social_id':'fake-new'},sensitive_csrf='test-csrf')
        result=self.client.post('/link_account',data={'action':'link','existing_name':'test-3','student_id':'1003'},headers=self.headers)
        self.assertEqual(result.status_code,302)
        self.assertEqual(self.fake.rows['members'],before)
        self.assertEqual(seen[0][1]['p_social_id'],'fake-new')
        with self.client.session_transaction() as state:
            self.assertNotIn('user_id',state)

    def test_name_only_link_does_not_call_rpc(self):
        with self.client.session_transaction() as state:
            state.update(temp_social_data={'social_id':'fake-new'},sensitive_csrf='test-csrf')
        self.client.post('/link_account',data={'action':'link','existing_name':'test-3'},headers=self.headers)
        self.assertFalse(any(c[0] in {'insert','update','delete'} for c in self.fake.calls))

    def test_notifications_hide_private_details(self):
        self.login()
        self.fake.rows['notifications']=[{'id':1,'status':'pending','details':{'pending_social_id':'private-kakao','target_student_id':'1003','original_name':'synthetic'}}]
        text=self.client.get('/api/notifications').get_data(as_text=True)
        self.assertNotIn('private-kakao',text)
        self.assertNotIn('1003',text)

    def test_origin_auth_and_public_post_origin(self):
        self.app.config.update(REQUIRE_ORIGIN_AUTH=True,ORIGIN_AUTH_SECRET='x'*32)
        self.assertEqual(self.client.get('/static/theme.css').status_code,403)
        self.assertEqual(self.client.get('/static/theme.css',headers={'X-App-Origin-Auth':'wrong'}).status_code,403)
        self.assertEqual(self.client.get('/static/theme.css',headers={'X-App-Origin-Auth':'x'*32}).status_code,200)
        self.login()
        headers={**self.headers,'X-App-Origin-Auth':'x'*32,'Origin':self.module.PUBLIC_BASE_URL}
        self.assertEqual(self.client.post('/api/admin/members/1/delete',json={},headers=headers,base_url='https://node.example.ts.net').status_code,403)
        # Origin guard allows the configured public host independently from transport Host.
        with self.app.test_request_context('/api/example',method='POST',headers={'Origin':self.module.PUBLIC_BASE_URL},base_url='https://node.example.ts.net'):
            from flask import session
            session['user_id']=2
            self.assertIsNone(self.module.reject_cross_site_state_changes())

class EngagementIdentityTests(unittest.TestCase):
    def setUp(self):
        self.db=FakeSupabase({'members':[member(1),member(2)]})
        self.app=Flask(__name__,template_folder='../templates')
        self.app.secret_key='synthetic'
        self.app.config['TESTING']=True
        self.app.add_url_rule('/login/kakao','kakao_login',lambda:'login')
        install_security(self.app,lambda:self.db)
        init_engagement_routes(self.app,self.db,lambda **kw:lambda fn:fn)
        self.client=self.app.test_client()
        self.paths=['/books/suggest',f'/books/suggestions/{TOKEN}/support',f'/books/suggestions/{TOKEN}/comments',f'/review/seminar/{TOKEN}',f'/brick/apply/{TOKEN}',f'/brick/review/{TOKEN}']

    def test_all_six_posts_reject_forged_identity(self):
        for remembered in [False,True]:
            with self.client.session_transaction() as state:
                state.clear()
                if remembered: state.update(participation_member_id=1,user_id=1)
            for path in self.paths:
                result=self.client.post(path,data={'student_id':'1001','member_name':'test-1','member_id':1})
                self.assertEqual(result.status_code,303)
                self.assertTrue(result.location.startswith('/login/kakao?next='))
        self.assertFalse(any(c[0] in {'insert','update','delete'} for c in self.db.calls))

    def test_authenticated_comment_ignores_forged_author(self):
        with self.client.session_transaction() as state:
            state.update(user_id=1,auth_provider='kakao',sensitive_csrf='csrf')
        path=f'/books/suggestions/{TOKEN}/comments'
        self.assertEqual(self.client.post(path,data={'content':'test'}).status_code,403)
        result=self.client.post(path,data={'content':'test','member_id':2,'member_name':'test-2','student_id':'1002','csrf_token':'csrf'})
        self.assertEqual(result.status_code,302)
        self.assertEqual(self.db.rows['book_suggestion_comments'][0]['member_id'],1)
        self.db.rows['members'][0]['is_active']=False
        self.assertEqual(self.client.post(path,data={'csrf_token':'csrf','content':'test'}).status_code,303)

    def test_origin_required_refuses_empty_configuration(self):
        with patch.dict(os.environ,{'REQUIRE_ORIGIN_AUTH':'true','ORIGIN_AUTH_SECRET':''}):
            with self.assertRaises(RuntimeError): install_security(Flask('failclosed'),lambda:self.db)
