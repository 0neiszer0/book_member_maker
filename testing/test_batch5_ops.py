import importlib
import os
import subprocess
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from postgrest.exceptions import APIError

from testing._fake_supabase import FakeSupabase


os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
os.environ.setdefault('FLASK_SECRET_KEY', 'synthetic-batch5-test')
os.environ.setdefault('SUPABASE_URL', 'http://127.0.0.1:9')
os.environ.setdefault('SUPABASE_SERVICE_KEY', 'synthetic-batch5-test')

ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = '10000000-0000-0000-0000-000000000001'
CLOSED = '10000000-0000-0000-0000-000000000002'
TOKEN = '20000000-0000-0000-0000-000000000001'
APPLICANT_ROOT = '30000000-0000-0000-0000-00000000000'
ACCEPTED = APPLICANT_ROOT + '1'
REJECTED = APPLICANT_ROOT + '2'
CSRF = {'X-App-CSRF': 'batch5-csrf'}
DUES_URL = f'/api/admin/recruitment-results/{CAMPAIGN}'
MEMBER_PURGE = '/api/admin/privacy/purge-inactive-members'
APPLICANT_PURGE = '/api/admin/privacy/purge-recruitment-applicants'
CONFIRM = {'confirm': '파기 확인'}


def member(member_id, role):
    return dict(id=member_id, name=f'Member {member_id}', role=role, account_status='active',
                member_status='active', auth_provider='kakao', auth_session_version=7,
                social_id=f'kakao-{member_id}', is_active=True)


class BatchOpsDB(FakeSupabase):
    def __init__(self):
        super().__init__({
            'members': [member(1, 'admin'), member(2, 'officer'), member(3, 'member'), member(4, 'officer')],
            'recruitment_campaigns': [
                dict(id=CAMPAIGN, share_token=TOKEN, title='Open campaign', is_active=True,
                     is_published=True, dues_account_info='Test Bank 9371', dues_amount='15,000원',
                     dues_contact_phone='010-1234-9371', dues_guide_note='Test dues note'),
            ],
            'recruitment_applicants': [
                dict(id=APPLICANT_ROOT + str(number), campaign_id=CAMPAIGN, name=f'Tester {number}',
                     name_key=f'tester{number}', student_id=f'2026000{number}', result_status=status,
                     dues_paid_at=None)
                for number, status in enumerate(('accepted', 'rejected', 'waitlisted', 'pending'), 1)
            ],
        })
        self.rpc_results = {
            'privacy_cleanup_summary': {
                'inactive_count': 1, 'inactive_preview': [{'id': 42, 'recruiting_class': 7}],
                'campaigns': [{'id': CLOSED, 'title': 'Closed campaign', 'applicant_count': 4, 'rejected_count': 2}],
            },
            'purge_inactive_member_privacy': 1,
            'purge_recruitment_applicant_privacy': {'state': 'success', 'purged_count': 2},
        }

    def rpc(self, name, params):
        self.calls.append(('rpc', name, params, {}))

        def execute():
            result = self.rpc_results[name]
            if isinstance(result, APIError):
                raise result
            return SimpleNamespace(data=result)

        return SimpleNamespace(execute=execute)


