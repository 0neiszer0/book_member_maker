-- Filename aligned with the applied Supabase migration version.
BEGIN;

-- No historical roster is guessed from today's member status.
ALTER TABLE public.seminar_terms
  ADD COLUMN roster_initialized_at timestamptz,
  ADD COLUMN roster_revision integer NOT NULL DEFAULT 0 CHECK (roster_revision >= 0);

CREATE TABLE public.seminar_term_members (
  term_id uuid NOT NULL REFERENCES public.seminar_terms(id) ON DELETE CASCADE,
  member_id bigint NOT NULL REFERENCES public.members(id) ON DELETE RESTRICT,
  status text NOT NULL CHECK (status IN ('active', 'paused', 'left')),
  entry_type text NOT NULL CHECK (entry_type IN ('continuing', 'new', 'returning')),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (term_id, member_id)
);
CREATE INDEX seminar_term_members_member_idx ON public.seminar_term_members(member_id);

CREATE TABLE public.seminar_term_roster_changes (
  term_id uuid NOT NULL REFERENCES public.seminar_terms(id) ON DELETE CASCADE,
  revision integer NOT NULL,
  previous_entries jsonb NOT NULL,
  entries jsonb NOT NULL,
  created_by bigint REFERENCES public.members(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (term_id, revision)
);
CREATE INDEX seminar_term_roster_changes_actor_idx ON public.seminar_term_roster_changes(created_by);
ALTER TABLE public.seminar_term_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.seminar_term_roster_changes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.seminar_term_members, public.seminar_term_roster_changes FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.seminar_term_members, public.seminar_term_roster_changes TO service_role;

CREATE FUNCTION public.save_seminar_term_members(p_term_id uuid, p_revision integer, p_entries jsonb, p_actor bigint)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_term public.seminar_terms%ROWTYPE;
  v_previous jsonb;
  v_entries jsonb;
BEGIN
  SELECT * INTO v_term FROM public.seminar_terms WHERE id = p_term_id FOR UPDATE;
  IF NOT FOUND OR v_term.roster_revision IS DISTINCT FROM p_revision THEN
    RETURN jsonb_build_object('accepted', false, 'reason', 'conflict');
  END IF;
  IF p_entries IS NULL OR jsonb_typeof(p_entries) <> 'array' THEN
    RAISE EXCEPTION 'Invalid roster';
  END IF;
  IF jsonb_array_length(p_entries) > 5000 OR EXISTS (
    SELECT 1 FROM jsonb_to_recordset(p_entries) AS r(member_id bigint, status text, entry_type text)
    WHERE r.member_id IS NULL OR r.status IS NULL OR r.entry_type IS NULL
      OR r.status NOT IN ('active','paused','left') OR r.entry_type NOT IN ('continuing','new','returning')
      OR NOT EXISTS (SELECT 1 FROM public.members m WHERE m.id = r.member_id)
  ) OR EXISTS (
    SELECT 1 FROM jsonb_to_recordset(p_entries) AS r(member_id bigint) GROUP BY member_id HAVING count(*) > 1
  ) THEN
    RAISE EXCEPTION 'Invalid roster entries';
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('member_id', member_id, 'status', status, 'entry_type', entry_type) ORDER BY member_id), '[]'::jsonb)
    INTO v_previous FROM public.seminar_term_members WHERE term_id = p_term_id;
  -- Omitted previous participants are retained as ended, never erased.
  UPDATE public.seminar_term_members SET status = 'left', updated_at = now()
    WHERE term_id = p_term_id AND member_id NOT IN (SELECT r.member_id FROM jsonb_to_recordset(p_entries) AS r(member_id bigint));
  INSERT INTO public.seminar_term_members(term_id, member_id, status, entry_type)
    SELECT p_term_id, r.member_id, r.status, r.entry_type FROM jsonb_to_recordset(p_entries) AS r(member_id bigint, status text, entry_type text)
    ON CONFLICT (term_id, member_id) DO UPDATE SET status = excluded.status, entry_type = excluded.entry_type, updated_at = now();
  UPDATE public.seminar_terms SET roster_revision = roster_revision + 1,
    roster_initialized_at = coalesce(roster_initialized_at, now()) WHERE id = p_term_id;
  SELECT coalesce(jsonb_agg(jsonb_build_object('member_id', member_id, 'status', status, 'entry_type', entry_type) ORDER BY member_id), '[]'::jsonb)
    INTO v_entries FROM public.seminar_term_members WHERE term_id = p_term_id;
  INSERT INTO public.seminar_term_roster_changes(term_id, revision, previous_entries, entries, created_by)
    VALUES (p_term_id, p_revision + 1, v_previous, v_entries, p_actor);
  RETURN jsonb_build_object('accepted', true, 'revision', p_revision + 1);
END $$;
REVOKE ALL ON FUNCTION public.save_seminar_term_members(uuid, integer, jsonb, bigint) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.save_seminar_term_members(uuid, integer, jsonb, bigint) TO service_role;

-- Serialize roster import against semester-roster saves without replacing the
-- established attendance transaction (including undo and absence audit).
CREATE FUNCTION public.apply_seminar_roster_for_term(
  p_session_id uuid, p_member_ids bigint[], p_expected_member_ids bigint[],
  p_previous_member_ids bigint[], p_previous_updated_at timestamptz,
  p_mode text, p_created_by bigint, p_term_revision integer
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE v_revision integer;
BEGIN
  SELECT t.roster_revision INTO v_revision FROM public.seminar_terms t
    JOIN public.seminar_sessions s ON s.term_id = t.id WHERE s.id = p_session_id FOR UPDATE OF t;
  IF NOT FOUND OR v_revision IS DISTINCT FROM p_term_revision THEN
    RETURN jsonb_build_object('accepted', false, 'reason', 'term_conflict');
  END IF;
  RETURN public.apply_seminar_roster(p_session_id, p_member_ids, p_expected_member_ids,
    p_previous_member_ids, p_previous_updated_at, p_mode, p_created_by);
END $$;
REVOKE ALL ON FUNCTION public.apply_seminar_roster_for_term(uuid,bigint[],bigint[],bigint[],timestamptz,text,bigint,integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.apply_seminar_roster_for_term(uuid,bigint[],bigint[],bigint[],timestamptz,text,bigint,integer) TO service_role;
COMMIT;
