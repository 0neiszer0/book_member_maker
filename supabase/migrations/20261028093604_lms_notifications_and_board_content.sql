begin;
set local lock_timeout = '5s';

alter table public.posts add column content_format text not null default 'plain'
  check (content_format in ('plain', 'html'));

create table public.member_preferences (
  member_id bigint primary key references public.members(id) on delete cascade,
  hidden_courses text[] not null default '{}' check (cardinality(hidden_courses) <= 100)
);
create table public.member_inbox (
  id uuid primary key default gen_random_uuid(),
  member_id bigint not null references public.members(id) on delete cascade,
  event_key text not null check (length(event_key) <= 200),
  title text not null check (length(title) <= 300),
  body text not null check (length(body) <= 1000),
  url text not null check (url like '/%' and url not like '//%' and length(url) <= 500),
  created_at timestamptz not null default now(),
  read_at timestamptz,
  resolved_at timestamptz,
  unique (member_id, event_key)
);
create index member_inbox_active_idx on public.member_inbox(member_id, created_at desc) where resolved_at is null;
create table public.push_subscriptions (
  endpoint_hash text primary key check (length(endpoint_hash) = 64),
  member_id bigint not null references public.members(id) on delete cascade,
  endpoint text not null check (length(endpoint) <= 2048),
  p256dh text not null check (length(p256dh) <= 128),
  auth text not null check (length(auth) <= 128),
  updated_at timestamptz not null default now()
);
create index push_subscriptions_member_idx on public.push_subscriptions(member_id);
create table public.push_deliveries (
  notification_id uuid not null references public.member_inbox(id) on delete cascade,
  endpoint_hash text not null references public.push_subscriptions(endpoint_hash) on delete cascade,
  attempts smallint not null default 0 check (attempts between 0 and 3),
  next_attempt_at timestamptz,
  sent_at timestamptz,
  primary key (notification_id, endpoint_hash)
);
create index push_deliveries_endpoint_idx on public.push_deliveries(endpoint_hash);

-- Authentication is the Flask/Kakao session, not Supabase Auth. Only the backend
-- service_role can access these tables; every HTTP route rechecks member ownership.
alter table public.member_preferences enable row level security;
alter table public.member_inbox enable row level security;
alter table public.push_subscriptions enable row level security;
alter table public.push_deliveries enable row level security;
revoke all on public.member_preferences, public.member_inbox, public.push_subscriptions, public.push_deliveries from public, anon, authenticated;
grant select, insert, update, delete on public.member_preferences, public.member_inbox, public.push_subscriptions, public.push_deliveries to service_role;

-- Hide only untouched auto-generated additional sessions. Preserve any actual
-- participation, planning or user input; admins can re-enable a session as needed.
update public.seminar_sessions s set is_active = false
where s.day_type = 'mon' and s.is_active
  and exists (select 1 from public.seminar_terms t where t.id = s.term_id and t.is_active)
  and s.planned_member_ids is null and s.actual_member_ids is null
  and s.roster_updated_at is null and s.attendance_confirmed_at is null
  and not exists (select 1 from public.history h where h.seminar_session_id = s.id or left(h.date, 10) = s.meeting_date::text)
  and not exists (select 1 from public.seminar_votes v where v.session_id = s.id)
  and not exists (select 1 from public.seminar_absences a where a.session_id = s.id)
  and not exists (select 1 from public.topic_events t where t.seminar_session_id = s.id)
  and not exists (select 1 from public.seminar_review_forms r where r.seminar_session_id = s.id);
commit;
