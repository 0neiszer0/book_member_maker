-- Planned Kakao rosters and confirmed attendance are separate facts.
-- Additive migration: no member, topic or grouping record is deleted.
BEGIN;

ALTER TABLE public.seminar_sessions
  ADD COLUMN IF NOT EXISTS planned_member_ids bigint[],
  ADD COLUMN IF NOT EXISTS roster_updated_at timestamptz,
  ADD COLUMN IF NOT EXISTS actual_member_ids bigint[],
  ADD COLUMN IF NOT EXISTS attendance_confirmed_at timestamptz,
  ADD COLUMN IF NOT EXISTS moderator_name text NOT NULL DEFAULT '';
ALTER TABLE public.topic_events
  ADD COLUMN IF NOT EXISTS moderator_name text NOT NULL DEFAULT '';
ALTER TABLE public.seminar_terms
  ADD COLUMN IF NOT EXISTS attendance_minimum integer NOT NULL DEFAULT 3;
ALTER TABLE public.special_events
  ADD COLUMN IF NOT EXISTS counts_toward_attendance boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS attendance_confirmed_at timestamptz;
ALTER TABLE public.history
  ADD COLUMN IF NOT EXISTS group_editor_state jsonb NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS actual_member_ids bigint[];

-- Existing past records retain their historical status. Today's/future groups
-- and every new saved group require an explicit actual-attendance confirmation.
-- Backfill only on first introduction, never on a repeated migration check.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'history'
      AND column_name = 'attendance_confirmed_at'
  ) THEN
    ALTER TABLE public.history ADD COLUMN attendance_confirmed_at timestamptz;
    UPDATE public.history SET attendance_confirmed_at = now()
    WHERE date ~ '^\d{4}-\d{2}-\d{2}$'
      AND date < to_char(now() AT TIME ZONE 'Asia/Seoul', 'YYYY-MM-DD');
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'seminar_terms_attendance_minimum_check'
      AND conrelid = 'public.seminar_terms'::regclass
  ) THEN
    ALTER TABLE public.seminar_terms ADD CONSTRAINT seminar_terms_attendance_minimum_check
      CHECK (attendance_minimum BETWEEN 1 AND 50);
  END IF;
END $$;

UPDATE public.seminar_sessions SET capacity = NULL WHERE day_type = 'mon';

CREATE TABLE IF NOT EXISTS public.seminar_roster_imports (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id uuid NOT NULL REFERENCES public.seminar_sessions(id) ON DELETE CASCADE,
  mode text NOT NULL CHECK (mode IN ('attendance', 'absence')),
  member_ids bigint[] NOT NULL,
  expected_member_ids bigint[] NOT NULL,
  previous_member_ids bigint[],
  created_by bigint REFERENCES public.members(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS seminar_roster_imports_session_created_idx
  ON public.seminar_roster_imports(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS seminar_roster_imports_created_by_idx
  ON public.seminar_roster_imports(created_by);
ALTER TABLE public.seminar_roster_imports ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.seminar_roster_imports FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.seminar_roster_imports TO service_role;

CREATE OR REPLACE FUNCTION public.apply_seminar_roster(
  p_session_id uuid,
  p_member_ids bigint[],
  p_expected_member_ids bigint[],
  p_previous_member_ids bigint[],
  p_previous_updated_at timestamptz,
  p_mode text,
  p_created_by bigint
) RETURNS jsonb
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
  v_session public.seminar_sessions%ROWTYPE;
  v_updated_at timestamptz;
BEGIN
  SELECT * INTO v_session FROM public.seminar_sessions
    WHERE id = p_session_id FOR UPDATE;
  IF NOT FOUND THEN
    RETURN jsonb_build_object('accepted', false, 'reason', 'not_found');
  END IF;
  IF v_session.roster_updated_at IS DISTINCT FROM p_previous_updated_at THEN
    RETURN jsonb_build_object('accepted', false, 'reason', 'conflict');
  END IF;
  IF p_mode IS NULL OR p_mode NOT IN ('attendance', 'absence')
     OR (v_session.day_type = 'mon' AND p_mode <> 'attendance')
     OR (v_session.day_type = 'thu' AND p_mode <> 'absence')
     OR p_member_ids IS NULL OR p_expected_member_ids IS NULL THEN
    RETURN jsonb_build_object('accepted', false, 'reason', 'invalid_roster');
  END IF;
  -- Array references are validated explicitly; historical snapshots may contain
  -- now-inactive members, so current activity status must not rewrite the past.
  IF EXISTS (
    SELECT 1 FROM unnest(p_member_ids || p_expected_member_ids ||
      coalesce(p_previous_member_ids, '{}'::bigint[])) AS supplied(member_id)
    LEFT JOIN public.members m ON m.id = supplied.member_id
    WHERE m.id IS NULL
  ) OR cardinality(p_member_ids) <> (SELECT count(DISTINCT id) FROM unnest(p_member_ids) ids(id))
    OR cardinality(p_expected_member_ids) <> (SELECT count(DISTINCT id) FROM unnest(p_expected_member_ids) ids(id)) THEN
    RETURN jsonb_build_object('accepted', false, 'reason', 'invalid_members');
  END IF;
  IF (p_mode = 'absence' AND p_member_ids && p_expected_member_ids)
    OR (p_mode = 'attendance' AND NOT (p_member_ids @> p_expected_member_ids AND p_expected_member_ids @> p_member_ids)) THEN
    RETURN jsonb_build_object('accepted', false, 'reason', 'invalid_roster');
  END IF;
  IF v_session.planned_member_ids IS NOT NULL AND
    v_session.planned_member_ids IS DISTINCT FROM p_previous_member_ids THEN
    RETURN jsonb_build_object('accepted', false, 'reason', 'conflict');
  END IF;
  v_updated_at := clock_timestamp();
  INSERT INTO public.seminar_roster_imports(
    session_id, mode, member_ids, expected_member_ids, previous_member_ids, created_by, created_at
  ) VALUES (
    p_session_id, p_mode, p_member_ids, p_expected_member_ids,
    p_previous_member_ids, p_created_by, v_updated_at
  );
  UPDATE public.seminar_sessions
    SET planned_member_ids = p_expected_member_ids, roster_updated_at = v_updated_at, capacity = NULL
    WHERE id = p_session_id;
  RETURN jsonb_build_object('accepted', true, 'updated_at', v_updated_at);
END $$;
REVOKE ALL ON FUNCTION public.apply_seminar_roster(uuid, bigint[], bigint[], bigint[], timestamptz, text, bigint)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.apply_seminar_roster(uuid, bigint[], bigint[], bigint[], timestamptz, text, bigint)
  TO service_role;

COMMENT ON COLUMN public.history.group_editor_state IS
  'Editor participant pool and explicit grouping exclusions; not an attendance decision.';
COMMENT ON COLUMN public.seminar_sessions.actual_member_ids IS
  'Confirmed actual attendance, independent of planned roster and group draft.';
COMMENT ON COLUMN public.seminar_terms.attendance_minimum IS
  'Required attendance credits; one credit per Thursday/following Monday weekly seminar, plus confirmed OT and brick-book sessions.';
NOTIFY pgrst, 'reload schema';
COMMIT;
