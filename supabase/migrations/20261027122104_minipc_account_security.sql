-- Apply only this reviewed expansion migration after production approval.
-- Local CLI could not initialize its user config in the restricted environment.
begin;

-- Fail without exposing or repairing identifiers if legacy duplicates exist.
do $$ begin
  if exists(select 1 from public.members where nullif(social_id,'') is not null
            group by social_id having count(*)>1) then
    raise exception 'Duplicate social identities require manual review';
  end if;
end $$;
create unique index if not exists members_social_id_unique_nonempty
  on public.members(social_id) where social_id is not null and social_id<>'';

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
  if not found or actor.role not in ('admin','officer') or actor.is_active is distinct from true
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
  return jsonb_build_object('accepted',true);
end $$;
revoke all on function public.account_request_mutate(text,bigint,bigint,text,text,text) from public,anon,authenticated;
grant execute on function public.account_request_mutate(text,bigint,bigint,text,text,text) to service_role;

create or replace function public.protected_member_mutate(
  p_actor_id bigint, p_member_id bigint, p_action text, p_payload jsonb default '{}'::jsonb
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare
  actor public.members%rowtype;
  m public.members%rowtype;
  new_role text;
  new_status text;
begin
  lock table public.members in share row exclusive mode;
  select * into actor from public.members where id=p_actor_id for update;
  if not found or actor.role not in ('admin','officer') or actor.is_active is distinct from true
     or actor.account_status is distinct from 'active' or actor.member_status in ('inactive','blocked') then
    return jsonb_build_object('accepted',false);
  end if;
  select * into m from public.members where id=p_member_id for update;
  if not found or p_action is null or p_action not in ('status','edit','delete') then return jsonb_build_object('accepted',false); end if;
  if m.role='admin' and (actor.role <> 'admin' or p_action='delete') then
    return jsonb_build_object('accepted',false);
  end if;
  new_role := case when p_action='edit' and p_payload ? 'role' then p_payload->>'role' else m.role end;
  new_status := case when p_action='status' then p_payload->>'member_status' else m.member_status end;
  if new_role is null or new_role not in ('member','officer','admin') or new_status is null
     or new_status not in ('active','dormant','inactive')
     or (new_role is distinct from m.role and actor.role <> 'admin') then return jsonb_build_object('accepted',false); end if;
  if m.id=actor.id and (p_action='delete' or new_status <> 'active' or new_role is distinct from m.role) then
    return jsonb_build_object('accepted',false);
  end if;
  if m.role='admin' and (new_role <> 'admin' or new_status <> 'active') and not exists(
    select 1 from public.members where id<>m.id and role='admin' and is_active=true
      and account_status='active' and member_status='active'
  ) then return jsonb_build_object('accepted',false); end if;
  if p_action='delete' then delete from public.members where id=m.id;
  elsif p_action='status' then
    update public.members set member_status=new_status,is_active=(new_status='active') where id=m.id;
  else
    if p_payload ? 'student_id' and nullif(p_payload->>'student_id','') is not null and (
      p_payload->>'student_id' !~ '^[0-9]{4,20}$' or exists(
        select 1 from public.members where id<>m.id and student_id=p_payload->>'student_id')) then
      return jsonb_build_object('accepted',false);
    end if;
    update public.members set role=new_role,
      name=case when p_payload ? 'name' then p_payload->>'name' else name end,
      email=case when p_payload ? 'email' then p_payload->>'email' else email end,
      gender=case when p_payload ? 'gender' then p_payload->>'gender' else gender end,
      department=case when p_payload ? 'department' then p_payload->>'department' else department end,
      student_id=case when p_payload ? 'student_id' then p_payload->>'student_id' else student_id end,
      recruiting_class=case when p_payload ? 'recruiting_class' then (p_payload->>'recruiting_class')::integer else recruiting_class end
      where id=m.id;
  end if;
  return jsonb_build_object('accepted',true);
end $$;
revoke all on function public.protected_member_mutate(bigint,bigint,text,jsonb) from public,anon,authenticated;
grant execute on function public.protected_member_mutate(bigint,bigint,text,jsonb) to service_role;
commit;
