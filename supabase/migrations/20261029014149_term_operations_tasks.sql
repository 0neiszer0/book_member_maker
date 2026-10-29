begin;
set local lock_timeout = '5s';
alter table public.seminar_terms add column operations_initialized_at timestamptz,
  add column operations_revision integer not null default 0;
alter table public.member_inbox add column dismissed_at timestamptz,
  add column operation_key text, add column operation_term_id uuid references public.seminar_terms(id);
create index member_inbox_operation_idx on public.member_inbox(operation_key) where resolved_at is null;

create table public.operation_roles (
 id text primary key check (id ~ '^[a-z][a-z0-9_-]{0,39}$'),
 label text not null check (length(label) between 1 and 40), department text not null default '',
 capabilities text[] not null default '{}' check (capabilities <@ array['members','attendance','tasks']),
 is_active boolean not null default true
);
insert into public.operation_roles(id,label,department,capabilities) values
 ('president','회장','',array['members','tasks']), ('vice_president','부회장','',array['members','tasks']),
 ('treasurer','총무','',array['members','tasks']),
 ('planning_head','기획부장','기획부',array['attendance','tasks']),
 ('academic_head','학술지원부장','학술지원부',array['attendance','tasks']),
 ('publicity_head','홍보부장','홍보부',array['attendance','tasks']),
 ('planning_member','기획부원','기획부','{}'), ('academic_member','학술지원부원','학술지원부','{}'),
 ('publicity_member','홍보부원','홍보부','{}');
create table public.term_officers (
 id uuid primary key default gen_random_uuid(), term_id uuid not null references public.seminar_terms(id),
 member_id bigint not null references public.members(id), role_id text not null references public.operation_roles(id),
 capabilities text[] check (capabilities <@ array['members','attendance','tasks']),
 unique(term_id,member_id,role_id)
);
create index term_officers_member_idx on public.term_officers(member_id,term_id);
create index term_officers_role_idx on public.term_officers(role_id);
create table public.operation_rules (
 id uuid primary key default gen_random_uuid(), term_id uuid not null references public.seminar_terms(id),
 title text not null check (length(title) between 1 and 150), body text not null default '' check (length(body)<=2000),
 frequency text not null check (frequency in ('once','daily','weekly','monthly')),
 start_date date not null, end_date date not null check (end_date>=start_date and end_date-start_date<=740),
 weekday integer not null default 0 check (weekday between 0 and 6), month_day integer not null default 1 check (month_day between 1 and 31),
 hour integer not null default 13 check (hour between 0 and 23),
 role_ids text[] not null default '{}', member_ids bigint[] not null default '{}',
 is_active boolean not null default true, created_by bigint not null references public.members(id), created_at timestamptz not null default now()
);
create index operation_rules_term_idx on public.operation_rules(term_id);
create index operation_rules_creator_idx on public.operation_rules(created_by);
create table public.operation_tasks (
 id uuid primary key default gen_random_uuid(), rule_id uuid not null references public.operation_rules(id),
 term_id uuid not null references public.seminar_terms(id), occurrence_date date not null,
 title text not null, body text not null default '', due_at timestamptz not null,
 completed_at timestamptz, completed_by bigint references public.members(id), unique(rule_id,occurrence_date)
);
create index operation_tasks_open_idx on public.operation_tasks(term_id,due_at) where completed_at is null;
create index operation_tasks_actor_idx on public.operation_tasks(completed_by);
create table public.operation_audit (
 id bigint generated always as identity primary key, actor_id bigint not null references public.members(id),
 term_id uuid references public.seminar_terms(id), action text not null, details jsonb not null,
 created_at timestamptz not null default now()
);
create index operation_audit_term_idx on public.operation_audit(term_id,created_at desc);
create index operation_audit_actor_idx on public.operation_audit(actor_id);

create function public.operation_can(p_actor bigint,p_cap text,p_term uuid default null)
returns boolean language sql stable security invoker set search_path='' as $$
 select exists(select 1 from public.members m where m.id=p_actor and m.is_active
 and m.account_status='active' and coalesce(m.member_status,'') not in ('inactive','blocked')
 and (m.role='admin' or exists(select 1 from public.seminar_terms t
   where (case when p_term is null then (now() at time zone 'Asia/Seoul')::date between t.start_date and t.end_date else t.id=p_term end)
   and ((t.operations_initialized_at is null and m.role='officer') or exists(
     select 1 from public.term_officers a join public.operation_roles r on r.id=a.role_id
     where a.term_id=t.id and a.member_id=m.id and r.is_active and p_cap=any(coalesce(a.capabilities,r.capabilities)))))))
