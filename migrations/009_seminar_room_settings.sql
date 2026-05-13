-- 009_seminar_room_settings.sql
-- 세미나실 예약 도우미 설정값 (싱글톤 1행)
--
-- 동아리명/전화번호/시간/목적/학기 시작·종료일 등을 관리자 UI 에서 직접 편집·저장한다.
-- env 변수 대신 DB 에 저장하여 코드 변경 없이 학기마다 갱신 가능.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.seminar_room_settings (
    id              INT PRIMARY KEY DEFAULT 1,
    club_name       TEXT NOT NULL DEFAULT '책 먹는 호반우',
    club_phone      TEXT NOT NULL DEFAULT '010-6509-3524',
    time_slot       TEXT NOT NULL DEFAULT '19:00~21:00',
    purpose         TEXT NOT NULL DEFAULT '동아리 세미나 진행',
    semester_start  DATE,
    semester_end    DATE,
    days_ahead_min  INT  NOT NULL DEFAULT 7,
    days_ahead_max  INT  NOT NULL DEFAULT 28,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT seminar_room_settings_singleton CHECK (id = 1)
);

-- 초기 1행 (기본값 + 현재 학기 종료일)
INSERT INTO public.seminar_room_settings (id, semester_end)
VALUES (1, DATE '2026-06-08')
ON CONFLICT (id) DO NOTHING;
