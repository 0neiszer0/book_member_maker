-- 통합 기록 시스템 v2 (단순화)
-- Supabase SQL 에디터에서 실행하세요.

-- 1) 장르 마스터
create table if not exists genres (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  is_default boolean not null default false,
  display_order int default 100,
  created_at timestamptz default now()
);
insert into genres (name, is_default, display_order) values
  ('고전문학', true, 10),
  ('한국문학', true, 20),
  ('비문학',   true, 30),
  ('시',       true, 40)
on conflict (name) do nothing;

-- 2) history 확장
alter table history add column if not exists book_title text;
alter table history add column if not exists genre text;

-- 3) 벽돌책 그룹 (책 단위)
create table if not exists brick_books (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  notes text,
  created_at timestamptz default now()
);

-- 4) 벽돌책 세션 (날짜별 모임)
create table if not exists brick_book_sessions (
  id uuid primary key default gen_random_uuid(),
  brick_book_id uuid not null references brick_books(id) on delete cascade,
  meeting_date date not null,
  notes text,
  created_at timestamptz default now()
);
create index if not exists brick_book_sessions_book_idx on brick_book_sessions(brick_book_id);
create index if not exists brick_book_sessions_date_idx on brick_book_sessions(meeting_date);

-- 5) 벽돌책 세션 참여자
create table if not exists brick_session_members (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references brick_book_sessions(id) on delete cascade,
  member_id bigint not null references members(id) on delete cascade,
  unique (session_id, member_id)
);
create index if not exists brick_session_members_member_idx on brick_session_members(member_id);

-- 6) 소모임 그룹
create table if not exists study_groups (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  notes text,
  created_at timestamptz default now()
);

-- 7) 소모임 세션
create table if not exists study_group_sessions (
  id uuid primary key default gen_random_uuid(),
  study_group_id uuid not null references study_groups(id) on delete cascade,
  meeting_date date not null,
  notes text,
  created_at timestamptz default now()
);
create index if not exists study_group_sessions_group_idx on study_group_sessions(study_group_id);
create index if not exists study_group_sessions_date_idx on study_group_sessions(meeting_date);

-- 8) 소모임 세션 참여자
create table if not exists study_session_members (
  id uuid primary key default gen_random_uuid(),
  session_id uuid not null references study_group_sessions(id) on delete cascade,
  member_id bigint not null references members(id) on delete cascade,
  unique (session_id, member_id)
);
create index if not exists study_session_members_member_idx on study_session_members(member_id);
