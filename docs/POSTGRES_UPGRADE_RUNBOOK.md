# Supabase Postgres 업그레이드 실행 안내서

점검일: 2026-09-01

프로젝트: `Book group maker project` (`lzvfkbekhbcqfbknldmo`)

상태: **사전 점검 완료, 실제 업그레이드는 아직 실행하지 않음**

이 문서는 운영진이 Supabase 대시보드에서 업그레이드를 실행하기 전에 확인할
항목과, 실행 직후 반드시 검증할 기능을 정리한다. 업그레이드는 서비스 중단을
동반하므로 별도 승인과 점검 시간 확정 전에는 실행하지 않는다.

## 1. 현재 점검 결과

| 항목 | 결과 | 판단 |
|---|---:|---|
| Supabase 상태 | `ACTIVE_HEALTHY` | 정상 |
| 현재 Postgres | `15.8` (`15.8.1.100`) | 보안 패치 업그레이드 필요 |
| 데이터베이스 크기 | 약 17MB | 데이터 복사량은 작지만 대시보드 예상 시간이 우선 |
| 복제 슬롯 / 활성 슬롯 | 0 / 0 | 차단 요소 없음 |
| 스트리밍 복제 연결 | 0 | 읽기 복제 사용 징후 없음 |
| 5분 초과 트랜잭션 | 0 | 점검 시점 정상 |
| prepared transaction | 0 | 정상 |
| 잠금 대기 세션 | 0 | 정상 |
| 무효 인덱스 | 0 | 정상 |
| 사용자 정의 operator estimator | 0 | 해당 없음 |
| `ltree`, `btree_gist` | 비활성 | 관련 재색인 이슈 해당 없음 |
| `reg*` 형식 컬럼 | 2 | 모두 Supabase 관리 `realtime.subscription` 컬럼 |
| `pgjwt` | 활성 | Postgres 17 대상이면 사전 비활성화 검토 필요 |

`reg*` 컬럼은 `realtime.subscription.entity(regclass)`와
`realtime.subscription.claims_role(regrole)`이다. 앱이 만든 컬럼이 아니므로 직접
변경하거나 삭제하지 않는다. Supabase 대시보드의 업그레이드 적합성 검사에서
차단 여부를 확인하고, 차단되면 Supabase 지원 절차를 따른다.

`pgjwt`는 저장소 및 `public` 함수에서 명시적 사용 흔적이 발견되지 않았다. 다만
Postgres 17에서는 지원 중단 확장 기능이므로, 실제 목표 버전이 17로 표시될 때만
대시보드에서 비활성화하고 아래 기능 검증을 모두 수행한다. 목표 버전은 문서에
미리 고정하지 않고 실행 당일 대시보드가 제시하는 버전을 기록한다.

## 2. 실행 승인 전 필수 조건

다음 항목이 모두 확인되어야 실행할 수 있다.

- [ ] 사용자에게 목표 버전, 대시보드 예상 중단 시간, 실행 시각을 알리고 승인받음
- [ ] Supabase `Database > Backups`에서 최신 백업 시각과 복구 가능 상태를 확인함
- [ ] 무료/유료 플랜 및 백업 보존 조건을 확인함
- [ ] Render에서 직전 정상 커밋과 롤백 방법을 기록함
- [ ] 당일 운영진 한 명이 사이트 기능 검증을 담당함
- [ ] 세미나·모집 결과 발표·조 편성 시간과 겹치지 않는 점검 창을 잡음
- [ ] 장기 트랜잭션, 복제 슬롯, 잠금 대기 항목을 실행 직전에 다시 확인함
- [ ] 대시보드의 모든 upgrade blocker를 해소함
- [ ] Postgres 17 대상이면 `pgjwt` 비활성화 후 로그인·API smoke test를 먼저 통과함

백업 상태는 API 집계만으로 확정하지 않는다. 운영진이 대시보드에서 실제 최신
백업과 복원 옵션을 눈으로 확인해야 한다. Supabase 공식 문서상 Pro, Team,
Enterprise 프로젝트는 일일 자동 백업을 제공하지만 현재 프로젝트 플랜은 이
문서에서 추정하지 않는다.

## 3. 실행 직전 읽기 전용 점검

아래 SQL은 개인 행을 출력하지 않고 차단 요인의 개수만 확인한다.

