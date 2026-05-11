-- 005_special_events.sql
-- 스페셜 이벤트(MT, 워크숍, 강연 등) 시스템
--
-- events 테이블은 면접용으로 유지하고, 별도 special_events 테이블 신설.
-- 회원 활동 기록과 마이페이지에서도 이 이벤트 참여를 함께 표시.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.special_events (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    description text,
    event_date date not null,
    end_date date,                                  -- null이면 당일 행사
    category text not null default 'event',         -- 'mt' | 'workshop' | 'lecture' | 'event' | 등 자유 라벨
    location text,
    is_active boolean not null default true,
    term_id uuid references public.seminar_terms(id) on delete set null,
    created_at timestamptz default now(),
    created_by bigint references public.members(id) on delete set null
);

CREATE INDEX IF NOT EXISTS special_events_date_idx
    ON public.special_events (event_date DESC);
CREATE INDEX IF NOT EXISTS special_events_active_idx
    ON public.special_events (is_active, event_date DESC);

CREATE TABLE IF NOT EXISTS public.special_event_attendees (
    id uuid primary key default gen_random_uuid(),
    event_id uuid not null references public.special_events(id) on delete cascade,
    member_id bigint not null references public.members(id) on delete cascade,
    role text default 'attendee',                   -- 'attendee' | 'organizer' | 'speaker' 등
    note text,
    created_at timestamptz default now(),
    unique (event_id, member_id)
);

CREATE INDEX IF NOT EXISTS special_event_attendees_event_idx
    ON public.special_event_attendees (event_id);
CREATE INDEX IF NOT EXISTS special_event_attendees_member_idx
    ON public.special_event_attendees (member_id);

-- RLS는 켜되 정책 없음 — 백엔드(SERVICE_KEY)만 접근. 의도적 선택.
ALTER TABLE public.special_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.special_event_attendees ENABLE ROW LEVEL SECURITY;
