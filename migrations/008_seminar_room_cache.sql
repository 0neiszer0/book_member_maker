-- 008_seminar_room_cache.sql
-- 경북대 총동아리연합회 게시판(dongari.knu.ac.kr) 세미나실 예약 글 캐시
--
-- 관리자 페이지에서 달력으로 다른 동아리의 세미나실 예약 현황을 조회하기 위한 캐시.
-- 외부 사이트 크롤링 결과를 저장하며, status가 approved/rejected인 글은 종착 상태로 보고
-- 재크롤 시 상세 페이지를 다시 fetch 하지 않는다(pending만 재확인).
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.seminar_room_posts (
    wr_id            BIGINT PRIMARY KEY,                              -- gnuboard wr_id
    title            TEXT NOT NULL,
    club_name        TEXT,                                            -- 대괄호 안 동아리명
    room             TEXT,                                            -- '민주' | '통일' | '백호' | NULL
    dates            JSONB NOT NULL DEFAULT '[]'::jsonb,              -- ISO 날짜 문자열 배열
    status           TEXT NOT NULL DEFAULT 'pending',                 -- approved | pending | rejected
    post_url         TEXT,
    discovered_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_checked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS seminar_room_posts_status_idx
    ON public.seminar_room_posts(status);

CREATE INDEX IF NOT EXISTS seminar_room_posts_dates_idx
    ON public.seminar_room_posts USING GIN(dates);
