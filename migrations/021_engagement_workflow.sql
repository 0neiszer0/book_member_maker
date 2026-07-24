-- Link-first participation workflow for seminar reviews, book suggestions,
-- and brick-book projects. Flask remains the only database client.

BEGIN;

CREATE TABLE public.book_catalog (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title text NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 200),
    author text NOT NULL CHECK (char_length(btrim(author)) BETWEEN 1 AND 120),
    kyobo_url text NOT NULL UNIQUE CHECK (
        kyobo_url ~ '^https://([a-z0-9-]+\.)*kyobobook\.co\.kr/'
    ),
    cover_path text,
    cover_mime_type text,
    created_by bigint REFERENCES public.members(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.book_suggestions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id uuid NOT NULL REFERENCES public.book_catalog(id) ON DELETE RESTRICT,
    created_by bigint NOT NULL REFERENCES public.members(id) ON DELETE RESTRICT,
    note text NOT NULL CHECK (char_length(btrim(note)) BETWEEN 1 AND 3000),
    status text NOT NULL DEFAULT 'suggested' CHECK (
        status IN ('suggested', 'considering', 'selected', 'completed', 'archived')
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    archived_at timestamptz
);

CREATE TABLE public.book_suggestion_targets (
    suggestion_id uuid NOT NULL REFERENCES public.book_suggestions(id) ON DELETE CASCADE,
    target_type text NOT NULL CHECK (target_type IN ('curriculum', 'brick_book')),
    PRIMARY KEY (suggestion_id, target_type)
);

CREATE TABLE public.book_suggestion_supporters (
    suggestion_id uuid NOT NULL REFERENCES public.book_suggestions(id) ON DELETE CASCADE,
    member_id bigint NOT NULL REFERENCES public.members(id) ON DELETE CASCADE,
    reason text CHECK (reason IS NULL OR char_length(reason) <= 500),
    created_at timestamptz NOT NULL DEFAULT now(),
    withdrawn_at timestamptz,
    PRIMARY KEY (suggestion_id, member_id)
);

CREATE TABLE public.book_suggestion_comments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    suggestion_id uuid NOT NULL REFERENCES public.book_suggestions(id) ON DELETE CASCADE,
    member_id bigint NOT NULL REFERENCES public.members(id) ON DELETE RESTRICT,
    content text NOT NULL CHECK (char_length(btrim(content)) BETWEEN 1 AND 2000),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);

CREATE TABLE public.seminar_review_forms (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    seminar_session_id uuid NOT NULL UNIQUE REFERENCES public.seminar_sessions(id) ON DELETE RESTRICT,
    share_token uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    instructions text CHECK (instructions IS NULL OR char_length(instructions) <= 2000),
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'open', 'closed')),
    open_at timestamptz,
    close_at timestamptz,
    created_by bigint REFERENCES public.members(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (close_at IS NULL OR open_at IS NULL OR close_at > open_at)
);

CREATE TABLE public.seminar_reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    form_id uuid NOT NULL REFERENCES public.seminar_review_forms(id) ON DELETE RESTRICT,
    seminar_session_id uuid NOT NULL REFERENCES public.seminar_sessions(id) ON DELETE RESTRICT,
    member_id bigint NOT NULL REFERENCES public.members(id) ON DELETE RESTRICT,
    memorable_point text NOT NULL CHECK (char_length(btrim(memorable_point)) BETWEEN 1 AND 5000),
    discussion_point text CHECK (discussion_point IS NULL OR char_length(discussion_point) <= 5000),
    free_text text CHECK (free_text IS NULL OR char_length(free_text) <= 10000),
    image_path text,
    image_mime_type text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    UNIQUE (form_id, member_id)
);

CREATE TABLE public.brick_projects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    book_id uuid NOT NULL REFERENCES public.book_catalog(id) ON DELETE RESTRICT,
    source_suggestion_id uuid REFERENCES public.book_suggestions(id) ON DELETE SET NULL,
    title text NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 200),
    description text NOT NULL CHECK (char_length(btrim(description)) BETWEEN 1 AND 5000),
    coordinator_id bigint REFERENCES public.members(id) ON DELETE SET NULL,
    capacity integer CHECK (capacity IS NULL OR capacity BETWEEN 1 AND 100),
    recruitment_start_at timestamptz,
    recruitment_end_at timestamptz,
    planned_start_date date,
    planned_end_date date,
    actual_start_date date,
    actual_end_date date,
    status text NOT NULL DEFAULT 'draft' CHECK (
        status IN ('draft', 'recruiting', 'active', 'completed', 'archived')
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        recruitment_end_at IS NULL OR recruitment_start_at IS NULL
        OR recruitment_end_at > recruitment_start_at
    ),
    CHECK (
        planned_end_date IS NULL OR planned_start_date IS NULL
        OR planned_end_date >= planned_start_date
    )
);

