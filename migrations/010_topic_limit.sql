-- 010: 발제문 1인 1개 제한 + 학번 기반 본인 식별
-- topic_limit: 제출자별 발제문 최대 개수 (기본 1, 회장이 개별 상향 가능)
-- student_id: 제출자 학번 (event_id+student_id로 동일인 판별, 학과 표기 차이로 인한 중복 제출 방지)
ALTER TABLE topic_submissions ADD COLUMN IF NOT EXISTS topic_limit int NOT NULL DEFAULT 1;
ALTER TABLE topic_submissions ADD COLUMN IF NOT EXISTS student_id text;
CREATE INDEX IF NOT EXISTS topic_submissions_event_sid_idx ON topic_submissions (event_id, student_id);
