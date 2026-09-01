-- 013_board_foreign_key_indexes.sql
-- Cover review targets and comment authors so deletes and review filtering stay fast.

BEGIN;

CREATE INDEX IF NOT EXISTS posts_history_idx
    ON public.posts(history_id)
    WHERE history_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS posts_brick_book_idx
    ON public.posts(brick_book_id)
    WHERE brick_book_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS post_comments_author_idx
    ON public.post_comments(author_id);

COMMIT;