CREATE TABLE public.brick_recruitments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL UNIQUE REFERENCES public.brick_projects(id) ON DELETE RESTRICT,
    share_token uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    instructions text CHECK (instructions IS NULL OR char_length(instructions) <= 3000),
    status text NOT NULL DEFAULT 'draft' CHECK (
        status IN ('draft', 'open', 'closed', 'finalized')
    ),
    open_at timestamptz,
    close_at timestamptz,
    created_by bigint REFERENCES public.members(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.brick_applications (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    recruitment_id uuid NOT NULL REFERENCES public.brick_recruitments(id) ON DELETE RESTRICT,
    project_id uuid NOT NULL REFERENCES public.brick_projects(id) ON DELETE RESTRICT,
    member_id bigint NOT NULL REFERENCES public.members(id) ON DELETE RESTRICT,
    motivation text NOT NULL CHECK (char_length(btrim(motivation)) BETWEEN 1 AND 5000),
    availability text CHECK (availability IS NULL OR char_length(availability) <= 2000),
    note text CHECK (note IS NULL OR char_length(note) <= 2000),
    status text NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'accepted', 'rejected', 'withdrawn')
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (recruitment_id, member_id)
);

CREATE TABLE public.brick_project_members (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.brick_projects(id) ON DELETE RESTRICT,
    member_id bigint NOT NULL REFERENCES public.members(id) ON DELETE RESTRICT,
    application_id uuid REFERENCES public.brick_applications(id) ON DELETE SET NULL,
    role text NOT NULL DEFAULT 'member' CHECK (role IN ('leader', 'member')),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'withdrawn')),
    joined_at timestamptz NOT NULL DEFAULT now(),
    left_at timestamptz,
    UNIQUE (project_id, member_id)
);

CREATE TABLE public.brick_review_forms (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL UNIQUE REFERENCES public.brick_projects(id) ON DELETE RESTRICT,
    share_token uuid NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    instructions text CHECK (instructions IS NULL OR char_length(instructions) <= 2000),
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'open', 'closed')),
    open_at timestamptz,
    close_at timestamptz,
    created_by bigint REFERENCES public.members(id) ON DELETE SET NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.brick_reviews (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    form_id uuid NOT NULL REFERENCES public.brick_review_forms(id) ON DELETE RESTRICT,
    project_id uuid NOT NULL REFERENCES public.brick_projects(id) ON DELETE RESTRICT,
    member_id bigint NOT NULL REFERENCES public.members(id) ON DELETE RESTRICT,
    memorable_point text NOT NULL CHECK (char_length(btrim(memorable_point)) BETWEEN 1 AND 5000),
    free_text text CHECK (free_text IS NULL OR char_length(free_text) <= 10000),
    image_path text,
    image_mime_type text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    UNIQUE (form_id, member_id)
);

