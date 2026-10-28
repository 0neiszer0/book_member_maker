import importlib
import os
import unittest
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

from testing._fake_supabase import FakeSupabase
from wiki_access import wiki_access
from wiki_routes import clean_wiki_html
from wiki_engine import EngineUnavailable


def wiki_fixture(today=None):
    today = today or date(2026, 10, 28)
    return {
        'members': [dict(id=i, name=name, social_id=str(9000+i), role='member',
                         is_active=True, account_status='active', member_status='active')
                    for i, name in ((1, '활동 회원 예시'), (2, '휴식 회원 예시'))],
        'seminar_terms': [dict(id='current', name='2026년 2학기', is_active=True,
            start_date=(today-timedelta(days=30)).isoformat(), end_date=(today+timedelta(days=30)).isoformat(),
            roster_initialized_at='2026-09-01')],
        'seminar_term_members': [dict(term_id='current', member_id=1, status='active'),
                                dict(term_id='current', member_id=2, status='paused')],
    }


class PolicyTests(unittest.TestCase):
    def test_current_term_membership_is_the_only_edit_grant(self):
        for status, expected in [('active', True), ('paused', False), ('left', False), (None, False)]:
            with self.subTest(status=status):
                db = FakeSupabase(wiki_fixture())
                db.rows['members'][0].update(is_active=False, role='admin')
                db.rows['seminar_term_members'][0]['status'] = status
                access = wiki_access(db, {'user_id':1,'auth_provider':'kakao'}, date(2026,10,28))
                self.assertIsNotNone(access)
                self.assertEqual(access.can_edit, expected)
                self.assertFalse(any(c[0] in ('insert','update','delete') for c in db.calls))

    def test_no_previous_term_or_uninitialized_roster_fallback(self):
        for scenario in ('past', 'future', 'overlap', 'uninitialized', 'missing'):
            with self.subTest(scenario=scenario):
                db=FakeSupabase(wiki_fixture()); term=db.rows['seminar_terms'][0]
                if scenario=='past': term['end_date']='2026-09-01'
                if scenario=='future': term['start_date']='2026-12-01'
                if scenario=='overlap': db.rows['seminar_terms'].append(dict(term,id='other'))
                if scenario=='uninitialized': term['roster_initialized_at']=None
                if scenario=='missing': db.rows['seminar_term_members']=[]
                self.assertFalse(wiki_access(db, {'user_id':1,'auth_provider':'kakao'}, date(2026,10,28)).can_edit)

    def test_kakao_and_approved_account_required(self):
        for changes, identity in [({},{}), ({},{'user_id':1}),
                ({'account_status':'pending'},{'user_id':1,'auth_provider':'kakao'}),
                ({'account_status':'blocked'},{'user_id':1,'auth_provider':'kakao'}),
                ({'member_status':'inactive'},{'user_id':1,'auth_provider':'kakao'}),
                ({'social_id':None},{'user_id':1,'auth_provider':'kakao'})]:
            db=FakeSupabase(wiki_fixture()); db.rows['members'][0].update(changes)
            self.assertIsNone(wiki_access(db, identity, date(2026,10,28)))


