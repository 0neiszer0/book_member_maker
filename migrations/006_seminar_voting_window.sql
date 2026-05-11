-- 006_seminar_voting_window.sql
-- 세미나 회차별 투표 시작/마감 시각을 관리자가 직접 지정할 수 있도록 컬럼 추가.
-- 값이 NULL이면 기존 기본 규칙(전주 금 18:00 ~ 전주 일 23:59:59)으로 fallback.
-- ============================================================================

ALTER TABLE public.seminar_sessions
    ADD COLUMN IF NOT EXISTS vote_open_at  timestamptz,
    ADD COLUMN IF NOT EXISTS vote_close_at timestamptz;

COMMENT ON COLUMN public.seminar_sessions.vote_open_at  IS '관리자 지정 투표 오픈 시각(KST). NULL이면 기본 규칙 사용.';
COMMENT ON COLUMN public.seminar_sessions.vote_close_at IS '관리자 지정 투표 마감 시각(KST). NULL이면 기본 규칙 사용.';
