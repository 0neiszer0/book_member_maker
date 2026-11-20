begin;
set local lock_timeout = '5s';

alter table public.members
  add column if not exists knu_email text
    check (knu_email ~ '^[a-z0-9._%+-]+@knu\.ac\.kr$'),
  add column if not exists knu_email_verified_at timestamptz,
  add column if not exists pin_hash text check (pin_hash like '$argon2id$%'),
  add column if not exists pin_failed_attempts integer not null default 0 check (pin_failed_attempts >= 0),
  add column if not exists pin_locked_until timestamptz;

create unique index if not exists members_knu_email_uidx on public.members (knu_email)
  where knu_email is not null and btrim(knu_email) <> '';

create table if not exists public.email_auth_codes (
  id uuid primary key default gen_random_uuid(),
  email text not null check (email ~ '^[a-z0-9._%+-]+@knu\.ac\.kr$'),
  purpose text not null check (purpose in ('login', 'signup', 'pin_reset')),
  code_hash text not null check (code_hash ~ '^[0-9a-f]{64}$'),
  attempts integer not null default 0 check (attempts between 0 and 5),
  expires_at timestamptz not null,
  consumed_at timestamptz,
  finalized_at timestamptz,
  client_ip text,
  created_at timestamptz not null default now()
);
create index if not exists email_auth_codes_purpose_idx
  on public.email_auth_codes (email, purpose, created_at desc);
create index if not exists email_auth_codes_email_idx
  on public.email_auth_codes (email, created_at desc);
create index if not exists email_auth_codes_client_idx
  on public.email_auth_codes (client_ip, created_at desc);

alter table public.email_auth_codes enable row level security;
revoke all on public.email_auth_codes from public, anon, authenticated;
grant select, insert, update, delete on public.email_auth_codes to service_role;

alter table public.signup_codes
  add column if not exists expires_at timestamptz,
  add column if not exists auto_approve_until timestamptz;

-- The roster helper uses the same table and revision as the existing roster editor.
grant select (id, is_active, start_date, end_date, roster_revision), update (roster_revision)
  on public.seminar_terms to service_role;

-- Keep the legacy password signup and the school-email flow from claiming the
-- same roster row or concurrently creating two accounts for one student ID.
create or replace function public.guard_local_signup_identity()
returns trigger language plpgsql security invoker set search_path = '' as $$
declare
  v_student_id text;
  v_email text;
begin
  if tg_table_name = 'members' then
    v_student_id := regexp_replace(new.student_id, '\s+', '', 'g');
    perform pg_advisory_xact_lock(62003, hashtext(v_student_id));
    if exists (select 1 from public.members where regexp_replace(student_id, '\s+', '', 'g') = v_student_id) then
      raise unique_violation using message = 'Student ID already has a member record';
    end if;
  else
    select knu_email into v_email from public.members where id = new.member_id for no key update;
    if v_email is not null then
      raise unique_violation using message = 'Member already has a school email login';
    end if;
  end if;
  return new;
end $$;

drop trigger if exists guard_new_local_member on public.members;
create trigger guard_new_local_member before insert on public.members for each row
  when (new.auth_provider = 'local' and new.student_id is not null)
  execute function public.guard_local_signup_identity();
drop trigger if exists guard_new_local_credential on public.member_credentials;
create trigger guard_new_local_credential before insert on public.member_credentials for each row
  when (new.status = 'pending')
  execute function public.guard_local_signup_identity();

create or replace function public.update_signup_configuration(
  p_action text, p_actor bigint, p_code text, p_term uuid, p_expires timestamptz, p_hours integer
) returns timestamptz language plpgsql security invoker set search_path = '' as $$
declare
  v_setting public.signup_codes%rowtype;
  v_now timestamptz;
  v_ot timestamptz;
begin
  perform pg_advisory_xact_lock(62004, 1);
  select * into v_setting from public.signup_codes where revoked_at is null for update;
  v_now := clock_timestamp();
  if p_action = 'ot_open' then
    if p_hours is null or p_hours not in (1, 3, 6) then
      raise exception 'Invalid OT duration';
    end if;
    v_ot := v_now + make_interval(hours => p_hours);
    if v_setting.id is null then
      insert into public.signup_codes (code, created_by, created_at, auto_approve_until)
        values ('OT-AUTO-APPROVAL', p_actor, v_now, v_ot);
    else
      update public.signup_codes set auto_approve_until = v_ot where id = v_setting.id;
    end if;
    return v_ot;
  elsif p_action = 'ot_close' then
    update public.signup_codes set auto_approve_until = null where id = v_setting.id;
  elsif p_action in ('revoke', 'replace') then
    update public.signup_codes set revoked_at = v_now where id = v_setting.id;
    if p_action = 'replace' then
      insert into public.signup_codes (code, term_id, created_by, created_at, expires_at, auto_approve_until)
        values (p_code, p_term, p_actor, v_now, p_expires,
                case when v_setting.auto_approve_until > v_now then v_setting.auto_approve_until end);
    end if;
  else
    raise exception 'Invalid signup action';
  end if;
  return null;
end $$;

