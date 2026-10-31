-- Undo prepare.sql. Run import_cafe.py --rollback --state <state file> first.
begin;
set local lock_timeout = '5s';
do $$ begin
  if exists (select 1 from public.posts p join public.members m on m.id = p.author_id
              where m.social_id = 'system:cafe-archive') then
    raise exception 'imported cafe posts still exist; run import_cafe.py --rollback first';
  end if;
  if exists (select 1 from public.posts p join public.boards b on b.id = p.board_id
              where b.slug = 'cafe-photo-review') then
    raise exception 'cafe-photo-review still has posts';
  end if;
end $$;
delete from public.boards where slug = 'cafe-photo-review';
delete from public.members where social_id = 'system:cafe-archive';
update public.boards set name = '세미나 후기', updated_at = now()
 where slug = 'seminar-reviews' and name = '세미나 기록';
update public.history set book_title = case date when '2026-01-12' then '날개' else '사탄탱고' end
 where (date = '2026-01-12' and book_title = '사탄탱고') or (date = '2026-01-19' and book_title = '날개');
update public.history set book_title = '나사내금'
 where date = '2026-10-01' and book_title = '나는 소망한다 내게 금지된 것을';
commit;
