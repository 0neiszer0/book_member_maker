-- 012_integrated_workflow_boards.sql
-- 세미나 회차를 발제문/조 편성 기록의 기준으로 연결하고 범용 게시판을 추가한다.

BEGIN;

-- ---------------------------------------------------------------------------
-- 세미나 회차 중심 연결
-- ---------------------------------------------------------------------------
ALTER TABLE public.seminar_sessions
    ADD COLUMN IF NOT EXISTS book_author text;

ALTER TABLE public.topic_events
    ADD COLUMN IF NOT EXISTS seminar_session_id uuid
        REFERENCES public.seminar_sessions(id) ON DELETE SET NULL;

ALTER TABLE public.history
    ADD COLUMN IF NOT EXISTS seminar_session_id uuid
        REFERENCES public.seminar_sessions(id) ON DELETE SET NULL;

CREATE UNIQUE INDEX IF NOT EXISTS topic_events_seminar_session_uidx
    ON public.topic_events(seminar_session_id)
    WHERE seminar_session_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS history_seminar_session_uidx
    ON public.history(seminar_session_id)
    WHERE seminar_session_id IS NOT NULL;

-- 날짜가 양쪽에서 유일하게 일치하는 기존 데이터만 안전하게 연결한다.
WITH unique_sessions AS (
    SELECT meeting_date, min(id::text)::uuid AS session_id
    FROM public.seminar_sessions
    GROUP BY meeting_date
    HAVING count(*) = 1
), unique_topics AS (
    SELECT meeting_date
    FROM public.topic_events
    GROUP BY meeting_date
    HAVING count(*) = 1
)
UPDATE public.topic_events te
SET seminar_session_id = us.session_id
FROM unique_sessions us
JOIN unique_topics ut ON ut.meeting_date = us.meeting_date
WHERE te.meeting_date = us.meeting_date
  AND te.seminar_session_id IS NULL;

WITH unique_sessions AS (
    SELECT meeting_date, min(id::text)::uuid AS session_id
    FROM public.seminar_sessions
    GROUP BY meeting_date
    HAVING count(*) = 1
), unique_history AS (
    SELECT date
    FROM public.history
    WHERE date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
    GROUP BY date
    HAVING count(*) = 1
)
UPDATE public.history h
SET seminar_session_id = us.session_id
FROM unique_sessions us
JOIN unique_history uh ON uh.date = us.meeting_date::text
WHERE h.date = us.meeting_date::text
  AND h.seminar_session_id IS NULL;

-- ---------------------------------------------------------------------------
-- 게시판
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.boards (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,48}$'),
    board_type text NOT NULL DEFAULT 'general'
        CHECK (board_type IN ('general', 'seminar_review', 'brick_book_review')),
    read_role text NOT NULL DEFAULT 'member'
        CHECK (read_role IN ('member', 'officer', 'admin')),
    write_role text NOT NULL DEFAULT 'member'
        CHECK (write_role IN ('member', 'officer', 'admin')),
    allow_comments boolean NOT NULL DEFAULT true,
    is_active boolean NOT NULL DEFAULT true,
    display_order integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.posts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    board_id uuid NOT NULL REFERENCES public.boards(id) ON DELETE RESTRICT,
    author_id bigint NOT NULL REFERENCES public.members(id) ON DELETE RESTRICT,
    title text NOT NULL CHECK (char_length(btrim(title)) BETWEEN 1 AND 200),
    content text NOT NULL CHECK (char_length(btrim(content)) BETWEEN 1 AND 50000),
    history_id uuid REFERENCES public.history(id) ON DELETE SET NULL,
    brick_book_id uuid REFERENCES public.brick_books(id) ON DELETE SET NULL,
    is_pinned boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz,
    CHECK (NOT (history_id IS NOT NULL AND brick_book_id IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS public.post_comments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id uuid NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
    author_id bigint NOT NULL REFERENCES public.members(id) ON DELETE RESTRICT,
    content text NOT NULL CHECK (char_length(btrim(content)) BETWEEN 1 AND 5000),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    deleted_at timestamptz
);

CREATE TABLE IF NOT EXISTS public.post_attachments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id uuid NOT NULL REFERENCES public.posts(id) ON DELETE CASCADE,
    storage_path text NOT NULL UNIQUE,
    original_name text NOT NULL,
    mime_type text NOT NULL,
    byte_size bigint NOT NULL CHECK (byte_size > 0 AND byte_size <= 10485760),
    display_order integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS boards_active_order_idx
    ON public.boards(is_active, display_order, name);
CREATE INDEX IF NOT EXISTS posts_board_created_idx
    ON public.posts(board_id, is_pinned DESC, created_at DESC)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS posts_author_idx ON public.posts(author_id);
CREATE INDEX IF NOT EXISTS post_comments_post_created_idx
    ON public.post_comments(post_id, created_at)
    WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS post_attachments_post_idx
    ON public.post_attachments(post_id, display_order);

INSERT INTO public.boards
    (name, slug, board_type, read_role, write_role, allow_comments, display_order)
VALUES
    ('공지사항', 'notices', 'general', 'member', 'officer', true, 10),
    ('자유게시판', 'free', 'general', 'member', 'member', true, 20),
    ('세미나 후기', 'seminar-reviews', 'seminar_review', 'member', 'member', true, 30),
    ('벽돌책 후기', 'brick-book-reviews', 'brick_book_review', 'member', 'member', true, 40)
ON CONFLICT (slug) DO NOTHING;

-- Render 로컬 디스크가 아니라 비공개 Storage에 이미지를 보관한다.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'board-uploads',
    'board-uploads',
    false,
    10485760,
    ARRAY['image/jpeg', 'image/png', 'image/webp', 'image/gif']
)
ON CONFLICT (id) DO UPDATE
SET public = false,
    file_size_limit = EXCLUDED.file_size_limit,
    allowed_mime_types = EXCLUDED.allowed_mime_types;

-- Flask 서버(service_role)만 Data API를 통해 접근한다.
ALTER TABLE public.seminar_terms ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.seminar_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.seminar_votes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.topic_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.topic_submissions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.boards ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.posts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.post_comments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.post_attachments ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.boards, public.posts, public.post_comments, public.post_attachments
    FROM anon, authenticated;
GRANT ALL ON public.boards, public.posts, public.post_comments, public.post_attachments
    TO service_role;
GRANT ALL ON public.seminar_terms, public.seminar_sessions, public.seminar_votes,
    public.topic_events, public.topic_submissions TO service_role;

COMMIT;
