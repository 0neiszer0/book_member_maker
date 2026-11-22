-- Online applications and private interview review.
alter table public.recruitment_campaigns
  add column if not exists is_accepting_applications boolean not null default true,
  add column if not exists application_deadline text,
  add column if not exists application_intro text,
  add column if not exists application_questions jsonb not null default '[{"id":"motivation","label":"동아리 지원 동기 및 기대하는 점","placeholder":"책을 읽고 함께 나누고 싶은 이유를 자유롭게 적어주세요.","required":true},{"id":"favorite_book","label":"인상 깊게 읽었거나 함께 나누고 싶은 책","placeholder":"책 제목과 간단한 이유를 적어주세요.","required":true},{"id":"intro","label":"정기 세미나 외에 해보고 싶은 활동이나 자기소개","placeholder":"평소 독서 스타일이나 관심 분야를 자유롭게 적어주세요.","required":false}]'::jsonb,
  add column if not exists interview_slot_options jsonb not null default '[]'::jsonb;
alter table public.recruitment_applicants
  add column if not exists department text,
  add column if not exists phone text,
  add column if not exists knu_email text,
  add column if not exists interview_availability jsonb not null default '[]'::jsonb,
  add column if not exists interview_availability_note text,
  add column if not exists answers jsonb not null default '{}'::jsonb,
  add column if not exists submitted_at timestamptz,
  add column if not exists interview_slot text,
  add column if not exists reviewer_note text;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'recruitment_application_fields_check') then
    alter table public.recruitment_campaigns add constraint recruitment_application_fields_check check (coalesce(length(application_deadline), 0) <= 120 and coalesce(length(application_intro), 0) <= 3000 and jsonb_typeof(application_questions) = 'array' and jsonb_typeof(interview_slot_options) = 'array');
  end if;
  if not exists (select 1 from pg_constraint where conname = 'recruitment_applicant_application_fields_check') then
    alter table public.recruitment_applicants add constraint recruitment_applicant_application_fields_check check (coalesce(length(department), 0) <= 100 and coalesce(length(phone), 0) <= 40 and (knu_email is null or knu_email ~ '^[a-z0-9._%+-]+@knu\.ac\.kr$') and coalesce(length(interview_availability_note), 0) <= 500 and coalesce(length(interview_slot), 0) <= 200 and coalesce(length(reviewer_note), 0) <= 3000 and jsonb_typeof(interview_availability) = 'array' and jsonb_typeof(answers) = 'object');
  end if;
end $$;
