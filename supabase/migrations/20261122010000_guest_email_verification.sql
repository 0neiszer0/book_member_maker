alter table public.topic_submissions add column if not exists knu_email text
  check (knu_email is null or knu_email ~ '^[a-z0-9._%+-]+@knu\.ac\.kr$');
alter table public.seminar_reviews add column if not exists knu_email text
  check (knu_email is null or knu_email ~ '^[a-z0-9._%+-]+@knu\.ac\.kr$');
alter table public.club_room_bookings add column if not exists knu_email text
  check (knu_email is null or knu_email ~ '^[a-z0-9._%+-]+@knu\.ac\.kr$');
alter table public.email_auth_codes drop constraint if exists email_auth_codes_purpose_check;
alter table public.email_auth_codes add constraint email_auth_codes_purpose_check
  check (purpose in ('login', 'signup', 'pin_reset', 'topic_edit', 'review_edit', 'room_edit'));
