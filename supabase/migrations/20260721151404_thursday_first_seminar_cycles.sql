-- 017_thursday_first_seminar_cycles.sql
-- 운영 묶음을 달력 주간에서 "목요일 본 세미나 + 다음 월요일 추가 세미나"로 교정한다.

BEGIN;

CREATE TEMP TABLE _seminar_week_shift ON COMMIT DROP AS
SELECT
    term_id,
    (week_start + 7)::date AS target_cycle_monday,
    book_title,
    book_author,
    note,
    needs_review
FROM public.seminar_weeks;

-- 기존 주간 입력값은 목요일 뒤에 오는 월요일 기준으로 한 칸 옮긴다.
INSERT INTO public.seminar_weeks (term_id, week_start)
SELECT DISTINCT term_id, target_cycle_monday
FROM _seminar_week_shift
ON CONFLICT (term_id, week_start) DO NOTHING;

-- 모든 회차가 새 운영 묶음을 가리킬 수 있도록 기준 행을 보장한다.
INSERT INTO public.seminar_weeks (term_id, week_start)
SELECT DISTINCT
    term_id,
    CASE
        WHEN day_type = 'thu' THEN (meeting_date + 4)::date
        ELSE meeting_date
    END
FROM public.seminar_sessions
ON CONFLICT (term_id, week_start) DO NOTHING;

UPDATE public.seminar_weeks
SET book_title = NULL,
    book_author = NULL,
    note = NULL,
    needs_review = false,
    updated_at = now();

UPDATE public.seminar_weeks w
SET book_title = snapshot.book_title,
    book_author = snapshot.book_author,
    note = snapshot.note,
    needs_review = snapshot.needs_review,
    updated_at = now()
FROM _seminar_week_shift snapshot
WHERE w.term_id = snapshot.term_id
  AND w.week_start = snapshot.target_cycle_monday;

UPDATE public.seminar_sessions s
SET seminar_week_id = w.id
FROM public.seminar_weeks w
WHERE w.term_id = s.term_id
  AND w.week_start = CASE
      WHEN s.day_type = 'thu' THEN (s.meeting_date + 4)::date
      ELSE s.meeting_date
  END;

-- 유니크 인덱스의 일시적인 자리 충돌을 피한 뒤 발제문을 회차의 새 묶음에 연결한다.
UPDATE public.topic_events
SET seminar_week_id = NULL
WHERE seminar_session_id IS NOT NULL;

UPDATE public.topic_events e
SET seminar_week_id = s.seminar_week_id
FROM public.seminar_sessions s
WHERE s.id = e.seminar_session_id;

-- 옮긴 일정에 값이 없던 경우에는 연결된 발제문/진행 기록에서만 복구한다.
UPDATE public.seminar_weeks w
SET book_title = NULLIF(btrim(e.book_title), ''),
    updated_at = now()
FROM public.topic_events e
WHERE e.seminar_week_id = w.id
  AND NULLIF(btrim(w.book_title), '') IS NULL
  AND NULLIF(btrim(e.book_title), '') IS NOT NULL;

UPDATE public.seminar_weeks w
SET book_author = NULLIF(btrim(e.book_author), ''),
    updated_at = now()
FROM public.topic_events e
WHERE e.seminar_week_id = w.id
  AND NULLIF(btrim(w.book_author), '') IS NULL
  AND NULLIF(btrim(e.book_author), '') IS NOT NULL;

UPDATE public.seminar_weeks w
SET book_title = NULLIF(btrim(h.book_title), ''),
    updated_at = now()
FROM public.history h
JOIN public.seminar_sessions s ON s.id = h.seminar_session_id
WHERE s.seminar_week_id = w.id
  AND NULLIF(btrim(w.book_title), '') IS NULL
  AND NULLIF(btrim(h.book_title), '') IS NOT NULL;

-- 서로 다른 제목이 남아 있으면 자동 덮어쓰기 전에 운영진 확인 표시를 남긴다.
UPDATE public.seminar_weeks w
SET needs_review = true,
    updated_at = now()
FROM public.topic_events e
WHERE e.seminar_week_id = w.id
  AND NULLIF(btrim(w.book_title), '') IS NOT NULL
  AND NULLIF(btrim(e.book_title), '') IS NOT NULL
  AND btrim(w.book_title) <> btrim(e.book_title);

-- 주간 기준값을 호환용 회차/발제문/진행 기록 필드에 동기화한다.
UPDATE public.seminar_sessions s
SET book_title = w.book_title,
    book_author = w.book_author
FROM public.seminar_weeks w
WHERE w.id = s.seminar_week_id;

UPDATE public.topic_events e
SET book_title = w.book_title,
    book_author = w.book_author
FROM public.seminar_weeks w
WHERE w.id = e.seminar_week_id
  AND NULLIF(btrim(w.book_title), '') IS NOT NULL;

UPDATE public.history h
SET book_title = w.book_title
FROM public.seminar_sessions s
JOIN public.seminar_weeks w ON w.id = s.seminar_week_id
WHERE h.seminar_session_id = s.id
  AND NULLIF(btrim(w.book_title), '') IS NOT NULL;

COMMENT ON COLUMN public.seminar_weeks.week_start IS
    '목요일 본 세미나와 그 다음 월요일 추가 세미나를 묶는 기준 월요일';

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM public.seminar_sessions s
        JOIN public.seminar_weeks w ON w.id = s.seminar_week_id
        WHERE w.term_id <> s.term_id
           OR w.week_start <> CASE
               WHEN s.day_type = 'thu' THEN (s.meeting_date + 4)::date
               ELSE s.meeting_date
           END
    ) THEN
        RAISE EXCEPTION '세미나 운영 묶음 재연결 검증에 실패했습니다.';
    END IF;
END;
$$;

COMMIT;