class FakeEngine:
    @contextmanager
    def user(self, member_id):
        yield None
    def document(self, client, title, revision=None):
        return dict(title=title, source='sample', version='1', exists=True, history=[])
    def render(self, *args): return '<p>sample</p>'
    def titles(self, *args): return ['대문']
    def history(self, *args): return []
    def save(self, *args): pass


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        environment = patch.dict(os.environ, dict(PYTHON_DOTENV_DISABLED='1',FLASK_SECRET_KEY='wiki-test-only',
            SUPABASE_URL='http://127.0.0.1:9',SUPABASE_SERVICE_KEY='wiki-test-only',
            PUBLIC_BASE_URL='http://localhost',SESSION_COOKIE_SECURE='0'))
        environment.start()
        cls.addClassCleanup(environment.stop)
        with patch('supabase.create_client', return_value=FakeSupabase()), patch('dotenv.load_dotenv'):
            cls.module=importlib.import_module('app')
        config = patch.dict(cls.module.app.config, TESTING=True, WIKI_ENABLED=True, SESSION_COOKIE_SECURE=False)
        config.start()
        cls.addClassCleanup(config.stop)

    def setUp(self):
        from datetime import datetime, timezone
        today=datetime.now(timezone(timedelta(hours=9))).date()
        self.db=FakeSupabase(wiki_fixture(today))
        database = patch.object(self.module, 'supabase', self.db)
        database.start(); self.addCleanup(database.stop)
        self.engine=FakeEngine()
        engine = patch.dict(self.module.app.extensions, wiki_engine=self.engine)
        engine.start(); self.addCleanup(engine.stop)
        self.client=self.module.app.test_client()

    def login(self, member=1):
        with self.client.session_transaction() as s:
            s.update(user_id=member,user_role='member',user_name='예시 회원',auth_provider='kakao',wiki_csrf='token')

    def test_oauth_returns_to_wiki_and_logout_removes_access(self):
        response=self.client.get('/wiki/w/대문')
        self.assertEqual(response.status_code,302); self.assertIn('/login?next=',response.location)
        self.client.get('/login/kakao?next=/wiki/w/대문')
        with self.client.session_transaction() as s: state=s['oauth_state']
        with patch.object(self.module.KakaoOauth,'get_token',return_value={'access_token':'test'}), \
             patch.object(self.module.KakaoOauth,'get_user_info',return_value={'id':9001,'kakao_account':{'profile':{}}}):
            result=self.client.get('/login/kakao/callback?code=example&state='+state)
        self.assertEqual(result.status_code,302); self.assertIn('/wiki/w/',result.location)
        self.assertEqual(self.client.get('/wiki/w/대문').status_code,200)
        self.client.get('/logout')
        self.assertEqual(self.client.get('/wiki/pages').status_code,302)

    def test_revoke_open_editor_and_selected_term_cannot_grant_edit(self):
        self.login(); self.assertEqual(self.client.get('/wiki/edit/대문').status_code,200)
        self.db.rows['seminar_term_members'][0]['status']='paused'
        with patch.object(self.engine,'save') as save:
            result=self.client.post('/wiki/edit/대문?term_id=current',data={'wiki_csrf':'token','version':'1','content':'x','summary':'x'})
            self.assertEqual(result.status_code,403); save.assert_not_called()
        for path in ['/wiki/w/대문','/wiki/pages','/wiki/history/대문']:
            self.assertEqual(self.client.get(path).status_code,200)
        self.db.rows['members'][0]['account_status']='blocked'
        self.assertEqual(self.client.get('/wiki/w/대문').status_code,403)

    def test_csrf_failure_and_membership_failure_are_closed(self):
        self.login()
        for token, origin in [('', 'http://localhost'),('token','https://evil.example'),('잘못된 토큰','http://localhost')]:
            result=self.client.post('/wiki/edit/대문',data={'wiki_csrf':token,'version':'1','content':'x','summary':'x'},headers={'Origin':origin})
            self.assertEqual(result.status_code,403)
        with patch.object(self.db,'table',side_effect=RuntimeError('lookup failed')):
            self.assertEqual(self.client.get('/wiki/w/대문').status_code,503)

    def test_engine_outage_preserves_posted_draft_at_every_stage(self):
        self.login()
        form = dict(wiki_csrf='token', version='1', content='연결 실패에도 남아야 할 본문', summary='작성 중 요약')
        for stage, action in [('user', 'save'), ('render', 'preview'), ('save', 'save')]:
            with self.subTest(stage=stage), patch.object(self.engine, stage, side_effect=EngineUnavailable('offline')):
                result = self.client.post('/wiki/edit/대문', data=dict(form, action=action))
                self.assertEqual(result.status_code, 503)
                self.assertIn(form['content'], result.get_data(as_text=True))
                self.assertIn(form['summary'], result.get_data(as_text=True))

    def test_dot_segment_titles_cannot_change_internal_endpoint(self):
        self.login()
        with patch.object(self.engine, 'user') as connection:
            for path in ['/wiki/w/..', '/wiki/edit/.', '/wiki/history/a/../b', '/wiki/pages?q=..']:
                self.assertEqual(self.client.get(path).status_code, 400)
            connection.assert_not_called()

    def test_navigation_private_responses_and_native_endpoints_hidden(self):
        self.login()
        response=self.client.get('/wiki/w/대문')
        self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertNotIn('opennamu_session',str(response.headers))
        html=response.get_data(as_text=True)
        self.assertIn('lms_wiki.css',html); self.assertNotIn('theme.css',html)
        self.assertIn('/wiki',html)
        for path in ['/wiki/api/v2/raw/대문','/wiki/login','/wiki/register','/wiki/manager','/wiki/setting','/wiki/image/x']:
            self.assertEqual(self.client.get(path).status_code,404)
        self.assertIn('/wiki/w/',self.client.get('/docs/대문').location)

    def test_rendering_strips_executable_html_and_rewrites_internal_links(self):
        with self.module.app.test_request_context():
            html=str(clean_wiki_html('<script>alert(1)</script><a href="/w/대문">home</a><img src=x onerror=alert(1)><a href="javascript:alert(1)">bad</a><p style="color:pink" onclick="x()">text</p>'))
        self.assertNotIn('script',html); self.assertNotIn('onerror',html); self.assertNotIn('onclick',html)
        self.assertNotIn('style=',html); self.assertIn('/wiki/w/',html)


if __name__=='__main__': unittest.main()
