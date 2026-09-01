# Supabase 마이그레이션 기준선

점검일: 2026-09-01
프로젝트: `lzvfkbekhbcqfbknldmo`

## 결론

- 앞으로의 정식 마이그레이션 경로는 `supabase/migrations/`이다.
- 기존 `migrations/001_...029_...sql`은 삭제하지 않고 감사용 레거시 자료로 남긴다.
- 기준선에는 운영 회원·출석·발제·모집 데이터가 들어 있지 않다.
- 브라우저 역할에 DB 권한을 주지 않는 기존 서버 전용 구조를 유지한다.
- 원격 마이그레이션 이력은 아직 변경하지 않았다. 아래 정렬 절차가 끝나기 전에는
  `supabase db push`를 실행하면 안 된다.

## 구성

`20260501000000_legacy_schema_baseline.sql`은 원격 이력보다 먼저 존재했던 기본
테이블과, 원격 이력에 기록되지 않은 기존 `001`~`004`, `008`, `009`를 합친
schema-only 기준선이다. 실제 운영 행은 복사하지 않는다.

그 뒤 파일은 원격 `supabase_migrations.schema_migrations`의 24개 타임스탬프와
동일하게 맞췄다. 원격에는 이름이 같은 `005_special_events`가 두 번 기록되어 있어,
첫 번째 파일에 실제 SQL을 두고 두 번째 파일은 이력 정렬용 주석 파일로 유지한다.

| 레거시 파일 | canonical 파일 |
|---|---|
| `001`~`004`, `008`, `009` 및 이전 기본 스키마 | `20260501000000_legacy_schema_baseline.sql` |
| `005_special_events.sql` | `20260508013131_005_special_events.sql` |
| 원격 중복 `005_special_events` | `20260508020003_005_special_events.sql` |
| `006` | `20260511013544_seminar_voting_window.sql` |
| `007` | `20260511093654_topic_admission_year.sql` |
| `010`~`029` | 원격 이력의 동일 타임스탬프·이름 파일 |

## 로컬 설정

- CLI: npm 개발 의존성 `supabase@2.116.0`으로 고정
- Postgres major: 운영과 동일한 `15`
- `auto_expose_new_tables = false`
- seed: 개인정보가 없는 빈 `supabase/seed.sql`

Docker Desktop이 설치되어 있지 않은 환경에서는 로컬 스택을 실행할 수 없다.
Docker가 준비된 새 clone에서 다음 순서로 재현한다.

```powershell
npm ci --ignore-scripts --no-audit --no-fund
npx supabase start
npx supabase db reset --local
npx supabase migration list --local
```

## 원격 이력 정렬 게이트

공식 문서상 `supabase db pull`은 원격 `schema_migrations`에도 기준선 적용 이력을
기록한다. 이 저장소는 이미 원격 스키마를 카탈로그로 대조해 기준선을 만들었으므로,
운영 적용 전에는 다음을 별도 유지보수 작업으로 수행한다.

1. 운영 백업 상태와 DB 비밀번호/CLI 연결 대상을 확인한다.
2. `npx supabase migration list --linked`로 차이가 기준선 한 건뿐인지 확인한다.
3. `20260501000000`을 applied로 표시하는 `migration repair` 명령을 dry-run 관점에서
   재검토한다. 다른 버전은 건드리지 않는다.
4. 다시 migration list를 실행해 local/remote가 모두 정렬됐는지 확인한다.
5. `npx supabase db push --dry-run` 결과가 `No pending migrations`인지 확인한다.

이 단계는 애플리케이션 테이블이나 행을 바꾸지 않지만 원격 마이그레이션 이력 한
행을 변경한다. 실행 전 정확한 대상 프로젝트와 백업을 다시 확인해야 한다.

## 검증과 롤백

- 로컬: fresh reset 후 public 테이블, 함수, RLS, grants를 검사한다.
- 원격: 테이블 수·RLS·브라우저 DML 권한·함수 EXECUTE 권한을 변경 전후 비교한다.
- 기준선 커밋 롤백: `supabase/`와 CLI 의존성 커밋을 되돌린다. 운영 DB 영향은 없다.
- 원격 이력 정렬 롤백: 실제 스키마를 되돌리지 않고 잘못 표시된 기준선 버전만
  `migration repair --status reverted 20260501000000`으로 원복한다.

## 금지 사항

- 운영 프로젝트에 `db reset --linked` 실행
- 운영 데이터를 seed로 export하거나 Git에 커밋
- 기준선 정렬 전에 `db push`
- 중복 `005` 이력을 임의 삭제
- 레거시 `migrations/`를 검증 없이 삭제 또는 이름 변경
