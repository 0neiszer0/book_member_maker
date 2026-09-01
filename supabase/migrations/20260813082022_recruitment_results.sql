begin;

create table if not exists public.recruitment_campaigns (
  id uuid primary key default gen_random_uuid(),
  title text not null,
  share_token uuid not null unique default gen_random_uuid(),
  intro_text text not null default '지원할 때 사용한 이름과 학번을 입력하면 결과를 확인할 수 있습니다.',
  pending_message text not null default '아직 결과 발표 전입니다. 안내된 발표 시각 이후 다시 확인해주세요.',
  accepted_message text not null default '합격을 축하드립니다. 아래 안내를 확인해주세요.',
  waitlisted_message text not null default '예비 합격 상태입니다. 추가 안내를 기다려주세요.',
  rejected_message text not null default '아쉽게도 이번 모집에서는 함께하지 못하게 되었습니다. 지원해주셔서 감사합니다.',
  contact_text text,
  is_active boolean not null default true,
  is_published boolean not null default false,
  created_by bigint references public.members(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint recruitment_campaigns_title_length check (char_length(btrim(title)) between 1 and 120),
  constraint recruitment_campaigns_intro_length check (char_length(intro_text) <= 2000),
  constraint recruitment_campaigns_message_lengths check (
    char_length(pending_message) <= 3000
    and char_length(accepted_message) <= 3000
    and char_length(waitlisted_message) <= 3000
    and char_length(rejected_message) <= 3000
    and (contact_text is null or char_length(contact_text) <= 1000)
  )
);

create table if not exists public.recruitment_applicants (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references public.recruitment_campaigns(id) on delete cascade,
  name text not null,
  name_key text not null,
  student_id text not null,
  result_status text not null default 'pending',
  personal_message text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint recruitment_applicants_identity unique (campaign_id, student_id),
  constraint recruitment_applicants_name_length check (char_length(btrim(name)) between 1 and 80),
  constraint recruitment_applicants_name_key_length check (char_length(name_key) between 1 and 80),
  constraint recruitment_applicants_student_id_format check (student_id ~ '^[0-9]{4,20}$'),
  constraint recruitment_applicants_status check (result_status in ('pending', 'accepted', 'waitlisted', 'rejected')),
  constraint recruitment_applicants_personal_message_length check (personal_message is null or char_length(personal_message) <= 3000)
);

create table if not exists public.recruitment_lookup_attempts (
  id uuid primary key default gen_random_uuid(),
  campaign_id uuid not null references public.recruitment_campaigns(id) on delete cascade,
  ip_hash text not null,
  succeeded boolean not null default false,
  created_at timestamptz not null default now(),
  constraint recruitment_lookup_attempts_hash_length check (char_length(ip_hash) = 64)
);

create index if not exists recruitment_campaigns_created_idx
  on public.recruitment_campaigns(created_at desc);
create index if not exists recruitment_applicants_campaign_status_idx
  on public.recruitment_applicants(campaign_id, result_status, name);
create index if not exists recruitment_applicants_lookup_idx
  on public.recruitment_applicants(campaign_id, student_id, name_key);
create index if not exists recruitment_lookup_attempts_rate_idx
  on public.recruitment_lookup_attempts(campaign_id, ip_hash, created_at desc);

alter table public.recruitment_campaigns enable row level security;
alter table public.recruitment_applicants enable row level security;
alter table public.recruitment_lookup_attempts enable row level security;

revoke all on table public.recruitment_campaigns from public, anon, authenticated;
revoke all on table public.recruitment_applicants from public, anon, authenticated;
revoke all on table public.recruitment_lookup_attempts from public, anon, authenticated;
grant select, insert, update, delete on table public.recruitment_campaigns to service_role;
grant select, insert, update, delete on table public.recruitment_applicants to service_role;
grant select, insert, update, delete on table public.recruitment_lookup_attempts to service_role;

comment on table public.recruitment_campaigns is
  '면접 결과 발표 차수와 공개 안내문. Flask 서버의 운영진 화면에서만 관리한다.';
comment on table public.recruitment_applicants is
  '차수별 지원자 식별 정보와 결과. 공개 브라우저에는 직접 노출하지 않고 Flask의 정확 일치 조회만 허용한다.';
comment on table public.recruitment_lookup_attempts is
  '결과 조회 남용 방지를 위한 IP 단방향 해시 기반 시도 기록. 원본 IP는 저장하지 않는다.';

commit;
