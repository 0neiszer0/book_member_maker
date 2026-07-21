-- 015_weekly_seminar_absences.sql
-- 주간 도서/발제문을 기준 데이터로 만들고, 목요일 불참 이력을 영구 보존한다.

BEGIN;

CREATE TABLE IF NOT EXISTS public.seminar_weeks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    term_id uuid NOT NULL REFERENCES public.seminar_terms(id) ON DELETE RESTRICT,
    week_start date NOT NULL,
    book_title text,
    book_author text,
    note text,
    needs_review boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (term_id, week_start)
);

ALTER TABLE public.seminar_sessions
    ADD COLUMN IF NOT EXISTS seminar_week_id uuid
        REFERENCES public.seminar_weeks(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS participation_mode text,
    ADD COLUMN IF NOT EXISTS capacity integer;

ALTER TABLE public.seminar_sessions
    DROP CONSTRAINT IF EXISTS seminar_sessions_participation_mode_check;
ALTER TABLE public.seminar_sessions
    ADD CONSTRAINT seminar_sessions_participation_mode_check
    CHECK (participation_mode IN ('legacy_explicit', 'opt_in', 'absence_only'));
ALTER TABLE public.seminar_sessions
    DROP CONSTRAINT IF EXISTS seminar_sessions_capacity_check;
ALTER TABLE public.seminar_sessions
    ADD CONSTRAINT seminar_sessions_capacity_check
    CHECK (capacity IS NULL OR capacity > 0);

ALTER TABLE public.topic_events
    ADD COLUMN IF NOT EXISTS seminar_week_id uuid
        REFERENCES public.seminar_weeks(id) ON DELETE RESTRICT;

CREATE TABLE IF NOT EXISTS public.seminar_absences (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id uuid NOT NULL REFERENCES public.seminar_sessions(id) ON DELETE RESTRICT,
    member_id bigint NOT NULL REFERENCES public.members(id) ON DELETE RESTRICT,
    note text,
    recorded_by bigint REFERENCES public.members(id) ON DELETE SET NULL,
    cancelled_by bigint REFERENCES public.members(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    cancelled_at timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS seminar_absences_active_uidx
    ON public.seminar_absences(session_id, member_id)
    WHERE cancelled_at IS NULL;
CREATE INDEX IF NOT EXISTS seminar_absences_session_idx
    ON public.seminar_absences(session_id, created_at);
CREATE INDEX IF NOT EXISTS seminar_absences_member_idx
    ON public.seminar_absences(member_id);
CREATE INDEX IF NOT EXISTS seminar_sessions_week_idx
    ON public.seminar_sessions(seminar_week_id, meeting_date);
CREATE UNIQUE INDEX IF NOT EXISTS topic_events_seminar_week_uidx
    ON public.topic_events(seminar_week_id)
    WHERE seminar_week_id IS NOT NULL;

-- 기존 회차를 주차(월요일 시작) 단위로 묶는다.
INSERT INTO public.seminar_weeks (term_id, week_start)
SELECT DISTINCT term_id, date_trunc('week', meeting_date::timestamp)::date
FROM public.seminar_sessions
ON CONFLICT (term_id, week_start) DO NOTHING;

UPDATE public.seminar_sessions s
SET seminar_week_id = w.id
FROM public.seminar_weeks w
WHERE w.term_id = s.term_id
  AND w.week_start = date_trunc('week', s.meeting_date::timestamp)::date
  AND s.seminar_week_id IS NULL;

UPDATE public.topic_events e
SET seminar_week_id = s.seminar_week_id
FROM public.seminar_sessions s
WHERE s.id = e.seminar_session_id
  AND e.seminar_week_id IS NULL;

-- 출처가 여러 곳이어도 제목이 하나로 일치할 때만 주간 도서로 채운다.
WITH title_candidates AS (
    SELECT seminar_week_id AS week_id, NULLIF(btrim(book_title), '') AS title
    FROM public.seminar_sessions
    UNION ALL
    SELECT seminar_week_id, NULLIF(btrim(book_title), '')
    FROM public.topic_events
    UNION ALL
    SELECT s.seminar_week_id, NULLIF(btrim(h.book_title), '')
    FROM public.history h
    JOIN public.seminar_sessions s ON s.id = h.seminar_session_id
), resolved AS (
    SELECT week_id,
           CASE WHEN count(DISTINCT title) FILTER (WHERE title IS NOT NULL) = 1
                THEN min(title) FILTER (WHERE title IS NOT NULL) END AS title,
           count(DISTINCT title) FILTER (WHERE title IS NOT NULL) > 1 AS needs_review
    FROM title_candidates
    WHERE week_id IS NOT NULL
    GROUP BY week_id
), author_candidates AS (
    SELECT seminar_week_id AS week_id, NULLIF(btrim(book_author), '') AS author
    FROM public.seminar_sessions
    UNION ALL
    SELECT seminar_week_id, NULLIF(btrim(book_author), '')
    FROM public.topic_events
), resolved_authors AS (
    SELECT week_id,
           CASE WHEN count(DISTINCT author) FILTER (WHERE author IS NOT NULL) = 1
                THEN min(author) FILTER (WHERE author IS NOT NULL) END AS author
    FROM author_candidates
    WHERE week_id IS NOT NULL
    GROUP BY week_id
)
UPDATE public.seminar_weeks w
SET book_title = COALESCE(w.book_title, r.title),
    book_author = COALESCE(w.book_author, a.author),
    needs_review = r.needs_review,
    updated_at = now()
FROM resolved r
LEFT JOIN resolved_authors a ON a.week_id = r.week_id
WHERE w.id = r.week_id;

-- 비어 있는 레거시 필드만 복구한다. 충돌 데이터는 보존한다.
UPDATE public.seminar_sessions s
SET book_title = w.book_title,
    book_author = COALESCE(s.book_author, w.book_author)
FROM public.seminar_weeks w
WHERE w.id = s.seminar_week_id
  AND w.book_title IS NOT NULL
  AND NULLIF(btrim(s.book_title), '') IS NULL;

UPDATE public.topic_events e
SET book_title = w.book_title,
    book_author = COALESCE(NULLIF(btrim(e.book_author), ''), w.book_author)
FROM public.seminar_weeks w
WHERE w.id = e.seminar_week_id
  AND w.book_title IS NOT NULL
  AND NULLIF(btrim(e.book_title), '') IS NULL;

UPDATE public.history h
SET book_title = w.book_title
FROM public.seminar_sessions s
JOIN public.seminar_weeks w ON w.id = s.seminar_week_id
WHERE h.seminar_session_id = s.id
  AND w.book_title IS NOT NULL
  AND NULLIF(btrim(h.book_title), '') IS NULL;

-- 앞으로의 월요일은 신청제, 목요일은 운영진 불참 입력제로 전환한다.
UPDATE public.seminar_sessions
SET participation_mode = CASE
        WHEN meeting_date < CURRENT_DATE THEN 'legacy_explicit'
        WHEN day_type = 'mon' THEN 'opt_in'
        WHEN day_type = 'thu' THEN 'absence_only'
        ELSE 'legacy_explicit'
    END,
    capacity = CASE
        WHEN meeting_date >= CURRENT_DATE AND day_type = 'mon' THEN 10
        ELSE capacity
    END
WHERE participation_mode IS NULL;

ALTER TABLE public.seminar_sessions
    ALTER COLUMN participation_mode SET DEFAULT 'legacy_explicit',
    ALTER COLUMN participation_mode SET NOT NULL;

-- 월요일 좌석 확정은 회차 행을 잠가 동시 신청도 정원을 넘지 않게 한다.
CREATE OR REPLACE FUNCTION public.claim_monday_seminar_seat(
    p_session_id uuid,
    p_member_id bigint
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_mode text;
    v_capacity integer;
    v_count integer;
BEGIN
    SELECT participation_mode, capacity
      INTO v_mode, v_capacity
      FROM public.seminar_sessions
     WHERE id = p_session_id
     FOR UPDATE;

    IF NOT FOUND OR v_mode <> 'opt_in' THEN
        RETURN jsonb_build_object('accepted', false, 'reason', 'not_opt_in');
    END IF;

    IF EXISTS (
        SELECT 1 FROM public.seminar_votes
         WHERE session_id = p_session_id AND member_id = p_member_id AND attending = true
    ) THEN
        SELECT count(*) INTO v_count FROM public.seminar_votes
         WHERE session_id = p_session_id AND attending = true;
        RETURN jsonb_build_object('accepted', true, 'count', v_count, 'capacity', v_capacity);
    END IF;

    SELECT count(*) INTO v_count FROM public.seminar_votes
     WHERE session_id = p_session_id AND attending = true;
    IF v_capacity IS NOT NULL AND v_count >= v_capacity THEN
        RETURN jsonb_build_object('accepted', false, 'reason', 'full', 'count', v_count, 'capacity', v_capacity);
    END IF;

    INSERT INTO public.seminar_votes(session_id, member_id, attending, added_by_admin)
    VALUES (p_session_id, p_member_id, true, false)
    ON CONFLICT (session_id, member_id)
    DO UPDATE SET attending = true, voted_at = now(), added_by_admin = false;

    RETURN jsonb_build_object('accepted', true, 'count', v_count + 1, 'capacity', v_capacity);
END;
$$;

ALTER TABLE public.seminar_weeks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.seminar_absences ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.seminar_weeks, public.seminar_absences FROM anon, authenticated;
GRANT ALL ON public.seminar_weeks, public.seminar_absences TO service_role;
GRANT ALL ON public.seminar_sessions, public.seminar_votes, public.topic_events,
    public.topic_submissions, public.history TO service_role;

REVOKE ALL ON FUNCTION public.claim_monday_seminar_seat(uuid, bigint)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_monday_seminar_seat(uuid, bigint)
    TO service_role;

COMMIT;
