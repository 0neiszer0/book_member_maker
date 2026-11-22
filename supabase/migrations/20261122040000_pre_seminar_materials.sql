CREATE TABLE IF NOT EXISTS public.pre_seminar_materials (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug text NOT NULL UNIQUE,
    title text NOT NULL,
    author text NOT NULL DEFAULT '',
    semester text NOT NULL DEFAULT '',
    semester_label text NOT NULL DEFAULT '',
    seminar_date text NOT NULL DEFAULT '',
    edition_note text NOT NULL DEFAULT '',
    markdown_body text NOT NULL DEFAULT '',
    is_published boolean NOT NULL DEFAULT true,
    created_by bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS pre_seminar_materials_published_idx
    ON public.pre_seminar_materials (is_published, seminar_date DESC, created_at DESC);
