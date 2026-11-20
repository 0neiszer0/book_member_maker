import importlib
import os
import unittest
from contextlib import contextmanager
from datetime import date, timedelta
from unittest.mock import patch

from testing._fake_supabase import FakeSupabase
from wiki_access import wiki_access, is_officer_title, strip_officer_includes
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
    _seq = 0

    def __init__(self):
        type(self)._seq += 1
        # A unique cache key per instance keeps the /wiki/random TTL cache from
        # leaking titles between tests that swap in different FakeEngine objects.
        self.base_url = 'http://127.0.0.1:5096'
        self.database = 'fake-engine-%d.db' % type(self)._seq

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


class RandomPageTests(RouteTests):
    def test_random_requires_login_like_other_wiki_pages(self):
        response = self.client.get('/wiki/random')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login?next=', response.location)

    def test_random_redirects_to_a_readable_page_never_officer_or_home(self):
        self.login()
        self.engine.titles = lambda client, query, number: (
            ['대문', '운영진:회계 정리', ' 운영진：비밀', '운영진:대문', 'MT', '책크메이트'] if number == 1 else [])
        seen = set()
        with patch('wiki_routes.secrets.choice', side_effect=lambda items: (seen.update(items), items[-1])[1]):
            response = self.client.get('/wiki/random')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(seen, {'MT', '책크메이트'})
        self.assertTrue(response.location.endswith('/wiki/w/%EC%B1%85%ED%81%AC%EB%A9%94%EC%9D%B4%ED%8A%B8'), response.location)
        self.assertEqual(self.client.get(response.location).status_code, 200)

    def test_random_pages_through_all_titles(self):
        self.login()
        calls = []
        def titles(client, query, number):
            calls.append(number)
            return ['문서%d-%d' % (number, i) for i in range(50)] if number == 1 else ['마지막']
        self.engine.titles = titles
        with patch('wiki_routes.secrets.choice', side_effect=lambda items: items[-1]):
            response = self.client.get('/wiki/random')
        self.assertEqual(calls, [1, 2])
        self.assertIn('/wiki/w/%EB%A7%88%EC%A7%80%EB%A7%89', response.location)

    def test_random_with_no_candidates_goes_to_home(self):
        self.login()
        self.engine.titles = lambda *a: ['대문', '운영진:대문']
        response = self.client.get('/wiki/random')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/wiki/w/%EB%8C%80%EB%AC%B8'), response.location)

    def test_random_reuses_cached_titles_within_ttl(self):
        self.login()
        calls = []
        def titles(client, query, number):
            calls.append(number)
            return ['문서%d' % number] if number == 1 else []
        self.engine.titles = titles
        with patch('wiki_routes.secrets.choice', side_effect=lambda items: items[0]):
            self.assertEqual(self.client.get('/wiki/random').status_code, 302)
            self.assertEqual(self.client.get('/wiki/random').status_code, 302)
        self.assertEqual(calls, [1], 'second request must reuse the cached title list')

    def test_random_cache_reapplies_per_request_filters(self):
        self.login()
        calls = []
        def titles(client, query, number):
            calls.append(number)
            return ['공개', '운영진:비밀'] if number == 1 else []
        self.engine.titles = titles
        seen = []
        with patch('wiki_routes.secrets.choice', side_effect=lambda items: (seen.append(list(items)), items[-1])[1]):
            self.client.get('/wiki/random')   # miss: caches the raw list, officer page included
            self.client.get('/wiki/random')   # hit: must still filter the officer page out
        self.assertEqual(calls, [1], 'the cached title list is reused without re-calling titles')
        self.assertEqual(seen, [['공개'], ['공개']], 'officer pages are filtered on every request')

    def test_random_link_is_in_wiki_sidebar(self):
        self.login()
        html = self.client.get('/wiki/w/대문').get_data(as_text=True)
        self.assertIn('href="/wiki/random"', html)
        self.assertIn('랜덤 문서', html)
        self.assertLess(html.index('모든 문서'), html.index('랜덤 문서'))


