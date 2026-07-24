create table public.seminar_no_shows (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references public.seminar_sessions(id) on delete restrict,
  member_id bigint not null references public.members(id) on delete restrict,
  note text check (note is null or char_length(note) <= 500),
  recorded_by bigint references public.members(id) on delete set null,
  cancelled_by bigint references public.members(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  cancelled_at timestamptz
);

comment on table public.seminar_no_shows is
  '세미나에 사전 연락 없이 불참한 회원 기록. 취소도 행을 삭제하지 않고 cancelled_at으로 보존한다.';

create unique index seminar_no_shows_active_uidx
  on public.seminar_no_shows (session_id, member_id)
  where cancelled_at is null;
create index seminar_no_shows_session_idx
  on public.seminar_no_shows (session_id, created_at);
create index seminar_no_shows_member_idx
  on public.seminar_no_shows (member_id);
create index seminar_no_shows_recorded_by_idx
  on public.seminar_no_shows (recorded_by)
  where recorded_by is not null;
create index seminar_no_shows_cancelled_by_idx
  on public.seminar_no_shows (cancelled_by)
  where cancelled_by is not null;

alter table public.seminar_no_shows enable row level security;
revoke all on table public.seminar_no_shows from anon, authenticated;
grant select, insert, update, delete on table public.seminar_no_shows to service_role;
