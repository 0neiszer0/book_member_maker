-- 014_secure_brick_book_review_target.sql
-- Brick-book reviews select this table through Flask only; keep it off the browser Data API.

BEGIN;

ALTER TABLE public.brick_books ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.brick_books FROM anon, authenticated;
GRANT ALL ON public.brick_books TO service_role;

-- The server also owns the seminar-review target table.
GRANT ALL ON public.history TO service_role;

COMMIT;
