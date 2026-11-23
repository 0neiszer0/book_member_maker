BEGIN;

ALTER TABLE public.pre_seminar_materials
    ADD COLUMN IF NOT EXISTS seminar_week_id uuid REFERENCES public.seminar_weeks(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS pre_seminar_materials_week_idx
    ON public.pre_seminar_materials (seminar_week_id)
    WHERE seminar_week_id IS NOT NULL;

COMMIT;
