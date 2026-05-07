-- 003: 회차별 책 정보 + 관리자가 투표 마감 후에도 수동 추가/제거하기 위한 컬럼

alter table seminar_sessions
  add column if not exists book_title text;

-- 관리자 수동 추가 투표 추적용 (선택적)
alter table seminar_votes
  add column if not exists added_by_admin boolean not null default false;