class Batch5RoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('app')

    def setUp(self):
        self.db = BatchOpsDB()
        self.app = self.module.app
        for patcher in (patch.dict(self.app.config, TESTING=True, REQUIRE_ORIGIN_AUTH=False),
                        patch.object(self.module, 'supabase', self.db)):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = self.app.test_client()

    def login(self, member_id):
        row = self.db.rows['members'][member_id - 1]
        with self.client.session_transaction() as state:
            state.clear()
            state.update(user_id=member_id, user_role=row['role'], auth_provider=row['auth_provider'],
                         sensitive_csrf=CSRF['X-App-CSRF'], auth_session_version=row['auth_session_version'])

    def post(self, url, data):
        return self.client.post(url, json=data, headers=CSRF)

    def set_email(self, member_id, value):
        return self.post(f'/api/admin/members/{member_id}/knu-email', {'knu_email': value})

    def test_all_new_posts_require_csrf(self):
        self.login(1)
        posts = {
            '/api/admin/members/2/knu-email': {'knu_email': 'a@knu.ac.kr'},
            f'{DUES_URL}/dues-settings': {'dues_amount': '1000'},
            f'{DUES_URL}/applicants/{ACCEPTED}/dues': {},
            MEMBER_PURGE: CONFIRM,
            APPLICANT_PURGE: dict(CONFIRM, campaign_id=CLOSED, scope='all'),
        }
        for url, payload in posts.items():
            for headers in ({}, {'X-App-CSRF': 'forged'}):
                with self.subTest(url=url, headers=headers):
                    self.assertEqual(self.client.post(url, json=payload, headers=headers).status_code, 403)
        self.assertEqual(self.db.calls, [])

    def test_only_primary_can_provision_another_staff_members_email(self):
        self.login(2)
        self.assertEqual(self.set_email(1, 'admin@knu.ac.kr').status_code, 403)
        self.assertEqual(self.set_email(4, 'other@knu.ac.kr').status_code, 403)
        self.assertEqual(self.set_email(3, ' Member ').get_json()['knu_email'], 'member@knu.ac.kr')
        self.assertEqual(self.set_email(2, '  STAFF@KNU.AC.KR  ').get_json()['knu_email'], 'staff@knu.ac.kr')
        officer = self.db.rows['members'][1]
        self.assertEqual(officer['auth_provider'], 'local')
        self.assertEqual(officer['auth_session_version'], 8)
        self.assertIsNone(officer['pin_hash'])
        self.assertEqual(datetime.fromisoformat(officer['knu_email_verified_at']).utcoffset(), timedelta())
        self.assertEqual(self.set_email(3, 'another@knu.ac.kr').status_code, 401)
        self.login(1)
        self.assertEqual(self.set_email(4, 'other@knu.ac.kr').status_code, 200)

    def test_email_validation_conflict_and_clear(self):
        self.login(1)
        target = self.db.rows['members'][2]
        target.update(knu_email='member@knu.ac.kr', knu_email_verified_at='verified', pin_hash='secret-pin',
                      pin_failed_attempts=4, pin_locked_until='locked')
        for invalid in ('user@gmail.com', 'a@knu.ac.kr.fake', '@knu.ac.kr', '한글@knu.ac.kr', False, None):
            with self.subTest(invalid=invalid):
                self.assertEqual(self.set_email(3, invalid).status_code, 400)
        self.assertEqual(self.set_email(99, 'a@knu.ac.kr').status_code, 404)
        with patch('testing._fake_supabase.FakeQuery.update') as update:
            update.return_value.eq.return_value = update.return_value
            update.return_value.execute.side_effect = APIError(
                {'code': '23505', 'message': 'Synthetic duplicate email'},
            )
            self.assertEqual(self.set_email(2, 'member@knu.ac.kr').status_code, 409)
        self.assertEqual(target['auth_session_version'], 7)
        self.assertEqual(self.set_email(3, '').status_code, 200)
        for field in ('knu_email', 'knu_email_verified_at', 'pin_hash', 'pin_locked_until'):
            self.assertIsNone(target[field])
        self.assertEqual(target['pin_failed_attempts'], 0)
        self.assertEqual(target['auth_session_version'], 8)

    def test_member_management_displays_email_controls_with_role_boundaries(self):
        self.login(2)
        body = self.client.get('/admin/members').get_data(as_text=True)
        self.assertIn('/admin/privacy', body)
        self.assertIn('/api/admin/members/2/knu-email', body)
        self.assertIn('/api/admin/members/3/knu-email', body)
        self.assertNotIn('/api/admin/members/1/knu-email', body)
        self.assertNotIn('/api/admin/members/4/knu-email', body)

    def test_officer_can_save_settings_and_toggle_accepted_applicant_dues(self):
        self.login(2)
        listing = self.client.get('/admin/recruitment-results').get_data(as_text=True)
        for label in ('합격자 회비 입금 안내 설정', '미입금 합격자만 보기', 'Test Bank 9371'):
            self.assertIn(label, listing)
        self.assertEqual(self.post(f'{DUES_URL}/dues-settings', {'dues_amount': 1000}).status_code, 400)
        self.assertEqual(self.post('/api/admin/recruitment-results/' + CLOSED + '/dues-settings',
                                   {'dues_amount': '1000'}).status_code, 404)
        self.assertEqual(self.post(f'{DUES_URL}/dues-settings', {
            'dues_amount': ' 20,000원 ', 'dues_guide_note': '',
        }).status_code, 200)
        campaign = self.db.rows['recruitment_campaigns'][0]
        self.assertEqual(campaign['dues_amount'], '20,000원')
        self.assertIsNone(campaign['dues_guide_note'])
        self.assertEqual(campaign['dues_account_info'], 'Test Bank 9371')

        roster = self.client.get(f'{DUES_URL}/dues')
        self.assertIn('no-store', roster.headers['Cache-Control'])
        self.assertEqual([row['id'] for row in roster.get_json()['applicants']], [ACCEPTED])
        wrong_campaign = f'/api/admin/recruitment-results/{CLOSED}/applicants/{ACCEPTED}/dues'
        self.assertEqual(self.post(wrong_campaign, {}).status_code, 404)
        self.assertEqual(self.post(f'{DUES_URL}/applicants/{REJECTED}/dues', {}).status_code, 409)
        toggle_url = f'{DUES_URL}/applicants/{ACCEPTED}/dues'
        paid = self.post(toggle_url, {}).get_json()
        self.assertTrue(paid['dues_paid'])
        self.assertEqual(datetime.fromisoformat(paid['dues_paid_at']).utcoffset(), timedelta())
        row = self.db.rows['recruitment_applicants'][0]
        self.assertEqual(row['dues_checked_by'], 2)
        self.assertEqual(row['dues_paid_at'], paid['dues_paid_at'])
        unpaid = self.post(toggle_url, {}).get_json()
        self.assertFalse(unpaid['dues_paid'])
        self.assertIsNone(unpaid['dues_paid_at'])
        self.assertIsNone(row['dues_checked_by'])

    def test_public_dues_information_is_only_returned_after_accepted_exact_match(self):
        url = f'/applicant-result/{TOKEN}'
        self.db.rows['recruitment_applicants'][0]['dues_paid_at'] = '2026-11-21T00:00:00Z'
        private_values = ('회비 입금 안내', 'Test Bank 9371', '010-1234-9371', 'Test dues note',
                          '15,000원', '회비 입금 확인 완료', '계좌 복사')
        public = self.client.get(url)
        self.assertIn('no-store', public.headers['Cache-Control'])
        for value in private_values:
            self.assertNotIn(value, public.get_data(as_text=True))
        for number in (2, 3, 4, 5, 1):
            name = f'Tester {number}' if number != 5 else 'wrong name'
            student_id = '20260001' if number == 5 else f'2026000{number}'
            body = self.client.post(url, data={'name': name, 'student_id': student_id}).get_data(as_text=True)
            for value in private_values:
                with self.subTest(number=number, value=value):
                    self.assertEqual(value in body, number == 1)
        self.db.rows['recruitment_applicants'][0]['dues_paid_at'] = None
        body = self.client.post(url, data={'name': 'Tester 1', 'student_id': '20260001'}).get_data(as_text=True)
        self.assertIn('회비 입금 안내', body)
        self.assertNotIn('회비 입금 확인 완료', body)
        self.db.rows['recruitment_campaigns'][0].update(dues_account_info=None, dues_contact_phone=None)
        body = self.client.post(url, data={'name': 'Tester 1', 'student_id': '20260001'}).get_data(as_text=True)
        self.assertNotIn('회비 입금 안내', body)
        self.assertNotIn('Test dues note', body)
        self.db.rows['recruitment_campaigns'][0].update(dues_contact_phone='010-1234-9371', is_published=False)
        body = self.client.post(url, data={'name': 'Tester 1', 'student_id': '20260001'}).get_data(as_text=True)
        self.assertNotIn('010-1234-9371', body)

    def test_regular_cannot_access_admin_tools(self):
        self.login(3)
        self.assertEqual(self.set_email(3, 'a@knu.ac.kr').status_code, 403)
        self.assertEqual(self.post(f'{DUES_URL}/dues-settings', {'dues_amount': '1000'}).status_code, 403)
        self.assertEqual(self.client.get(f'{DUES_URL}/dues').status_code, 403)
        self.assertEqual(self.post(MEMBER_PURGE, CONFIRM).status_code, 403)
        self.assertEqual(self.client.get('/admin/privacy').status_code, 302)

    def test_privacy_summary_and_exact_confirmation_are_separate_from_purge_privilege(self):
        self.login(2)
        summary = self.client.get('/admin/privacy')
        self.assertEqual(summary.status_code, 200)
        self.assertIn('no-store', summary.headers['Cache-Control'])
        body = summary.get_data(as_text=True)
        self.assertIn('ID #42 · 7기 · 비활성', body)
        self.assertIn('불합격 2명 · 전체 4명', body)
        self.assertNotIn(MEMBER_PURGE, body)
        self.assertNotIn('kakao-2', body)
        self.assertEqual(self.post(MEMBER_PURGE, CONFIRM).status_code, 403)
        self.assertEqual(self.post(APPLICANT_PURGE, dict(CONFIRM, campaign_id=CLOSED, scope='all')).status_code, 403)
        self.assertEqual([call[1] for call in self.db.calls if call[0] == 'rpc'], ['privacy_cleanup_summary'])
        self.login(1)
        self.assertIn(MEMBER_PURGE, self.client.get('/admin/privacy').get_data(as_text=True))
        for invalid in ({}, {'confirm': '파기 확인 '}, ['파기 확인']):
            self.assertEqual(self.post(MEMBER_PURGE, invalid).status_code, 400)
        self.assertEqual(self.post(MEMBER_PURGE, CONFIRM).get_json()['purged_count'], 1)
        for invalid in ({}, {'confirm': '파기 확인 '}, dict(CONFIRM, campaign_id='invalid', scope='all'),
                        dict(CONFIRM, campaign_id=CLOSED, scope='active')):
            self.assertEqual(self.post(APPLICANT_PURGE, invalid).status_code, 400)
        valid = dict(CONFIRM, campaign_id=CLOSED, scope='rejected')
        self.assertEqual(self.post(APPLICANT_PURGE, valid).get_json()['purged_count'], 2)
        self.assertEqual(self.db.calls[-1][2], {'p_campaign': CLOSED, 'p_scope': 'rejected'})
        for state, status in (('missing', 404), ('active', 409)):
            self.db.rpc_results['purge_recruitment_applicant_privacy'] = {'state': state}
            self.assertEqual(self.post(APPLICANT_PURGE, dict(valid, scope='all')).status_code, status)

    def test_privacy_errors_do_not_log_database_details(self):
        self.login(1)
        secret = 'private-email@knu.ac.kr'
        self.db.rpc_results['purge_inactive_member_privacy'] = APIError({'message': secret})
        with self.assertLogs(self.app.logger, level='ERROR') as logs:
            result = self.post(MEMBER_PURGE, CONFIRM)
        self.assertEqual(result.status_code, 500)
        self.assertNotIn(secret, result.get_data(as_text=True))
        self.assertNotIn(secret, '\n'.join(logs.output))


