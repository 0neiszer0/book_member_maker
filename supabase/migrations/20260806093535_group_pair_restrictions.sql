begin;

create table public.group_pair_restrictions (
  id bigint generated always as identity primary key,
  member_a_id bigint not null references public.members(id) on delete cascade,
  member_b_id bigint not null references public.members(id) on delete cascade,
  note text check (note is null or char_length(note) <= 200),
  created_by_member_id bigint references public.members(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint group_pair_restrictions_member_order_check check (member_a_id < member_b_id),
  constraint group_pair_restrictions_member_pair_key unique (member_a_id, member_b_id)
);

comment on table public.group_pair_restrictions is
  '조 편성에서 같은 조가 되면 안 되는 회원 쌍. Flask의 primary admin만 조회·관리한다.';

create index group_pair_restrictions_member_a_idx
  on public.group_pair_restrictions (member_a_id);
create index group_pair_restrictions_member_b_idx
  on public.group_pair_restrictions (member_b_id);
create index group_pair_restrictions_created_by_idx
  on public.group_pair_restrictions (created_by_member_id)
  where created_by_member_id is not null;

alter table public.group_pair_restrictions enable row level security;
revoke all on table public.group_pair_restrictions from public, anon, authenticated;
grant select, insert, update, delete on table public.group_pair_restrictions to service_role;

revoke all on sequence public.group_pair_restrictions_id_seq from public, anon, authenticated;
grant usage, select on sequence public.group_pair_restrictions_id_seq to service_role;

commit;