```sql
select
  current_setting('server_version') as server_version,
  pg_size_pretty(pg_database_size(current_database())) as database_size,
  (select count(*) from pg_replication_slots) as replication_slots,
  (select count(*) from pg_stat_replication) as replica_connections,
  (select count(*) from pg_stat_activity
    where xact_start is not null
      and pid <> pg_backend_pid()
      and now() - xact_start > interval '5 minutes') as long_transactions,
  (select count(*) from pg_stat_activity
    where wait_event_type = 'Lock'
      and pid <> pg_backend_pid()) as lock_waiters,
  (select count(*) from pg_index where not indisvalid) as invalid_indexes;
```

하나라도 0이 아니면 즉시 실행하지 말고 원인을 먼저 확인한다. 복제 슬롯 삭제,
확장 기능 비활성화, 관리 스키마 변경은 이 문서만으로 자동 수행하지 않는다.

업그레이드는 Supabase 대시보드의 `Project Settings > Infrastructure` 또는 현재
표시되는 `Upgrade project` 화면에서 실행한다. 대시보드가 보여주는 예상 시간과
차단 경고를 캡처해 운영 기록에 남긴다. 업그레이드 중에는 DB와 연결 서비스가
오프라인이 될 수 있으므로 Render 설정이나 코드를 동시에 변경하지 않는다.

## 4. 업그레이드 후 검증 순서

먼저 Supabase 프로젝트가 `ACTIVE_HEALTHY`인지 확인하고, 다음 순서로 점검한다.

1. Security Advisor에서 `vulnerable_postgres_version` 경고가 사라졌는지 확인
2. 전체 public 테이블의 RLS 활성, `anon`/`authenticated` DML 0건 확인
3. 4개 공개 RPC가 `SECURITY INVOKER`, 빈 `search_path`, 브라우저 실행 불가인지 확인
4. 확장 기능 버전과 무효 인덱스 0건 확인
5. Render 로그에서 DB 연결·PostgREST 오류와 새 느린 쿼리가 없는지 확인
6. 아래 애플리케이션 smoke test 수행

### 필수 smoke test

- [ ] Kakao 로그인 후 회원 홈과 로그아웃
- [ ] 세미나 일정 및 진행 현황 조회
- [ ] 월요일 신청제 좌석 신청과 중복 방지
- [ ] 발제문 신규 작성, 기존 수정, 비회원 수정 코드 검증
- [ ] 조 편성 생성·수정·저장·캡처 재생성
- [ ] 회원 상태 변경 및 관리자 추가 권한 확인
- [ ] 모집 지원자 결과 조회와 반복 조회 제한
- [ ] 비공개 이미지 업로드 및 signed URL 조회
- [ ] Word/Excel 다운로드
- [ ] 세미나실 예약 캐시 조회

검증 중 쓰기 테스트는 실사용자 데이터를 수정하지 않도록 사전에 정한 테스트
계정과 테스트 회차만 사용하고, 완료 후 생성한 테스트 데이터만 정리한다.

## 5. 실패와 롤백

Supabase 공식 절차에서는 업그레이드 실패 시 기존 DB 인스턴스를 다시 올린다.
그렇더라도 앱 오류가 생기면 다음 순서로 대응한다.

1. 새 쓰기 작업을 중지하고 장애 시작 시각을 기록한다.
2. Supabase 프로젝트 상태와 업그레이드 로그를 확인한다.
3. DB는 임의로 downgrade하거나 스키마를 삭제하지 않는다.
4. 앱 호환 문제라면 Render를 직전 정상 커밋으로 롤백한다.
5. 데이터 복원이 필요하면 대시보드 백업 시각과 장애 이후 쓰기 손실 범위를 먼저
   확인하고 Supabase 지원 절차로 복구한다.
6. 복구 후 전체 행 수와 핵심 업무 집계를 업그레이드 전 기록과 비교한다.

복원은 장애 이후의 정상 쓰기를 되돌릴 수 있으므로 자동으로 실행하지 않는다.

## 6. 스테이징 선택지

가장 안전한 선택은 Supabase Branch에서 목표 버전과 앱 smoke test를 먼저 실행하는
것이다. Branch는 비용이 발생할 수 있고 운영 데이터가 복제되지 않으므로, 조직과
비용을 확인해 별도 승인을 받은 뒤 생성한다. 비용 승인이 없다면 Docker가 있는
개발 환경에서 canonical migration을 새 DB에 재현하고, 익명 테스트 데이터로 먼저
검증한다.

## 7. 공식 참고 자료

- [Supabase 프로젝트 업그레이드](https://supabase.com/docs/guides/platform/upgrading)
- [Supabase 데이터베이스 백업](https://supabase.com/docs/guides/platform/backups)
- [Postgres 15 릴리스 노트](https://www.postgresql.org/docs/15/release.html)
