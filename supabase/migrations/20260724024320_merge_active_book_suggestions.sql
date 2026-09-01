BEGIN;

-- A Kyobo product identifies one catalog book, and one active conversation is
-- kept for that book. Archived suggestions may be proposed again later.
CREATE UNIQUE INDEX book_suggestions_one_active_per_book_idx
ON public.book_suggestions(book_id)
WHERE status <> 'archived';

COMMIT;
