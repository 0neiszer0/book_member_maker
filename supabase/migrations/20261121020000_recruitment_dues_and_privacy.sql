begin;
set local lock_timeout = '5s';

alter table public.recruitment_campaigns
  add column if not exists dues_account_info text,
  add column if not exists dues_amount text,
  add column if not exists dues_contact_phone text,
  add column if not exists dues_guide_note text;

alter table public.recruitment_applicants
  add column if not exists dues_paid_at timestamptz,
  add column if not exists dues_checked_by bigint references public.members(id) on delete set null,
  add column if not exists knu_email text check (knu_email is null or knu_email ~ '^[a-z0-9._%+-]+@knu\.ac\.kr$');

create index if not exists recruitment_applicants_dues_checked_by_idx
  on public.recruitment_applicants (dues_checked_by) where dues_checked_by is not null;

create or replace view public.inactive_member_privacy_candidates
with (security_invoker = true) as
select m.id, m.recruiting_class
from public.members m
where m.role = 'member'
  and (m.member_status = 'inactive' or m.is_active is false)
  -- Archive authors use synthetic IDs as stable references.
  and coalesce(m.social_id, '') not like 'system:%'
  and (
    m.email is not null or m.knu_email is not null or m.knu_email_verified_at is not null
    or m.student_id is not null or m.social_id is not null or m.pin_hash is not null
    or m.pin_failed_attempts <> 0 or m.pin_locked_until is not null
    or exists (select 1 from public.member_credentials c where c.member_id = m.id)
    or exists (select 1 from public.account_setup_tokens t where t.member_id = m.id)
    or exists (select 1 from public.push_subscriptions p where p.member_id = m.id)
  );

create or replace function public.privacy_cleanup_summary()
returns jsonb language sql stable security invoker set search_path = '' as $$
  with members as (
    select id, recruiting_class from public.inactive_member_privacy_candidates
  ), preview as (
    select id, recruiting_class from members order by id limit 20
  ), campaigns as (
    select c.id, c.title, c.created_at, count(a.id) as applicant_count,
           count(a.id) filter (where a.result_status = 'rejected') as rejected_count
    from public.recruitment_campaigns c
    left join public.recruitment_applicants a on a.campaign_id = c.id
    where c.is_active is false
    group by c.id
  )
  select jsonb_build_object(
    'inactive_count', (select count(*) from members),
    'inactive_preview', coalesce((select jsonb_agg(to_jsonb(p) order by p.id) from preview p), '[]'::jsonb),
    'campaigns', coalesce((select jsonb_agg(
      jsonb_build_object('id', c.id, 'title', c.title, 'applicant_count', c.applicant_count,
                         'rejected_count', c.rejected_count)
      order by c.created_at desc, c.id) from campaigns c), '[]'::jsonb)
  );
$$;

create or replace function public.purge_inactive_member_privacy()
returns bigint language plpgsql security invoker set search_path = '' as $$
declare
  purged_count bigint;
begin
  -- A second purge waits and reads fresh candidates after the first commits.
  perform pg_advisory_xact_lock(62005, 1);
  with candidates as (
    select m.id
    from public.members m
    join public.inactive_member_privacy_candidates c on c.id = m.id
    where m.role = 'member'
      and (m.member_status = 'inactive' or m.is_active is false)
      and coalesce(m.social_id, '') not like 'system:%'
    order by m.id
    for update of m
  ), purged as (
    update public.members m set
      email = null, knu_email = null, knu_email_verified_at = null,
      pin_hash = null, pin_failed_attempts = 0, pin_locked_until = null,
      social_id = null, student_id = null, auth_session_version = m.auth_session_version + 1
    from candidates c
    where m.id = c.id
    returning m.id
  ), credentials as (
    delete from public.member_credentials c using purged p where c.member_id = p.id
  ), setup_tokens as (
    delete from public.account_setup_tokens t using purged p where t.member_id = p.id
  ), subscriptions as (
    delete from public.push_subscriptions s using purged p where s.member_id = p.id
  )
  select count(*) into purged_count from purged;
  return purged_count;
end;
$$;

create or replace function public.purge_recruitment_applicant_privacy(p_campaign uuid, p_scope text)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  campaign_active boolean;
  purged_count bigint;
begin
  if p_scope is null or p_scope not in ('rejected', 'all') then
    return jsonb_build_object('state', 'invalid');
  end if;
  select is_active into campaign_active
  from public.recruitment_campaigns where id = p_campaign for update;
  if not found then
    return jsonb_build_object('state', 'missing');
  end if;
  if p_scope = 'all' and campaign_active then
    return jsonb_build_object('state', 'active');
  end if;
  delete from public.recruitment_applicants
  where campaign_id = p_campaign and (p_scope = 'all' or result_status = 'rejected');
  get diagnostics purged_count = row_count;
  return jsonb_build_object('state', 'success', 'purged_count', purged_count);
end;
$$;

revoke all on public.inactive_member_privacy_candidates from public, anon, authenticated;
grant select on public.inactive_member_privacy_candidates to service_role;

revoke all on function public.privacy_cleanup_summary(), public.purge_inactive_member_privacy(),
  public.purge_recruitment_applicant_privacy(uuid, text) from public, anon, authenticated;
grant execute on function public.privacy_cleanup_summary(), public.purge_inactive_member_privacy(),
  public.purge_recruitment_applicant_privacy(uuid, text) to service_role;

commit;
