-- Data change for the cafe import (not a schema migration). Run once, right before import_cafe.py --apply.
-- Rollback: prepare.rollback.sql (after import_cafe.py --rollback).
begin;
set local lock_timeout = '5s';

-- 1) '세미나 후기' board becomes the per-session record board. Slug stays, so old links keep working.
update public.boards set name = '세미나 기록', updated_at = now()
 where slug = 'seminar-reviews' and name = '세미나 후기';

-- 2) Officer-only holding board for cafe photo posts (책크메이트, 정규모임, 친목활동).
insert into public.boards (name, slug, board_type, read_role, write_role, allow_comments, is_active, display_order)
values ('카페 사진 보관함 (검토 중)', 'cafe-photo-review', 'general', 'officer', 'admin', false, true, 90)
on conflict (slug) do nothing;

-- 3) Author account for imported posts. It can never sign in (inactive, blocked, no Kakao id, no password).
insert into public.members (name, social_id, role, is_active, member_status, account_status)
select '카페 보관', 'system:cafe-archive', 'member', false, 'blocked', 'disabled'
 where not exists (select 1 from public.members where social_id = 'system:cafe-archive');

-- 4) Session titles on 2026-01-12 and 2026-01-19 are swapped (cafe 발제문·일지: 0112 사탄탱고, 0119 날개).
update public.history set book_title = case date when '2026-01-12' then '사탄탱고' else '날개' end
 where (date = '2026-01-12' and book_title = '날개') or (date = '2026-01-19' and book_title = '사탄탱고');

-- 5) 2026-10-01 회차 책 제목이 약칭('나사내금')으로 들어가 있어 정식 제목으로 바꾼다 (카페 후기·일지 표기 기준).
update public.history set book_title = '나는 소망한다 내게 금지된 것을'
 where date = '2026-10-01' and book_title = '나사내금';

commit;
