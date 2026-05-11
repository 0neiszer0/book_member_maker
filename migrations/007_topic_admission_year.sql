-- 007_topic_admission_year.sql
-- 발제문 제출 시 학번(입학년도 2자리)을 함께 받아 표시용으로 저장.
-- ============================================================================

ALTER TABLE public.topic_submissions
    ADD COLUMN IF NOT EXISTS admission_year text;

COMMENT ON COLUMN public.topic_submissions.admission_year
    IS '학번 입학년도 2자리(예: 22). 전체 학번(2022XXXXXX)의 3-4번째 문자.';
