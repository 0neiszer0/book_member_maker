-- 세미나 출석 투표 시스템 (학기 단위)
-- Supabase SQL 에디터에서 실행하세요.

-- 1) 학기
create table if not exists seminar_terms (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  start_date date not null,
  end_date date not null,
  share_token uuid not null default gen_random_uuid() unique,
  max_capacity int not null default 32,
  is_active boolean not null default true,
  created_at timestamptz default now()
);

-- 2) 회차 (월/목 각각)
create table if not exists seminar_sessions (
  id uuid primary key default gen_random_uuid(),
  term_id uuid not null references seminar_terms(id) on delete cascade,
  meeting_date date not null,
  day_type text not null check (day_type in ('mon','thu')),
  is_active boolean not null default true,
  unique (term_id, meeting_date)
);
create index if not exists seminar_sessions_meeting_date_idx
  on seminar_sessions(meeting_date);

-- 3) 투표
create table if not exists seminar_votes (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references seminar_sessions(id) on delete cascade,
  member_id bigint not null references members(id) on delete cascade,
  attending boolean not null,
  voted_at timestamptz default now(),
  unique (session_id, member_id)
);
create index if not exists seminar_votes_session_attending_idx
  on seminar_votes(session_id, attending);
