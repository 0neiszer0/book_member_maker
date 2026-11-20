-- Public no-login officer handover wiki survey forms and responses.
begin;
set local lock_timeout = '5s';

create table if not exists public.officer_handover_forms (
  id uuid primary key default gen_random_uuid(),
  share_token uuid not null unique default gen_random_uuid(),
  title text not null,
  term_label text,
  status text not null default 'open' check (status in ('open', 'closed')),
  created_by integer,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.officer_handover_responses (
  id uuid primary key default gen_random_uuid(),
  form_id uuid not null references public.officer_handover_forms(id) on delete cascade,
  role_name text not null,
  author_name text,
  term_cohort text,
  core_tasks text not null,
  hardships_and_tips text,
  assets_and_links text,
  common_issues text,
  next_officer_note text,
  created_at timestamptz not null default now()
);

create index if not exists officer_handover_forms_share_token_idx
  on public.officer_handover_forms(share_token);

create index if not exists officer_handover_responses_form_created_idx
  on public.officer_handover_responses(form_id, created_at desc);

alter table public.officer_handover_forms enable row level security;
alter table public.officer_handover_responses enable row level security;

revoke all on table public.officer_handover_forms from public, anon, authenticated;
revoke all on table public.officer_handover_responses from public, anon, authenticated;
grant select, insert, update, delete on table public.officer_handover_forms to service_role;
grant select, insert, update, delete on table public.officer_handover_responses to service_role;

commit;

-- Rollback:
-- begin;
-- drop table if exists public.officer_handover_responses;
-- drop table if exists public.officer_handover_forms;
-- commit;
