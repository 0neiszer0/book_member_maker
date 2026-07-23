-- 로그인 회원의 버그·개선 제보를 서버를 통해서만 저장한다.

BEGIN;

CREATE TABLE IF NOT EXISTS public.bug_reports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    reporter_id bigint REFERENCES public.members(id) ON DELETE SET NULL,
    reporter_name text NOT NULL,
    category text NOT NULL DEFAULT 'bug',
    title text NOT NULL,
    description text NOT NULL,
    source_page text NOT NULL DEFAULT 'unknown',
    user_agent text,
    status text NOT NULL DEFAULT 'new',
    admin_note text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    CONSTRAINT bug_reports_category_check CHECK (category IN ('bug', 'suggestion')),
    CONSTRAINT bug_reports_status_check CHECK (status IN ('new', 'reviewing', 'resolved')),
    CONSTRAINT bug_reports_title_length_check CHECK (char_length(title) BETWEEN 2 AND 120),
    CONSTRAINT bug_reports_description_length_check CHECK (char_length(description) BETWEEN 10 AND 3000)
);

CREATE INDEX IF NOT EXISTS bug_reports_status_created_idx
    ON public.bug_reports(status, created_at DESC);
CREATE INDEX IF NOT EXISTS bug_reports_reporter_idx
    ON public.bug_reports(reporter_id, created_at DESC)
    WHERE reporter_id IS NOT NULL;

ALTER TABLE public.bug_reports ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.bug_reports FROM anon, authenticated;
GRANT ALL ON public.bug_reports TO service_role;

COMMENT ON TABLE public.bug_reports IS
    '앱 내부에서 접수된 버그 및 개선 제보. Flask 서버의 service_role만 접근한다.';

COMMIT;
