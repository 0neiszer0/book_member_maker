begin;
set local lock_timeout = '5s';

-- Let eligible members keep their existing record when moving to school email.
create or replace function public.complete_email_signup(
  p_code_id uuid, p_email text, p_name text, p_student_id text, p_department text,
  p_pin_hash text, p_signup_code text
) returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  v_proof public.email_auth_codes%rowtype;
  v_member public.members%rowtype;
  v_credential_status text;
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
       or v_member.social_id like 'system:%' or v_member.knu_email is not null
       or exists (select 1 from public.term_officers where member_id = v_member.id) then
      return jsonb_build_object('result', 'conflict');
    end if;
    -- Match the member-before-credential lock order used by signup approval.
    select status into v_credential_status from public.member_credentials
      where member_id = v_member.id for update;
    if (found or v_member.auth_provider = 'local') and v_credential_status is distinct from 'active' then
      return jsonb_build_object('result', 'conflict');
    end if;
    update public.members set knu_email = p_email, knu_email_verified_at = v_proof.consumed_at,
      auth_provider = 'local', pin_hash = p_pin_hash, student_id = p_student_id,
      auth_session_version = v_member.auth_session_version + 1
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
         or exists (
           select 1 from public.seminar_terms where id = v_code.term_id and end_date < v_today
         ) then
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

revoke all on function public.complete_email_signup(uuid,text,text,text,text,text,text)
  from public, anon, authenticated;
grant execute on function public.complete_email_signup(uuid,text,text,text,text,text,text) to service_role;

commit;