class OfficerPolicyTests(unittest.TestCase):
    def roster(self, initialized=True):
        db = FakeSupabase(wiki_fixture())
        db.rows['seminar_terms'][0]['operations_initialized_at'] = '2026-09-01' if initialized else None
        db.rows['seminar_terms'].append(dict(id='past', name='2026년 1학기', is_active=True, start_date='2026-03-01',
                                             end_date='2026-06-30', roster_initialized_at='2026-03-01',
                                             operations_initialized_at='2026-03-01'))
        db.rows['operation_roles'] = [dict(id='president', is_active=True), dict(id='planning_member', is_active=True),
                                      dict(id='retired', is_active=False)]
        db.rows['term_officers'] = []
        return db

    def officer(self, db, member=2):
        return wiki_access(db, {'user_id': member, 'auth_provider': 'kakao'}, date(2026, 10, 28)).is_officer

    def test_current_term_officer_roster_decides_officer_pages(self):
        db = self.roster()
        self.assertFalse(self.officer(db))
        db.rows['term_officers'] = [dict(term_id='current', member_id=2, role_id='planning_member')]
        self.assertTrue(self.officer(db))
        access = wiki_access(db, {'user_id': 2, 'auth_provider': 'kakao'}, date(2026, 10, 28))
        self.assertFalse(access.can_edit)  # ordinary pages still follow the semester member roster
        db.rows['members'][1]['is_active'] = False
        self.assertFalse(self.officer(db))

    def test_global_staff_role_or_past_or_inactive_assignment_is_not_enough(self):
        db = self.roster()
        db.rows['members'][1]['role'] = 'officer'
        db.rows['term_officers'] = [dict(term_id='past', member_id=2, role_id='president'),
                                    dict(term_id='current', member_id=2, role_id='retired')]
        self.assertFalse(self.officer(db))

    def test_site_admin_is_always_an_officer(self):
        db = self.roster()
        db.rows['members'][1]['role'] = 'admin'
        self.assertTrue(self.officer(db))
        db.rows['seminar_terms'] = []  # no current term at all
        self.assertTrue(self.officer(db))

    def test_unconfigured_term_keeps_existing_staff_until_roster_is_set(self):
        db = self.roster(initialized=False)
        self.assertFalse(self.officer(db))
        db.rows['members'][1]['role'] = 'officer'
        self.assertTrue(self.officer(db))

    def test_roster_lookup_failure_closes_officer_pages_only(self):
        db = self.roster()
        db.rows['term_officers'] = [dict(term_id='current', member_id=2, role_id='president')]
        original = db.table
        def table(name):
            if name == 'term_officers':
                raise RuntimeError('offline')
            return original(name)
        with patch.object(db, 'table', side_effect=table):
            access = wiki_access(db, {'user_id': 2, 'auth_provider': 'kakao'}, date(2026, 10, 28))
        self.assertIsNotNone(access); self.assertFalse(access.is_officer)

    def test_officer_namespace_detection_and_include_guard(self):
        for title in ['운영진:회계', ' 운영진:회계', '운영진：회계', '운영진:']:
            self.assertTrue(is_officer_title(title), title)
        for title in ['운영진 안내', '대문', '회원:운영진:x']:
            self.assertFalse(is_officer_title(title), title)
        for source in ['[include(운영진:회계)]', '앞 [ INCLUDE ( 운영진：회계 )] 뒤', '[include(운영\\진:회계)]']:
            self.assertNotIn('회계', strip_officer_includes(source).replace('운영진 전용', ''))
        self.assertEqual(strip_officer_includes('[include(틀:안내)]\n[[운영진:회계]]'), '[include(틀:안내)]\n[[운영진:회계]]')


