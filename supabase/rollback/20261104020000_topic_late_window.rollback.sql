-- Reverts 20261104020000_topic_late_window. Events reopened only by the late
-- window close again on the next page load (normal auto-close).
begin;
set local lock_timeout = '5s';
alter table public.topic_events drop column late_until;
commit;