-- Reserve under transaction-scoped locks so concurrent requests share the same limits.
create or replace function public.reserve_email_auth_code(
  p_id uuid, p_email text, p_purpose text, p_code_hash text, p_client_ip text
) returns boolean language plpgsql security invoker set search_path = '' as $$
declare
  v_now timestamptz;
begin
  perform pg_advisory_xact_lock(62001, hashtext(p_email));
  perform pg_advisory_xact_lock(62002, hashtext(p_client_ip));
  v_now := clock_timestamp();
  if exists (select 1 from public.email_auth_codes
             where email = p_email and created_at > v_now - interval '60 seconds')
     or (select count(*) from public.email_auth_codes
         where email = p_email and created_at > v_now - interval '1 hour') >= 5
     or (select count(*) from public.email_auth_codes
         where client_ip = p_client_ip and created_at > v_now - interval '1 hour') >= 20 then
    return false;
  end if;
  insert into public.email_auth_codes (id, email, purpose, code_hash, client_ip, created_at, expires_at)
    values (p_id, p_email, p_purpose, p_code_hash, p_client_ip, v_now, v_now + interval '10 minutes');
  return true;
end $$;

-- Share the roster row lock and revision with save_seminar_term_members.
-- An uninitialized roster keeps its existing fallback until officers save it.
create or replace function public.ensure_signup_term_member(p_member bigint)
returns void language plpgsql security invoker set search_path = '' as $$
declare
  v_term uuid;
  v_today date := (now() at time zone 'Asia/Seoul')::date;
begin
  select id into v_term from public.seminar_terms where is_active
    order by case when v_today between start_date and end_date then 0
                  when start_date > v_today then 1 else 2 end,
             case when start_date > v_today then start_date end,
             start_date desc, id
    limit 1 for update;
  if v_term is null then
    return;
  end if;
  insert into public.seminar_term_members (term_id, member_id, status, entry_type)
    values (v_term, p_member, 'active', 'new') on conflict (term_id, member_id) do nothing;
  if found then
    update public.seminar_terms set roster_revision = roster_revision + 1 where id = v_term;
  end if;
end $$;

