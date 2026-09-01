# Legacy database migrations

> 새 마이그레이션은 `supabase/migrations/`에 Supabase CLI 타임스탬프 형식으로
> 생성한다. 이 폴더의 `001`~`029` 파일은 운영 이력 대조와 감사용으로 보존하며,
> 신규 변경을 여기에 추가하지 않는다.

이 디렉터리의 SQL은 운영 Supabase에 자동 적용되지 않는다. `001` 이전에 생성된
`members`, `attendance`, `history`, `notifications`, `questions`, `documents`,
`bookclub_co_matrix` 등 레거시 기본 테이블이 이미 존재한다는 전제에서 시작한다.
따라서 현재 파일만으로 빈 프로젝트를 완전히 재구성할 수는 없다.

## 운영 적용 원칙

1. 운영 스키마와 백업 상태를 먼저 확인한다.
2. 새 파일은 `npx supabase migration new <name>`으로 `supabase/migrations/`에 생성하고
   `BEGIN`/`COMMIT`을 사용한다.
3. 테이블·함수·스토리지 변경은 RLS, `anon`/`authenticated` 권한 회수,
   `service_role` 권한 및 필요한 인덱스를 함께 검토한다.
4. SQL과 애플리케이션의 배포 순서를 정한다. 이전 앱과 호환되지 않는 변경은
   확장 → 코드 배포 → 정리의 단계적 변경으로 나눈다.
5. Supabase SQL Editor 또는 승인된 CLI에서 사람이 검토한 SQL만 실행한다.
6. 적용 후 테이블/함수 존재, RLS, 인덱스와 핵심 읽기·쓰기 흐름을 검증한다.

## Canonical baseline

개인정보와 운영 데이터를 포함하지 않는 schema-only 기준선과 원격 타임스탬프
대응 파일은 `supabase/migrations/`에 있다. 상세 대응 관계와 아직 필요한 원격 이력
정렬 절차는 `docs/SUPABASE_MIGRATION_BASELINE.md`를 따른다.


## 회원 병합 트랜잭션 준비

현재 Flask의 회원 병합은 여러 HTTP DB 요청으로 나뉘어 있어 원자적이지 않다.
하지만 레거시 baseline이 없어 참조 테이블을 추측해 RPC를 만들면 이력을 누락할 수
있다. 먼저 운영 SQL Editor에서 아래 **읽기 전용 스키마 조회**를 실행하고 결과를
검토한 뒤 `merge_members_transaction` 함수를 작성한다. 이 SQL은 회원 데이터 값을
조회하거나 변경하지 않는다.

```sql
select
  ns.nspname as schema_name,
  rel.relname as table_name,
  att.attname as column_name,
  con.conname as constraint_name,
  pg_get_constraintdef(con.oid) as definition
from pg_constraint con
join pg_class rel on rel.oid = con.conrelid
join pg_namespace ns on ns.oid = rel.relnamespace
join lateral unnest(con.conkey) with ordinality as cols(attnum, ord) on true
join pg_attribute att
  on att.attrelid = con.conrelid
 and att.attnum = cols.attnum
where con.contype = 'f'
  and con.confrelid = 'public.members'::regclass
order by ns.nspname, rel.relname, con.conname, cols.ord;
```

확정 RPC는 source/target 회원을 `FOR UPDATE`로 잠그고, 고유키 중복을 명시적으로
병합한 후 모든 참조 이동과 source 삭제를 하나의 PostgreSQL 트랜잭션에서 수행해야
한다. 함수 권한은 `PUBLIC`, `anon`, `authenticated`에서 회수하고 `service_role`에만
부여한다.