$$;

create function public.save_term_officers(p_term uuid,p_actor bigint,p_revision integer,p_entries jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare t public.seminar_terms%rowtype; e jsonb;
begin
 if not exists(select 1 from public.members where id=p_actor and role='admin' and is_active and account_status='active' and coalesce(member_status,'') not in ('inactive','blocked')) then
   return jsonb_build_object('accepted',false); end if;
 select * into t from public.seminar_terms where id=p_term for update;
 if not found or t.operations_revision<>p_revision then return jsonb_build_object('accepted',false); end if;
 if jsonb_typeof(p_entries)<>'array' or jsonb_array_length(p_entries)>100 then raise exception 'invalid assignments'; end if;
 for e in select value from jsonb_array_elements(p_entries) loop
   if not exists(select 1 from public.members where id=(e->>'member_id')::bigint and is_active and account_status='active' and coalesce(member_status,'') not in ('inactive','blocked'))
      or not exists(select 1 from public.operation_roles where id=e->>'role_id' and is_active) then raise exception 'invalid officer'; end if;
 end loop;
 insert into public.operation_audit(actor_id,term_id,action,details)
 values(p_actor,p_term,'officers',jsonb_build_object('before',(select coalesce(jsonb_agg(to_jsonb(a)),'[]') from public.term_officers a where term_id=p_term),'after',p_entries));
 delete from public.term_officers where term_id=p_term;
 insert into public.term_officers(term_id,member_id,role_id,capabilities)
 select p_term,(item->>'member_id')::bigint,item->>'role_id',case when item->'capabilities' is null or item->'capabilities'='null'::jsonb then null else array(select jsonb_array_elements_text(item->'capabilities')) end
 from jsonb_array_elements(p_entries) as x(item);
 update public.seminar_terms set operations_initialized_at=coalesce(operations_initialized_at,now()),operations_revision=operations_revision+1 where id=p_term;
 return jsonb_build_object('accepted',true,'revision',p_revision+1);
end $$;

create function public.complete_operation_task(p_task uuid,p_actor bigint)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare t public.operation_tasks%rowtype; r public.operation_rules%rowtype;
begin
 select * into t from public.operation_tasks where id=p_task for update;
 if not found then return jsonb_build_object('accepted',false); end if;
 select * into r from public.operation_rules where id=t.rule_id;
 if not r.is_active or not exists(select 1 from public.members m where m.id=p_actor and m.is_active and m.account_status='active' and coalesce(m.member_status,'') not in ('inactive','blocked')
   and (public.operation_can(p_actor,'tasks',t.term_id) or exists(select 1 from public.term_officers a join public.operation_roles d on d.id=a.role_id
     where a.term_id=t.term_id and a.member_id=p_actor and d.is_active and (p_actor=any(r.member_ids) or a.role_id=any(r.role_ids))))) then
   return jsonb_build_object('accepted',false); end if;
 if t.completed_at is null then
   update public.operation_tasks set completed_at=now(),completed_by=p_actor where id=p_task;
   insert into public.operation_audit(actor_id,term_id,action,details) values(p_actor,t.term_id,'task_complete',jsonb_build_object('task_id',p_task));
 end if;
 update public.member_inbox set resolved_at=now() where operation_key='custom:'||p_task::text and resolved_at is null;
 return jsonb_build_object('accepted',true);
end $$;

-- Every batch is all-or-nothing, with optimistic row versions and explicit actor.
create function public.confirm_seminar_attendance_batch(p_actor bigint,p_entries jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare e jsonb; s public.seminar_sessions%rowtype; ids bigint[];
begin
 if jsonb_typeof(p_entries)<>'array' or jsonb_array_length(p_entries) not between 1 and 50 then raise exception 'invalid batch'; end if;
 -- Match roster writes: term locks precede session locks.
 perform 1 from public.seminar_terms where id in (select term_id from public.seminar_sessions where id in
   (select (x->>'session_id')::uuid from jsonb_array_elements(p_entries) x)) order by id for update;
 perform 1 from public.seminar_sessions where id in (select (x->>'session_id')::uuid from jsonb_array_elements(p_entries) x) order by id for update;
 for e in select value from jsonb_array_elements(p_entries) loop
   select * into s from public.seminar_sessions where id=(e->>'session_id')::uuid;
   if not found or not public.operation_can(p_actor,'attendance',s.term_id) or not s.is_active
      or s.meeting_date>(now() at time zone 'Asia/Seoul')::date then raise exception 'attendance not allowed'; end if;
   if exists(select 1 from public.seminar_weeks w where w.id=s.seminar_week_id and coalesce(w.book_title,'')='' and coalesce(w.note,'') ~ '(휴회|휴강|시험기간|중간고사|기말고사)') then raise exception 'break week'; end if;
   -- JSON representation preserves timestamp precision sent by PostgREST.
   if (select roster_revision from public.seminar_terms where id=s.term_id) is distinct from (e->>'expected_term_revision')::integer
      or s.attendance_confirmed_at is distinct from (e->>'expected_confirmed_at')::timestamptz
      or s.roster_updated_at is distinct from (e->>'expected_roster_updated_at')::timestamptz then
     return jsonb_build_object('accepted',false,'conflict',true); end if;
   if jsonb_typeof(e->'member_ids')<>'array' then raise exception 'invalid attendance'; end if;
   ids:=array(select distinct value::bigint from jsonb_array_elements_text(e->'member_ids'));
   if exists(select 1 from unnest(ids) mid where not exists(select 1 from public.members where id=mid)) or
      exists(select 1 from public.seminar_no_shows where session_id=s.id and cancelled_at is null and member_id=any(ids)) then raise exception 'invalid attendees'; end if;
 end loop;
 for e in select value from jsonb_array_elements(p_entries) loop
   select * into s from public.seminar_sessions where id=(e->>'session_id')::uuid;
   ids:=array(select distinct value::bigint from jsonb_array_elements_text(e->'member_ids'));
   insert into public.operation_audit(actor_id,term_id,action,details) values(p_actor,s.term_id,'attendance_confirm',
     jsonb_build_object('session_id',s.id,'before',s.actual_member_ids,'after',ids));
   update public.seminar_sessions set actual_member_ids=ids,attendance_confirmed_at=now() where id=s.id;
   update public.history set actual_member_ids=ids,attendance_confirmed_at=now() where seminar_session_id=s.id;
   update public.member_inbox set resolved_at=now() where operation_key='attendance:'||s.id::text and resolved_at is null;
 end loop;
 return jsonb_build_object('accepted',true,'count',jsonb_array_length(p_entries));
end $$;

alter table public.operation_roles enable row level security;
alter table public.term_officers enable row level security;
alter table public.operation_rules enable row level security;
alter table public.operation_tasks enable row level security;
alter table public.operation_audit enable row level security;
revoke all on public.operation_roles,public.term_officers,public.operation_rules,public.operation_tasks,public.operation_audit from public,anon,authenticated;
grant select,insert,update,delete on public.operation_roles,public.term_officers,public.operation_rules,public.operation_tasks,public.operation_audit to service_role;
grant usage,select on sequence public.operation_audit_id_seq to service_role;
revoke all on function public.operation_can(bigint,text,uuid),public.save_term_officers(uuid,bigint,integer,jsonb),public.complete_operation_task(uuid,bigint),public.confirm_seminar_attendance_batch(bigint,jsonb) from public,anon,authenticated;
grant execute on function public.operation_can(bigint,text,uuid),public.save_term_officers(uuid,bigint,integer,jsonb),public.complete_operation_task(uuid,bigint),public.confirm_seminar_attendance_batch(bigint,jsonb) to service_role;
create or replace function public.account_request_mutate(
  p_action text, p_actor_id bigint default null, p_notification_id bigint default null,
  p_name text default null, p_student_id text default null, p_social_id text default null
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  n public.notifications%rowtype;
  m public.members%rowtype;
  actor public.members%rowtype;
  candidate_count integer;
begin
  -- Small administrative operation: serialize with all member writes, including legacy routes.
  lock table public.members in share row exclusive mode;
  lock table public.notifications in share row exclusive mode;
  if p_action = 'request' then
    if nullif(trim(p_social_id), '') is null or nullif(trim(p_name), '') is null
       or p_student_id is null or p_student_id !~ '^[0-9]{4,20}$' then
      return jsonb_build_object('accepted', false);
    end if;
    select count(*) into candidate_count from public.members where name=p_name and student_id=p_student_id;
    if candidate_count <> 1 then return jsonb_build_object('accepted', false); end if;
    select * into m from public.members where name=p_name and student_id=p_student_id for update;
    if nullif(m.social_id, '') is not null or m.is_active is distinct from true
       or m.member_status in ('inactive','blocked') or coalesce(m.account_status,'') not in ('active','pending')
       or exists(select 1 from public.members where social_id=p_social_id) then
      return jsonb_build_object('accepted', false);
    end if;
    -- At most one unresolved request per target or Kakao identity; reuse only identical requests.
    select * into n from public.notifications where type='account_link_request' and status='pending'
      and (related_member_id=m.id or details->>'pending_social_id'=p_social_id) limit 1;
    if found then
      return jsonb_build_object('accepted', n.related_member_id=m.id and n.details->>'pending_social_id'=p_social_id);
    end if;
    insert into public.notifications(type,status,related_member_id,details)
      values('account_link_request','pending',m.id,jsonb_build_object(
        'pending_social_id',p_social_id,'original_name',m.name,
        'target_name',m.name,'target_student_id',m.student_id,'request_version',1));
    return jsonb_build_object('accepted',true);
  end if;
  if p_action is null or p_action not in ('approve','deny') then return jsonb_build_object('accepted',false); end if;
  select * into actor from public.members where id=p_actor_id for update;
  if not found or not public.operation_can(p_actor_id,'members',null) or actor.is_active is distinct from true
     or actor.account_status is distinct from 'active' or actor.member_status in ('inactive','blocked') then
    return jsonb_build_object('accepted',false);
  end if;
  select * into n from public.notifications where id=p_notification_id for update;
  if not found or n.status <> 'pending' or n.type not in ('account_link_request','new_user_request') then
    return jsonb_build_object('accepted',false);
  end if;
  select * into m from public.members where id=n.related_member_id for update;
  if not found or (m.role in ('admin','officer') and actor.role <> 'admin') then
    return jsonb_build_object('accepted',false);
  end if;
  if n.type='account_link_request' then
    if n.details->>'request_version' is distinct from '1' or nullif(n.details->>'pending_social_id','') is null
       or nullif(m.social_id,'') is not null then return jsonb_build_object('accepted',false); end if;
    if p_action='approve' then
      if m.name is distinct from n.details->>'target_name' or m.student_id is distinct from n.details->>'target_student_id'
         or m.is_active is distinct from true or m.member_status in ('inactive','blocked')
         or coalesce(m.account_status,'') not in ('active','pending')
         or exists(select 1 from public.members where social_id=n.details->>'pending_social_id') then
        return jsonb_build_object('accepted',false);
      end if;
      update public.members set social_id=n.details->>'pending_social_id', account_status='active' where id=m.id;
    end if;
  else
    -- An old signup notification must never delete an already approved/promoted account.
    if m.role is distinct from 'member' or m.account_status is distinct from 'pending'
       or m.is_active is distinct from true or m.member_status in ('inactive','blocked') then
      return jsonb_build_object('accepted',false);
    end if;
    if p_action='approve' then update public.members set account_status='active' where id=m.id;
    else delete from public.members where id=m.id;
    end if;
  end if;
  update public.notifications set status=case when p_action='approve' then 'approved' else 'denied' end,
    details=coalesce(details,'{}'::jsonb)-'pending_social_id'-'target_student_id'
    where id=n.id and status='pending';
  update public.member_inbox set resolved_at=now() where event_key='request:'||n.id::text and resolved_at is null;
  return jsonb_build_object('accepted',true);
end $$;
revoke all on function public.account_request_mutate(text,bigint,bigint,text,text,text) from public,anon,authenticated;
grant execute on function public.account_request_mutate(text,bigint,bigint,text,text,text) to service_role;


CREATE OR REPLACE FUNCTION public.save_seminar_term_members(p_term_id uuid, p_revision integer, p_entries jsonb, p_actor bigint)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_term public.seminar_terms%ROWTYPE;
  v_previous jsonb;
  v_entries jsonb;
BEGIN
  IF NOT public.operation_can(p_actor,'members',p_term_id) THEN RETURN jsonb_build_object('accepted',false,'reason','forbidden'); END IF;
  SELECT * INTO v_term FROM public.seminar_terms WHERE id = p_term_id FOR UPDATE;
  IF NOT FOUND OR v_term.roster_revision IS DISTINCT FROM p_revision THEN
    RETURN jsonb_build_object('accepted', false, 'reason', 'conflict');
  END IF;
  IF p_entries IS NULL OR jsonb_typeof(p_entries) <> 'array' THEN
    RAISE EXCEPTION 'Invalid roster';
  END IF;
  IF jsonb_array_length(p_entries) > 5000 OR EXISTS (
    SELECT 1 FROM jsonb_to_recordset(p_entries) AS r(member_id bigint, status text, entry_type text)
    WHERE r.member_id IS NULL OR r.status IS NULL OR r.entry_type IS NULL
      OR r.status NOT IN ('active','paused','left') OR r.entry_type NOT IN ('continuing','new','returning')
      OR NOT EXISTS (SELECT 1 FROM public.members m WHERE m.id = r.member_id)
  ) OR EXISTS (
    SELECT 1 FROM jsonb_to_recordset(p_entries) AS r(member_id bigint) GROUP BY member_id HAVING count(*) > 1
  ) THEN
    RAISE EXCEPTION 'Invalid roster entries';
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('member_id', member_id, 'status', status, 'entry_type', entry_type) ORDER BY member_id), '[]'::jsonb)
    INTO v_previous FROM public.seminar_term_members WHERE term_id = p_term_id;
  -- Omitted previous participants are retained as ended, never erased.
  UPDATE public.seminar_term_members SET status = 'left', updated_at = now()
    WHERE term_id = p_term_id AND member_id NOT IN (SELECT r.member_id FROM jsonb_to_recordset(p_entries) AS r(member_id bigint));
  INSERT INTO public.seminar_term_members(term_id, member_id, status, entry_type)
    SELECT p_term_id, r.member_id, r.status, r.entry_type FROM jsonb_to_recordset(p_entries) AS r(member_id bigint, status text, entry_type text)
    ON CONFLICT (term_id, member_id) DO UPDATE SET status = excluded.status, entry_type = excluded.entry_type, updated_at = now();
  UPDATE public.seminar_terms SET roster_revision = roster_revision + 1,
    roster_initialized_at = coalesce(roster_initialized_at, now()) WHERE id = p_term_id;
  SELECT coalesce(jsonb_agg(jsonb_build_object('member_id', member_id, 'status', status, 'entry_type', entry_type) ORDER BY member_id), '[]'::jsonb)
    INTO v_entries FROM public.seminar_term_members WHERE term_id = p_term_id;
  INSERT INTO public.seminar_term_roster_changes(term_id, revision, previous_entries, entries, created_by)
    VALUES (p_term_id, p_revision + 1, v_previous, v_entries, p_actor);
  UPDATE public.member_inbox SET resolved_at=now() WHERE operation_key='roster:'||p_term_id::text AND resolved_at IS NULL;
  RETURN jsonb_build_object('accepted', true, 'revision', p_revision + 1);
END $$;
REVOKE ALL ON FUNCTION public.save_seminar_term_members(uuid, integer, jsonb, bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.save_seminar_term_members(uuid, integer, jsonb, bigint) TO service_role;

CREATE OR REPLACE FUNCTION public.apply_seminar_roster_for_term(
  p_session_id uuid, p_member_ids bigint[], p_expected_member_ids bigint[],
  p_previous_member_ids bigint[], p_previous_updated_at timestamptz,
  p_mode text, p_created_by bigint, p_term_revision integer
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE v_revision integer;
BEGIN
  IF NOT public.operation_can(p_created_by,'attendance',(SELECT term_id FROM public.seminar_sessions WHERE id=p_session_id)) THEN RETURN jsonb_build_object('accepted',false,'reason','forbidden'); END IF;
  SELECT t.roster_revision INTO v_revision FROM public.seminar_terms t
    JOIN public.seminar_sessions s ON s.term_id = t.id WHERE s.id = p_session_id FOR UPDATE OF t;
  IF NOT FOUND OR v_revision IS DISTINCT FROM p_term_revision THEN
    RETURN jsonb_build_object('accepted', false, 'reason', 'term_conflict');
  END IF;
  RETURN public.apply_seminar_roster(p_session_id, p_member_ids, p_expected_member_ids,
    p_previous_member_ids, p_previous_updated_at, p_mode, p_created_by);
END $$;
REVOKE ALL ON FUNCTION public.apply_seminar_roster_for_term(uuid,bigint[],bigint[],bigint[],timestamptz,text,bigint,integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.apply_seminar_roster_for_term(uuid,bigint[],bigint[],bigint[],timestamptz,text,bigint,integer) TO service_role;
commit;
