-- 011: 발제문 제출자 식별과 개수 제한을 DB에서도 보장
-- 기존 제출은 student_id가 NULL이므로 유지하고, 학번이 기록되는 신규/수정 제출만
-- 같은 이벤트에서 한 사람당 하나의 제출 레코드를 갖도록 제한한다.

UPDATE topic_submissions
SET student_id = NULLIF(BTRIM(student_id), '')
WHERE student_id IS DISTINCT FROM NULLIF(BTRIM(student_id), '');

CREATE UNIQUE INDEX IF NOT EXISTS topic_submissions_event_sid_uidx
ON topic_submissions (event_id, student_id)
WHERE student_id IS NOT NULL;

DROP INDEX IF EXISTS topic_submissions_event_sid_idx;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'topic_submissions_topic_limit_check'
          AND conrelid = 'topic_submissions'::regclass
    ) THEN
        ALTER TABLE topic_submissions
        ADD CONSTRAINT topic_submissions_topic_limit_check
        CHECK (topic_limit BETWEEN 1 AND 10);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'topic_submissions_student_id_format_check'
          AND conrelid = 'topic_submissions'::regclass
    ) THEN
        ALTER TABLE topic_submissions
        ADD CONSTRAINT topic_submissions_student_id_format_check
        CHECK (student_id IS NULL OR student_id ~ '^[0-9]{4,10}$');
    END IF;
END $$;
