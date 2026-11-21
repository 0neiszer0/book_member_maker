begin;
set local lock_timeout = '5s';

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

update public.seminar_sessions
set participation_mode = 'opt_in'
where day_type = 'thu'
  and participation_mode = 'absence_only'
  and attendance_confirmed_at is null
  and planned_member_ids is null
  and meeting_date > (clock_timestamp() at time zone 'Asia/Seoul')::date;

notify pgrst, 'reload schema';
commit;
