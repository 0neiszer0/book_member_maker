-- 발제문 추가 제출 기간: officers can keep (or reopen) a topic event for late
-- submissions until late_until. The original deadline (세미나 주 화요일 23:59) is
-- still computed from the session dates and is not changed.
-- Rollback: supabase/rollback/20261104020000_topic_late_window.rollback.sql
begin;
set local lock_timeout = '5s';
alter table public.topic_events add column late_until timestamptz;
commit;
