-- Manual rollback for 20261031130000_seminar_review_guest_link.sql.
-- Refuses to run while unclaimed guest reviews exist (they would violate NOT NULL).
begin;
set local lock_timeout = '5s';
do $$ begin
  if exists (select 1 from public.seminar_reviews where member_id is null)
     or exists (select 1 from public.submission_revisions where member_id is null) then
    raise exception 'guest seminar reviews exist; export and remove or claim them first';
  end if;
end $$;
drop table if exists public.review_edit_attempts;
drop index if exists public.seminar_reviews_form_student_uidx;
alter table public.seminar_reviews
  drop constraint if exists seminar_reviews_identity_check,
  drop constraint if exists seminar_reviews_edit_token_hash_check,
  drop constraint if exists seminar_reviews_student_id_check,
  drop constraint if exists seminar_reviews_author_name_check,
  drop constraint if exists seminar_reviews_identity_kind_check,
  drop column if exists edit_token_hash,
  drop column if exists identity_kind,
  drop column if exists student_id,
  drop column if exists author_name,
  alter column member_id set not null;
alter table public.submission_revisions
  drop constraint if exists submission_revisions_actor_kind_check,
  add constraint submission_revisions_actor_kind_check check (actor_kind in ('member', 'staff')),
  alter column member_id set not null;
commit;
