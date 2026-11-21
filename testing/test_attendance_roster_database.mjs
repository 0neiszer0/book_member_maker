// Run with: node testing/test_attendance_roster_database.mjs <PGlite dist/index.js>
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';

const {PGlite} = await import(pathToFileURL(process.argv[2]).href);
const db = new PGlite();
const migration = name => readFile(new URL('../supabase/migrations/' + name + '.sql', import.meta.url), 'utf8');
const scalar = async (query, params) => (await db.query(query, params)).rows[0].value;

try {
  await db.exec(`
    create role anon; create role authenticated; create role service_role bypassrls;
    create schema storage;
    create table storage.buckets(id text primary key, name text, public boolean,
      file_size_limit bigint, allowed_mime_types text[]);
  `);
  for (const name of [
    '20260501000000_legacy_schema_baseline', '20260508013131_005_special_events',
    '20260720154532_integrated_workflow_boards', '20260721032138_weekly_seminar_absences',
    '20260724040758_add_seminar_no_shows', '20260903103757_seminar_attendance_and_moderators',
    '20260905052040_semester_membership',
  ]) {
    await db.exec(await migration(name));
  }
  await db.exec(`
    insert into members(id,name) values (1,'Officer'), (2,'Member');
    insert into seminar_terms(name,start_date,end_date) values ('Test',current_date-30,current_date+30);
    with days as (select (clock_timestamp() at time zone 'Asia/Seoul')::date today)
    insert into seminar_sessions(term_id,meeting_date,day_type,participation_mode,planned_member_ids,attendance_confirmed_at)
      select t.id, days.today+v.day_offset, v.day_type, v.mode, v.planned, v.confirmed
      from seminar_terms t cross join days cross join (values
        (-1,'thu','absence_only',null::bigint[],null::timestamptz),
        (0,'thu','absence_only',null,null),
        (1,'thu','absence_only',null,null),
        (2,'thu','absence_only',array[2]::bigint[],null),
        (3,'thu','absence_only',null,now()),
        (4,'mon','opt_in',null,null)
      ) v(day_offset,day_type,mode,planned,confirmed);
    insert into seminar_no_shows(session_id,member_id)
      select id,2 from seminar_sessions where day_type='mon';
  `);

  const sql = await migration('20261121040000_attendance_only_rosters');
  await db.exec(sql);
  await db.exec(sql);
  const {rows} = await db.query('select id, participation_mode from seminar_sessions order by meeting_date');
  assert.deepEqual(rows.map(row => row.participation_mode),
    ['absence_only', 'absence_only', 'opt_in', 'absence_only', 'absence_only', 'opt_in']);
  const signature = 'public.apply_seminar_roster(uuid,bigint[],bigint[],bigint[],timestamptz,text,bigint)';
  for (const [role, expected] of [['anon', false], ['authenticated', false], ['service_role', true]]) {
    assert.equal(await scalar("select has_function_privilege($1,$2,'execute') as value", [role, signature]), expected);
  }

  const apply = (id, attendees, previous, updatedAt, mode = 'attendance') =>
    scalar('select public.apply_seminar_roster_for_term($1,$2,$2,$3,$4,$5,1,0) as value',
      [id, attendees, previous, updatedAt, mode]);
  await db.exec('set role service_role');
  const thu = rows[2].id;
  const mon = rows[5].id;
  const first = await apply(thu, [1, 2], [], null);
  assert.equal(first.accepted, true);
  assert.deepEqual(await scalar('select planned_member_ids as value from seminar_sessions where id=$1', [thu]), [1, 2]);
  assert.equal((await apply(thu, [], [1, 2], null)).accepted, false);
  assert.equal((await apply(thu, [], [1, 2], first.updated_at)).accepted, true);
  assert.deepEqual(await scalar('select planned_member_ids as value from seminar_sessions where id=$1', [thu]), []);
  assert.equal((await apply(mon, [1], [], null, 'absence')).accepted, false);
  assert.equal((await apply(mon, [1], [], null)).accepted, true);
  assert.equal(await scalar('select count(*)::int as value from seminar_no_shows where session_id=$1', [mon]), 1);
  assert.equal(await scalar("select count(*)::int as value from seminar_roster_imports where mode='attendance'"), 3);
  console.log('PASS: Thursday and Monday attendance imports, undo, revision checks, migration reruns and no-show preservation');
} catch (error) {
  console.error(error.message, error.where || '');
  process.exitCode = 1;
} finally {
  await db.close();
}
