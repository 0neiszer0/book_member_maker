-- 005_special_events.sql
-- 스페셜 이벤트 시스템 (세미나/벽돌책/소모임 외의 1회성 행사)
-- 예: MT, 워크숍, 강연, 친목 행사 등
-- ============================================================================

-- 1) special_events — 이벤트 본체
create table if not exists public.special_events (
    id uuid primary key default gen_random_uuid(),
    name text not null,                    -- "여름 MT", "독서 워크숍" 등
    description text,                      -- 설명/장소/메모
    event_date date not null,              -- 행사 날짜
    end_date date,                         -- 종료일 (다일 행사일 경우, null 가능)
    category text default 'event',         -- 자유 분류 ('mt', 'workshop', 'lecture', 'social', 'event')
    is_active boolean not null default true,
    term_id uuid references public.seminar_terms(id) on delete set null, -- 학기 필터 연계
    created_at timestamptz default now(),
    created_by bigint references public.members(id) on delete set null
);

create index if not exists special_events_date_idx
    on public.special_events (event_date desc);
create index if not exists special_events_term_idx
    on public.special_events (term_id) where term_id is not null;
create index if not exists special_events_active_idx
    on public.special_events (is_active, event_date desc);


-- 2) special_event_attendees — 참석자 명단
create table if not exists public.special_event_attendees (
    id uuid primary key default gen_random_uuid(),
    event_id uuid not null references public.special_events(id) on delete cascade,
    member_id bigint not null references public.members(id) on delete cascade,
    role text default 'attendee',          -- 'attendee', 'host', 'speaker' 등
    note text,                             -- "발표자", "1박2일 참석" 등 자유 메모
    created_at timestamptz default now(),
    unique (event_id, member_id)
);

create index if not exists special_event_attendees_event_idx
    on public.special_event_attendees (event_id);
create index if not exists special_event_attendees_member_idx
    on public.special_event_attendees (member_id);


-- ============================================================================
-- 적용 후 확인:
-- SELECT * FROM special_events;
-- ============================================================================