class OfficerRouteTests(RouteTests):
    OFFICER_DOC = '운영진:회계 정리'

    def setUp(self):
        super().setUp()
        self.db.rows['members'].append(dict(id=3, name='운영진 예시', social_id='9003', role='member',
                                            is_active=True, account_status='active', member_status='active'))
        self.db.rows['seminar_terms'][0]['operations_initialized_at'] = '2026-09-01'
        self.db.rows['operation_roles'] = [dict(id='academic_head', is_active=True)]
        self.db.rows['term_officers'] = [dict(term_id='current', member_id=3, role_id='academic_head')]
        self.rendered = []
        engine = self.engine
        engine.titles = lambda *a: ['대문', self.OFFICER_DOC, '운영진:대문']
        engine.render = lambda client, title, source: self.rendered.append(source) or '<p>%s</p>' % source

    def test_member_cannot_read_list_or_edit_officer_pages(self):
        self.login(1)  # roster-active ordinary member
        with patch.object(self.engine, 'document') as document, patch.object(self.engine, 'save') as save:
            for path in ['/wiki/w/' + self.OFFICER_DOC, '/wiki/w/ 운영진:회계 정리', '/wiki/w/운영진：회계 정리',
                         '/wiki/history/' + self.OFFICER_DOC, '/wiki/edit/' + self.OFFICER_DOC]:
                self.assertEqual(self.client.get(path).status_code, 404, path)
            result = self.client.post('/wiki/edit/' + self.OFFICER_DOC,
                                      data={'wiki_csrf': 'token', 'version': '1', 'content': 'x', 'summary': 'x'})
            self.assertEqual(result.status_code, 404)
            self.assertEqual(self.client.get('/wiki/new?title=' + self.OFFICER_DOC).status_code, 403)
            document.assert_not_called(); save.assert_not_called()
        listing = self.client.get('/wiki/pages').get_data(as_text=True)
        self.assertIn('대문', listing); self.assertNotIn('운영진:', listing)
        self.assertNotIn('운영진:', self.client.get('/wiki/pages?q=운영진').get_data(as_text=True))
        self.assertNotIn('운영진 문서', self.client.get('/wiki/w/대문').get_data(as_text=True))

    def test_member_pages_cannot_transclude_officer_pages(self):
        self.login(1)
        with patch.object(self.engine, 'document', return_value=dict(title='대문', version='1', exists=True, history=[],
                                                                      source='[include(운영진:회계 정리)]')):
            self.client.get('/wiki/w/대문')
        self.client.post('/wiki/edit/대문', data={'wiki_csrf': 'token', 'version': '1', 'action': 'preview',
                                                 'content': '[include( 운영진:회계 정리 )]', 'summary': 'x'})
        self.assertEqual(len(self.rendered), 2)
        self.assertTrue(all('include' not in r for r in self.rendered), self.rendered)

    def test_officer_reads_and_edits_officer_pages_without_roster(self):
        self.login(3)  # officer, not on the current-term roster
        response = self.client.get('/wiki/w/' + self.OFFICER_DOC)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('운영진 전용 문서입니다', html); self.assertIn('/wiki/edit/', html)
        self.assertIn(self.OFFICER_DOC, self.client.get('/wiki/pages').get_data(as_text=True))
        self.assertEqual(self.client.get('/wiki/history/' + self.OFFICER_DOC).status_code, 200)
        self.assertEqual(self.client.get('/wiki/edit/' + self.OFFICER_DOC).status_code, 200)
        with patch.object(self.engine, 'save') as save:
            result = self.client.post('/wiki/edit/' + self.OFFICER_DOC,
                                      data={'wiki_csrf': 'token', 'version': '1', 'content': 'x', 'summary': 'x'})
            self.assertEqual(result.status_code, 303); save.assert_called_once()
            # Ordinary pages still follow the current-term roster rule, even for staff.
            self.assertEqual(self.client.post('/wiki/edit/대문', data={'wiki_csrf': 'token', 'version': '1',
                                              'content': 'x', 'summary': 'x'}).status_code, 403)
        self.assertEqual(self.client.get('/wiki/new?title=' + self.OFFICER_DOC).status_code, 302)

    def test_demoted_officer_loses_access_before_save(self):
        self.login(3)
        self.assertEqual(self.client.get('/wiki/edit/' + self.OFFICER_DOC).status_code, 200)
        self.db.rows['term_officers'] = []  # removed from this term's officer roster
        with patch.object(self.engine, 'save') as save:
            result = self.client.post('/wiki/edit/' + self.OFFICER_DOC,
                                      data={'wiki_csrf': 'token', 'version': '1', 'content': 'x', 'summary': 'x'})
            self.assertEqual(result.status_code, 404); save.assert_not_called()


class OfficerNavTests(OfficerRouteTests):
    """'운영진 위키' global nav entry: officers and admins only."""
    LINK = '<span>운영진 위키</span>'

    def nav_html(self):
        self.module.app.extensions['officer_wiki_nav_cache'].clear()
        with self.module.app.test_request_context():
            paths = [self.module.url_for(e) for e in ('help_member', 'club_room', 'lms_calendar')]
        for path in paths:
            response = self.client.get(path)
            html = response.get_data(as_text=True)
            if response.status_code == 200 and 'lms-global' in html:
                return html
        self.fail('no page with the global navigation rendered')

    def test_officer_sees_officer_wiki_link(self):
        self.login(3)
        html = self.nav_html()
        self.assertIn(self.LINK, html)
        self.assertIn('/wiki/w/%EC%9A%B4%EC%98%81%EC%A7%84:%EB%8C%80%EB%AC%B8', html)

    def test_admin_sees_officer_wiki_link(self):
        self.db.rows['members'][0]['role'] = 'admin'
        self.login(1)
        self.assertIn(self.LINK, self.nav_html())

    def test_member_and_anonymous_do_not_see_officer_wiki_link(self):
        self.assertNotIn(self.LINK, self.nav_html())
        self.login(1)
        self.assertNotIn(self.LINK, self.nav_html())
        self.assertNotIn(self.LINK, self.client.get('/wiki/w/대문').get_data(as_text=True))

    def test_officer_wiki_link_hidden_when_wiki_disabled_or_lookup_fails(self):
        self.login(3)
        with patch.dict(self.module.app.config, WIKI_ENABLED=False):
            self.assertNotIn(self.LINK, self.nav_html())
        original = self.db.table
        def table(name):
            if name == 'term_officers':
                raise RuntimeError('offline')
            return original(name)
        with patch.object(self.db, 'table', side_effect=table):
            self.assertNotIn(self.LINK, self.nav_html())

    def test_officer_wiki_link_on_wiki_pages_uses_page_access(self):
        self.login(3)
        self.assertIn(self.LINK, self.client.get('/wiki/w/대문').get_data(as_text=True))


# Inherit RouteTests' fixtures only; its own tests already run once above.
for _name in [n for n in vars(RouteTests) if n.startswith('test_')]:
    setattr(OfficerRouteTests, _name, None)
    setattr(RandomPageTests, _name, None)
for _name in [n for n in vars(OfficerRouteTests) if n.startswith('test_')]:
    setattr(OfficerNavTests, _name, None)


if __name__=='__main__': unittest.main()