class Batch5MigrationTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('KNU_TEST_PGLITE_MODULE'), 'Set KNU_TEST_PGLITE_MODULE to a local PGlite module')
    def test_migration_reapplies_and_privacy_purges_are_atomic_and_scoped(self):
        program = r"""
const {readFileSync} = require('node:fs');
const assert = require('node:assert/strict');
const {PGlite} = require(process.env.KNU_TEST_PGLITE_MODULE);
const db = new PGlite();
const [openCampaign, closedCampaign] = process.argv.slice(1);
const sql = name => readFileSync('supabase/migrations/' + name + '.sql', 'utf8');
const value = async (query, params) => (await db.query(query, params)).rows[0].value;

(async () => {
  await db.exec(`
    create role anon; create role authenticated; create role service_role bypassrls;
    create schema storage;
    create table storage.buckets(id text primary key, name text, public boolean,
      file_size_limit bigint, allowed_mime_types text[]);
  `);
  for (const name of [
    '20260501000000_legacy_schema_baseline',
    '20260720154532_integrated_workflow_boards',
    '20260813082022_recruitment_results',
    '20260905052040_semester_membership',
    '20261101010000_local_password_login',
  ]) await db.exec(sql(name));
  // Apply the notification schema before its unrelated historical session cleanup.
  await db.exec(sql('20261028102247_lms_notifications_and_board_content')
    .split('-- Hide only untouched')[0] + 'commit;');
  await db.exec('create table public.term_officers (member_id bigint not null);');
  await db.exec(sql('20261120120000_knu_email_pin_auth'));
  const migration = sql('20261121020000_recruitment_dues_and_privacy');
  await db.exec(migration);
  await db.exec(migration);
  for (const role of ['anon', 'authenticated', 'service_role']) {
    const allowed = role === 'service_role';
    for (const signature of ['privacy_cleanup_summary()', 'purge_inactive_member_privacy()',
      'purge_recruitment_applicant_privacy(uuid,text)']) {
      assert.equal(await value("select has_function_privilege($1,$2,'execute') as value", [role, signature]), allowed);
    }
    assert.equal(await value("select has_table_privilege($1,'inactive_member_privacy_candidates','select') as value", [role]), allowed);
    assert.equal(await value("select has_table_privilege($1,'recruitment_applicants','select') as value", [role]), allowed);
  }
  await db.exec(`
    insert into members (id, name, role, member_status, is_active, recruiting_class, email, knu_email,
      knu_email_verified_at, student_id, social_id, pin_hash, pin_failed_attempts, pin_locked_until)
    values
      (1,'Inactive','member','inactive',true,7,'private@example.test','private@knu.ac.kr',now(),
       '20260001','private-social','$argon2id$synthetic',5,now()),
      (2,'Disabled','member','active',false,8,null,null,null,null,null,null,0,null),
      (3,'Active','member','active',true,9,'active@example.test',null,null,null,null,null,0,null),
      (4,'Officer','officer','inactive',false,9,'officer@example.test',null,null,null,null,null,0,null),
      (5,'Admin','admin','inactive',false,9,'admin@example.test',null,null,null,null,null,0,null),
      (6,'Archive','member','blocked',false,null,null,null,null,null,'system:cafe-archive',null,0,null),
      (7,'Empty','member','inactive',false,null,null,null,null,null,null,null,0,null),
      (8,'Checker','officer','active',true,null,null,null,null,null,null,null,0,null);
    insert into member_credentials(member_id,login_id,password_hash,status)
      select id,'test' || id,'$argon2id$synthetic','active' from members where id between 1 and 5;
    insert into account_setup_tokens(member_id,token_hash,expires_at)
      select id,repeat(id::text,64),now() from members where id between 1 and 5;
    insert into push_subscriptions(member_id,endpoint_hash,endpoint,p256dh,auth)
      select id,repeat(id::text,64),'https://push.example.test/' || id,'key','token' from members where id between 1 and 5;
    insert into history(date,groups) values ('2026-11-21','[["Inactive"]]');
    insert into attendance(user_id,meeting_date) values (1,'2026-11-21');
    insert into topic_submissions(author_name,department,pin_code,topics) values ('Inactive','Test','test','[]');
    insert into recruitment_campaigns(id,title,is_active,dues_account_info,dues_contact_phone)
    values ('${openCampaign}','Open',true,'Account','010-1234-5678'),
           ('${closedCampaign}','Closed',false,null,null);
    insert into recruitment_applicants(campaign_id,name,name_key,student_id,result_status,dues_checked_by,knu_email)
    values ('${openCampaign}','First','first','20260011','accepted',8,'a@knu.ac.kr'),
           ('${openCampaign}','Second','second','20260012','rejected',null,null),
           ('${closedCampaign}','Third','third','20260013','accepted',null,null),
           ('${closedCampaign}','Fourth','fourth','20260014','rejected',null,null);
  `);
  await assert.rejects(db.exec("update recruitment_applicants set knu_email='bad@elsewhere.test'"), {code:'23514'});
  await assert.rejects(db.exec("update members set knu_email='private@knu.ac.kr' where id=3"), {code:'23505'});
  await db.exec('delete from members where id=8');
  assert.equal(await value("select dues_checked_by as value from recruitment_applicants where name_key='first'"), null);

  await db.exec('set role service_role');
  const summary = await value('select public.privacy_cleanup_summary() as value');
  assert.deepEqual(summary, {
    inactive_count: 2,
    inactive_preview: [{id: 1, recruiting_class: 7}, {id: 2, recruiting_class: 8}],
    campaigns: [{id: closedCampaign, title: 'Closed', applicant_count: 2, rejected_count: 1}],
  });
  await db.exec(`
    reset role;
    create function public.test_fail_purge() returns trigger language plpgsql as $$
    begin raise exception 'synthetic purge failure'; end $$;
    create trigger test_fail_purge before delete on public.push_subscriptions
      for each row execute function public.test_fail_purge();
    set role service_role;
  `);
  await assert.rejects(value('select public.purge_inactive_member_privacy() as value'), /synthetic purge failure/);
  assert.equal(await value('select email as value from members where id=1'), 'private@example.test');
  assert.equal(await value('select count(*)::int as value from member_credentials where member_id in (1,2)'), 2);
  await db.exec('reset role; drop trigger test_fail_purge on public.push_subscriptions; set role service_role');

  assert.equal(Number(await value('select public.purge_inactive_member_privacy() as value')), 2);
  const {rows: cleared} = await db.query(`
    select id,recruiting_class,email,knu_email,knu_email_verified_at,student_id,social_id,
           pin_hash,pin_failed_attempts,pin_locked_until,auth_session_version
    from members where id in (1,2) order by id
  `);
  assert.deepEqual(cleared, [[1,7],[2,8]].map(([id,recruiting_class]) => ({
    id,recruiting_class,email:null,knu_email:null,knu_email_verified_at:null,student_id:null,social_id:null,
    pin_hash:null,pin_failed_attempts:0,pin_locked_until:null,auth_session_version:1,
  })));
  for (const table of ['member_credentials','account_setup_tokens','push_subscriptions']) {
    assert.deepEqual(await value(`select array_agg(member_id order by member_id) as value from ${table}`), [3,4,5]);
  }
  assert.deepEqual(await value("select array_agg(email order by id) as value from members where id between 3 and 5"),
    ['active@example.test','officer@example.test','admin@example.test']);
  assert.equal(await value("select social_id as value from members where id=6"), 'system:cafe-archive');
  assert.equal(await value("select auth_session_version as value from members where id=7"), 0);
  assert.equal(Number(await value('select public.purge_inactive_member_privacy() as value')), 0);
  await db.exec('reset role');
  for (const table of ['history','attendance','topic_submissions']) {
    assert.equal(await value(`select count(*)::int as value from ${table}`), 1);
  }
  await db.exec('set role service_role');
  const purge = (campaign, scope) => value('select public.purge_recruitment_applicant_privacy($1,$2) as value', [campaign,scope]);
  assert.deepEqual(await purge(openCampaign, 'all'), {state:'active'});
  assert.deepEqual(await purge(openCampaign, 'rejected'), {state:'success',purged_count:1});
  assert.deepEqual(await purge(closedCampaign, 'rejected'), {state:'success',purged_count:1});
  assert.deepEqual(await purge(closedCampaign, 'all'), {state:'success',purged_count:1});
  assert.deepEqual(await purge(closedCampaign, 'all'), {state:'success',purged_count:0});
  assert.equal(await value("select count(*)::int as value from recruitment_applicants where result_status='accepted'"), 1);
  await db.close();
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run(
            ['node', '-e', program, CAMPAIGN, CLOSED], cwd=ROOT, capture_output=True,
            text=True, encoding='utf-8', timeout=40,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
