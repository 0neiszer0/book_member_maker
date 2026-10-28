begin;
set local lock_timeout = '5s';
-- Existing notices stay global (NULL). A term cannot be deleted while its notices exist.
alter table public.posts add column term_id uuid references public.seminar_terms(id) on delete restrict;
create index posts_term_id_idx on public.posts(term_id);
comment on column public.posts.term_id is 'Notice display scope; NULL applies to every term. Existing Flask board permissions still apply.';
commit;
