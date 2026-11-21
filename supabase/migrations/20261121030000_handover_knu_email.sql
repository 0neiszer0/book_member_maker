begin;
set local lock_timeout = '5s';

alter table public.officer_handover_responses
  add column if not exists knu_email text
    check (knu_email is null or knu_email ~ '^[a-z0-9._%+-]+@knu\.ac\.kr$');

commit;
