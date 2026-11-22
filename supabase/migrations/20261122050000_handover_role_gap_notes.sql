-- Role-tailored wiki-gap notes for the officer handover survey.
-- A single nullable text column keeps existing rows and older fake DBs working
-- with zero breaking schema changes.
begin;
set local lock_timeout = '5s';

alter table public.officer_handover_responses
  add column if not exists role_gap_notes text;

commit;

-- Rollback:
-- begin;
-- alter table public.officer_handover_responses drop column if exists role_gap_notes;
-- commit;