CREATE TABLE public.brick_project_status_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES public.brick_projects(id) ON DELETE CASCADE,
    from_status text,
    to_status text NOT NULL,
    changed_by bigint REFERENCES public.members(id) ON DELETE SET NULL,
    note text CHECK (note IS NULL OR char_length(note) <= 1000),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE public.submission_revisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_type text NOT NULL CHECK (
        submission_type IN ('seminar_review', 'brick_application', 'brick_review')
    ),
    submission_id uuid NOT NULL,
    member_id bigint NOT NULL REFERENCES public.members(id) ON DELETE RESTRICT,
    payload jsonb NOT NULL,
    actor_kind text NOT NULL DEFAULT 'member' CHECK (actor_kind IN ('member', 'staff')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX book_suggestions_book_id_idx ON public.book_suggestions(book_id);
CREATE INDEX book_suggestions_created_by_idx ON public.book_suggestions(created_by);
CREATE INDEX book_suggestions_status_created_idx ON public.book_suggestions(status, created_at DESC);
CREATE INDEX book_suggestion_supporters_member_idx ON public.book_suggestion_supporters(member_id);
CREATE INDEX book_suggestion_comments_suggestion_idx ON public.book_suggestion_comments(suggestion_id, created_at);
CREATE INDEX book_suggestion_comments_member_idx ON public.book_suggestion_comments(member_id);
CREATE INDEX seminar_review_forms_status_idx ON public.seminar_review_forms(status, close_at);
CREATE INDEX seminar_reviews_session_idx ON public.seminar_reviews(seminar_session_id);
CREATE INDEX seminar_reviews_member_idx ON public.seminar_reviews(member_id);
CREATE INDEX brick_projects_book_idx ON public.brick_projects(book_id);
CREATE INDEX brick_projects_status_idx ON public.brick_projects(status, recruitment_end_at);
CREATE INDEX brick_projects_source_suggestion_idx ON public.brick_projects(source_suggestion_id);
CREATE INDEX brick_applications_project_idx ON public.brick_applications(project_id, status);
CREATE INDEX brick_applications_member_idx ON public.brick_applications(member_id);
CREATE INDEX brick_project_members_member_idx ON public.brick_project_members(member_id);
CREATE INDEX brick_reviews_project_idx ON public.brick_reviews(project_id);
CREATE INDEX brick_reviews_member_idx ON public.brick_reviews(member_id);
CREATE INDEX brick_project_status_history_project_idx ON public.brick_project_status_history(project_id, created_at);
CREATE INDEX submission_revisions_submission_idx ON public.submission_revisions(submission_type, submission_id, created_at);
CREATE INDEX submission_revisions_member_idx ON public.submission_revisions(member_id);

CREATE OR REPLACE FUNCTION public.accept_brick_application(p_application_id uuid)
RETURNS void
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    target public.brick_applications%ROWTYPE;
    target_capacity integer;
    accepted_count integer;
BEGIN
    SELECT * INTO target
      FROM public.brick_applications
     WHERE id = p_application_id
     FOR UPDATE;

    IF target.id IS NULL THEN
        RAISE EXCEPTION 'application_not_found';
    END IF;

    SELECT capacity INTO target_capacity
      FROM public.brick_projects
     WHERE id = target.project_id
     FOR UPDATE;

    SELECT count(*) INTO accepted_count
      FROM public.brick_applications
     WHERE project_id = target.project_id
       AND status = 'accepted'
       AND id <> target.id;

    IF target_capacity IS NOT NULL AND accepted_count >= target_capacity THEN
        RAISE EXCEPTION 'project_capacity_reached';
    END IF;

    UPDATE public.brick_applications
       SET status = 'accepted', updated_at = now()
     WHERE id = target.id;

    INSERT INTO public.brick_project_members(project_id, member_id, application_id)
    VALUES (target.project_id, target.member_id, target.id)
    ON CONFLICT (project_id, member_id)
    DO UPDATE SET application_id = EXCLUDED.application_id,
                  status = 'active',
                  left_at = NULL;
END;
$$;

-- Explicit server-only access. RLS is defense in depth; Flask uses service_role.
DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'book_catalog', 'book_suggestions', 'book_suggestion_targets',
        'book_suggestion_supporters', 'book_suggestion_comments',
        'seminar_review_forms', 'seminar_reviews', 'brick_projects',
        'brick_recruitments', 'brick_applications', 'brick_project_members',
        'brick_review_forms', 'brick_reviews', 'brick_project_status_history',
        'submission_revisions'
    ]
    LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('REVOKE ALL PRIVILEGES ON public.%I FROM anon, authenticated', table_name);
        EXECUTE format(
            'GRANT SELECT, INSERT, UPDATE, DELETE ON public.%I TO service_role',
            table_name
        );
    END LOOP;
END
$$;

REVOKE ALL PRIVILEGES ON FUNCTION public.accept_brick_application(uuid)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.accept_brick_application(uuid) TO service_role;

-- Public downloads are intentional for optional covers and one-photo reviews.
-- Uploads are performed only by Flask with service_role.
INSERT INTO storage.buckets(id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'engagement-images',
    'engagement-images',
    true,
    1048576,
    ARRAY['image/webp']
)
ON CONFLICT (id) DO UPDATE
SET public = EXCLUDED.public,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

COMMIT;