create or replace function public.complete_email_signup(
  p_code_id uuid, p_email text, p_name text, p_student_id text, p_department text,
  p_pin_hash text, p_signup_code text
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  v_proof public.email_auth_codes%rowtype;
  v_member public.members%rowtype;
  v_code public.signup_codes%rowtype;
  v_member_ids bigint[];
  v_now timestamptz;
  v_ot boolean;
  v_today date;
begin
  select * into v_proof from public.email_auth_codes where id = p_code_id for update;
  if not found or v_proof.email is distinct from p_email or v_proof.purpose not in ('login','signup')
     or v_proof.consumed_at is null or v_proof.finalized_at is not null
     or v_proof.consumed_at + interval '10 minutes' <= clock_timestamp() then
    return jsonb_build_object('result', 'expired');
  end if;

  -- Normalize legacy whitespace in stored student IDs and serialize school-email enrollment
  -- for the same student, even when submitted from two different verified addresses.
  perform pg_advisory_xact_lock(62003, hashtext(p_student_id));
  select array(select id from public.members
               where regexp_replace(student_id, '\s+', '', 'g') = p_student_id limit 2)
    into v_member_ids;
  if exists (select 1 from public.members where knu_email = p_email) then
    return jsonb_build_object('result', 'conflict');
  end if;

  if cardinality(v_member_ids) <> 0 then
    if cardinality(v_member_ids) <> 1 then
      return jsonb_build_object('result', 'conflict');
    end if;
    select * into v_member from public.members where id = v_member_ids[1] for update;
    if not found or btrim(v_member.name) is distinct from p_name
       or regexp_replace(v_member.student_id, '\s+', '', 'g') is distinct from p_student_id
       or v_member.role is distinct from 'member' or v_member.is_active is distinct from true
       or v_member.account_status is distinct from 'active'
       or v_member.member_status in ('inactive', 'blocked', 'pending')
       or v_member.social_id like 'system:%' or v_member.knu_email is not null or v_member.auth_provider = 'local'
       or exists (select 1 from public.member_credentials where member_id = v_member.id)
       or exists (select 1 from public.term_officers where member_id = v_member.id) then
      return jsonb_build_object('result', 'conflict');
    end if;
    update public.members set knu_email = p_email, knu_email_verified_at = v_proof.consumed_at,
      auth_provider = 'local', pin_hash = p_pin_hash, student_id = p_student_id
      where id = v_member.id returning * into v_member;
  else
    if char_length(coalesce(p_department, '')) not between 1 and 60 then
      return jsonb_build_object('result', 'department');
    end if;
    perform pg_advisory_xact_lock_shared(62004, 1);
    select * into v_code from public.signup_codes where revoked_at is null
      order by created_at desc limit 1 for share;
    v_now := clock_timestamp();
    v_today := (v_now at time zone 'Asia/Seoul')::date;
    v_ot := coalesce(v_code.auto_approve_until > v_now, false);
    if not v_ot then
      if v_code.id is null or v_code.code = 'OT-AUTO-APPROVAL'
         or v_code.expires_at <= v_now
         or (v_code.expires_at is null and exists (
           select 1 from public.seminar_terms where id = v_code.term_id and end_date < v_today
         )) then
        return jsonb_build_object('result', 'closed');
      end if;
      if v_code.code <> 'OPEN-SIGNUP-NO-CODE' and v_code.code is distinct from p_signup_code then
        return jsonb_build_object('result', 'code');
      end if;
    end if;
    insert into public.members (name, student_id, department, role, auth_provider,
                                knu_email, knu_email_verified_at, pin_hash,
                                account_status, member_status, is_active)
      values (p_name, p_student_id, p_department, 'member', 'local', p_email, v_proof.consumed_at, p_pin_hash,
              case when v_ot then 'active' else 'pending' end,
              case when v_ot then 'active' else 'inactive' end, v_ot)
      returning * into v_member;
    if v_ot then
      perform public.ensure_signup_term_member(v_member.id);
    end if;
  end if;
  update public.email_auth_codes set finalized_at = clock_timestamp() where id = p_code_id;
  return jsonb_build_object('result', v_member.account_status, 'member_id', v_member.id);
exception when unique_violation then
  return jsonb_build_object('result', 'conflict');
end $$;

create or replace function public.decide_local_signup(p_member bigint, p_actor bigint, p_approve boolean)
returns text language plpgsql security invoker set search_path = '' as $$
declare
  v_member public.members%rowtype;
  v_credential public.member_credentials%rowtype;
  v_email_pending boolean;
begin
  select * into v_member from public.members where id = p_member for no key update;
  if not found then
    return 'missing';
  end if;
  select * into v_credential from public.member_credentials where member_id = p_member for update;
  v_email_pending := v_member.account_status = 'pending' and v_member.auth_provider = 'local'
    and v_member.knu_email_verified_at is not null and v_member.knu_email is not null;
  if v_credential.status is distinct from 'pending' and v_email_pending is not true then
    return 'missing';
  end if;

  if not p_approve then
    delete from public.member_credentials where member_id = p_member and status = 'pending';
    if v_member.account_status = 'pending' then
      begin
        delete from public.members where id = p_member;
      exception when foreign_key_violation then
        update public.members set account_status = 'disabled' where id = p_member;
      end;
    end if;
    return 'success';
  end if;

  if v_member.member_status = 'blocked' or v_member.account_status = 'disabled'
     or (v_member.account_status is distinct from 'pending'
         and (v_member.member_status = 'inactive' or v_member.is_active is false))
     or (v_member.account_status = 'pending' and v_member.auth_provider is distinct from 'local'
         and v_member.member_status = 'inactive') then
    return 'inactive';
  end if;
  update public.members set account_status = 'active', auth_provider = 'local',
    member_status = case when v_member.account_status = 'pending' then 'active' else member_status end,
    is_active = case when v_member.account_status = 'pending' then true else is_active end
    where id = p_member;
  update public.member_credentials set status = 'active', approved_at = now(), approved_by = p_actor
    where member_id = p_member and status = 'pending';
  if v_member.account_status = 'pending' then
    perform public.ensure_signup_term_member(p_member);
  end if;
  return 'success';
end $$;

revoke all on function public.reserve_email_auth_code(uuid,text,text,text,text),
  public.guard_local_signup_identity(),
  public.update_signup_configuration(text,bigint,text,uuid,timestamptz,integer),
  public.ensure_signup_term_member(bigint), public.complete_email_signup(uuid,text,text,text,text,text,text),
  public.decide_local_signup(bigint,bigint,boolean) from public, anon, authenticated;
grant execute on function public.reserve_email_auth_code(uuid,text,text,text,text),
  public.guard_local_signup_identity(),
  public.update_signup_configuration(text,bigint,text,uuid,timestamptz,integer),
  public.ensure_signup_term_member(bigint), public.complete_email_signup(uuid,text,text,text,text,text,text),
  public.decide_local_signup(bigint,bigint,boolean) to service_role;

commit;

-- Rollback (coordinate with the application rollback):
-- begin;
-- drop trigger if exists guard_new_local_credential on public.member_credentials;
-- drop trigger if exists guard_new_local_member on public.members;
-- drop function if exists public.guard_local_signup_identity();
-- drop function if exists public.decide_local_signup(bigint,bigint,boolean);
-- drop function if exists public.complete_email_signup(uuid,text,text,text,text,text,text);
-- drop function if exists public.ensure_signup_term_member(bigint);
-- drop function if exists public.reserve_email_auth_code(uuid,text,text,text,text);
-- drop function if exists public.update_signup_configuration(text,bigint,text,uuid,timestamptz,integer);
-- delete from public.signup_codes where code = 'OT-AUTO-APPROVAL';
-- alter table public.signup_codes drop column if exists expires_at, drop column if exists auto_approve_until;
-- drop table if exists public.email_auth_codes;
-- drop index if exists public.members_knu_email_uidx;
-- alter table public.members drop column if exists knu_email, drop column if exists knu_email_verified_at,
--   drop column if exists pin_hash, drop column if exists pin_failed_attempts, drop column if exists pin_locked_until;
-- commit;
