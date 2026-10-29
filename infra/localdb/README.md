# 로컬 DB 이전 준비 — 운영 전환 미승인

2026-10-29 기준. 실제 운영은 Supabase를 계속 사용한다. 사용자 승인 후 Ubuntu에 최소 구성을 설치하고 합성 데이터 시험을 완료했다. 실제 회원 데이터 암호화 백업·개인 Drive 재다운로드·새 DB 두 곳 복원을 완료했고, 운영 전환은 아직 하지 않았다. [실제 결과](RESTORE_VALIDATION.md)를 확인한다. [시험 결과와 재개 위치](trial/VALIDATION.md), [실제 백업·복원 실행안](REAL_DATA_REHEARSAL.md)을 먼저 읽는다.

## 현재 확인한 범위

- 운영 PostgreSQL 15.8, 초기 조사 DB 약19.4MB, 운영 기능 SQL 이후 public 테이블72개. 실제 이전 직전 수량·크기는 다시 수집한다.
- Supabase Auth 사용자 0명. 로그인은 Flask·카카오이며 자체 회원/역할 테이블을 쓴다.
- Storage 버킷 4개: board-uploads(private), book-covers(public), engagement-photos(private), engagement-images(private). 조사 시점에는 객체 0개였지만 전환 직전에 다시 확인한다.
- 사용 확장: plpgsql, pg_stat_statements, pgcrypto, pgjwt, supabase_vault, uuid-ossp. 설치 목록과 실제 앱 의존성은 구분해 복구 단계에서 확인한다.
- VM: 기존 동적 메모리 최대3GB 유지. 시험 중 약2.93GiB로 늘었으며 별도 Docker PostgreSQL은 합성 시험 후 중지했다. 디스크 여유는 이미지/볼륨 추가 후 전환 전에 재조회한다.
- 위키 SQLite는 이미 로컬이다. DB 전환 시 위키 DB, 게시판 파일, 앱 비밀 설정까지 복원 범위에 포함한다.

## 적용할 설계

PC 주소를 코드에 넣지 않고 API 주소·비밀키·백업 경로를 서버 설정으로 유지한다. 앱 API와 파일 저장소는 같은 VM 내부에서만 접근하고, Worker/Tunnel의 회원용 주소는 유지한다. 새 PC로 옮길 때는 데이터·설정 복구와 Tunnel 연결만 교체할 수 있어야 한다. 지금 인수인계 묶음이나 공용 계정 연결은 만들지 않는다.

`SUPABASE_URL`을 PostgreSQL 주소로 바꾸는 것만으로 이전할 수 없다. 앱은 PostgREST RPC 및 Storage의 업로드·서명 URL API를 사용한다. 우선 API 호환성을 유지하는 self-host 구성으로 복구 시험을 하되, 현재 VM 메모리에 전체 Supabase 스택을 바로 올리지 않는다. 사용할 공식 배포 버전을 고정하고 불필요한 Studio/Analytics 등 관리 서비스를 줄인 후보의 메모리·기동을 검증해야 한다. 구성 축소가 해당 버전에서 지원되지 않으면 VM 자원 조정 또는 경량 DB 접근 계층을 별도로 선택한다.

개발용 `supabase start`를 운영 서버로 사용하지 않는다. 운영 설치 전에 최소 구성·필요 메모리·백업 대상·복원 시험 결과를 구체화해 승인받는다. DB만 먼저 옮기고 Storage를 원격에 남기는 방식은 최종 목표가 아니다.

## 백업과 복구 순서

1. PostgreSQL 연결 정보를 비밀 파일로 받고, PC 밖 백업 목적지 및 age 공개 암호화 키를 지정한다. 비밀번호·개인키는 채팅이나 저장소에 넣지 않는다. 목적지는 개인 Google Drive로 정했고 연결된 계정을 확인했다. DB 비밀번호는 Windows DPAPI로 보관하여 TLS 읽기 전용 접속을 검증했다. 실제 암호문 업로드·재다운로드와 두 번의 격리 복원을 완료했다.
2. 기존 `infra/minipc/backup.py`로 public·supabase_migrations custom dump와 Storage 객체/메타데이터를 수집해 age 암호화 후 승인된 외부 저장소에 복사한다. 기존 자동 백업은 아직 설치되지 않았다. DB/Storage 동시 일관성을 위해 최종 백업에서는 앱과 알림 타이머의 쓰기를 멈춘다.
3. 암호문을 다시 내려받아 검증하고, 개인 임시 폴더에 복호화한 TAR를 아래 도구로 점검한다. 검사 로그에는 회원명·객체 경로를 출력하지 않는다.

   ```sh
   python3 infra/localdb/verify_archive.py /private/restore-test/backup.tar
   ```

4. 운영과 다른 빈 복구 DB/내부 API 주소에서 먼저 복구한다. 공식 self-host 버전과 PostgreSQL major 호환성을 맞추고 필요한 역할/확장을 먼저 준비한다. pg_restore 목록을 확인한 뒤 public 및 migration 기록을 복구한다. Supabase의 내부 auth/storage 스키마를 무작정 덮어쓰지 않는다. auth.users=0을 다시 확인하고 달라졌다면 Auth 이전 범위를 다시 검토한다.
5. 파일은 같은 공개/비공개 설정의 버킷을 생성한 뒤 Storage API 또는 S3 경유로 업로드한다. 로컬 volume에 파일만 복사하면 Storage 메타데이터가 없어 정상 동작하지 않는다. URL에 기존 프로젝트가 저장된 데이터와 `engagement.py`의 커버 URL 생성도 점검한다.
6. 이전 전후 테이블별 행 수, PK/FK, identity sequence, 함수 권한/RLS, 버킷별 객체 수·크기·해시를 비교한다. 가상 계정의 로그인 세션·출석 확정/되돌림·신청 처리·알림 작업·게시판 이미지 업로드/서명 URL 만료를 별도 복구 DB에서 확인한다. 기존 운영 데이터를 바꾸는 테스트는 하지 않는다.
7. 외부 백업으로 다시 빈 DB에 복구하여 동일 검사를 통과해야 전환 후보로 간주한다. TAR 해시 검증만으로 복원 성공이라고 기록하지 않는다.

## 실제 전환 직전 승인 범위

설치/서버 자원 변경 승인 → 복구 시험 → 결과 제출 → 최종 쓰기 중지·백업·증분 동기화·환경 설정 변경·앱 재시작을 별도로 승인받는다. 전환 후에는 두 DB에 동시에 쓰지 않는다. 운영 회원 트래픽은 한쪽만 사용한다.

새 DB가 회원 쓰기를 받기 전 내부 검증에서 실패하면 기존 환경 설정으로 복귀한다. 공개 트래픽을 연 뒤에는 신규 기록 보존을 우선해 로컬을 수정한다. 역동기화 도구는 아직 없으므로 자동으로 Supabase에 되돌리지 않는다. 복귀가 꼭 필요하면 다시 쓰기를 멈추고 양쪽 데이터를 비교·이관하는 별도 복구 계획을 승인받는다. Supabase 삭제/해지는 별도 승인까지 보류한다.

## Claude 검토와 다음 실험 (2026-10-29)

실제 Claude Opus 5.5 high 검토: 전체 스택보다 PostgreSQL + PostgREST + 파일 계층을 권장. 현재 문서는 실제 복원 전 계획이며 전환 준비 완료가 아니다. 운영 DB 15.8에서 API를 직접 SQL로 모두 재작성하는 방식은 약 560곳의 회귀 위험 때문에 제외한다.

공식 self-hosted/v0.8.3 구성 확인: PostgreSQL 17.6.1.136, PostgREST v14.18, Storage API v1.81.0, Envoy v1.39.1. 전체 구성의 공식 최소치는 RAM 4GB/디스크 40GB여서 현재 VM 최대 3GB/30GB에 그대로 설치하지 않는다. Windows 전체 여유 메모리도 조사 시 약 3.25GB였다. 이 버전들은 호환성 시험 후보이며 검증된 운영 조합이라고 주장하지 않는다.

1. 운영 연결·회원 데이터·운영 비밀 없이, loopback 전용 포트와 별도 볼륨에서 PG/PostgREST/Storage 최소 조합을 시험한다. Auth/Studio/Realtime/Edge Functions/Analytics/Supavisor는 앱 사용 여부를 확인한 뒤 제외하며, 기본 compose의 gateway 의존성도 함께 수정한다. Docker·VM 자원 변경은 호스트 변경 승인 후에만 실행한다.
2. 우선 기존 Storage API를 유지해 업로드·서명·삭제 호환성을 검증한다. 자원 초과 또는 불필요한 의존성이 확인되면 앱 내부 파일 어댑터로 변경하는 대안을 비교한다. 처음부터 검증되지 않은 두 방식을 함께 구현하지 않는다.
3. 빈 DB에 server-only 역할과 필요한 스키마/확장을 준비하고 전체 migration을 적용한다. 합성 데이터로 앱의 실제 PostgREST CRUD/upsert/RPC, anon 차단, 파일 업로드/서명 URL 만료/삭제를 확인한다. 기존 운영 PG15 → 후보 PG17 복원은 별도로 dump/restore 검증한다. PGlite 단위 검증으로 이 단계 성공을 대체하지 않는다.
4. 서비스별 정상/업로드/알림 작업 중 메모리와 API 지연을 측정한다. 기존 앱·위키를 포함해 충분한 여유가 없으면 중단한다. 결과로 VM 최소/고정 메모리를 결정하며, 현재 메모리로 운영 가능하다고 미리 결론내리지 않는다.

### 전환 전에 해결할 코드 항목

- `SUPABASE_URL` 내부 API 주소와 브라우저 이미지 주소를 분리한다. `boards.py`의 signed URL과 `engagement.py`의 커버 URL은 내부 127.0.0.1을 브라우저에 보내면 깨진다. 고정 내부 Storage upstream만 접근하는 같은 사이트의 미디어 GET 경로를 마련하고, 공개 커버와 토큰이 필요한 비공개 객체를 구분한다. 임의 URL 프록시나 REST/관리 API의 인터넷 공개는 금지한다.
- `backup.py`의 고정 PG17 container loopback 모드와 format 2(위키 snapshot/첨부/app.env/위키 키)를 준비하고 합성 Linux 검증을 마쳤다. 같은 사이트 이미지 경로 역시 준비·검증했고 미배포다. 실제 암호화·외부 업로드·회원 데이터 복원은 완료했다. 자동 외부 백업과 최종 쓰기 동결 사본을 준비한 뒤에만 전환한다.
- PC 밖 백업을 다시 내려받아 복호화하고, 새 빈 DB에 두 번째 복원을 수행한다. 개인키는 저장소·채팅에 두지 않는다. 같은 PC 디스크만의 백업은 외부 백업으로 간주하지 않는다.
- 권장 운영값: 매일 백업 + 전환 직전 백업, 일간 14개/주간 8개 보존, 실패 시 전체 관리자 알림. 개인 Drive 목적지는 확정됐고 복구 키는 1Password + Windows DPAPI 보관을 준비한다. 쓰기 중단은 실제 복원 소요를 잰 뒤 구체적 시간을 제안한다.

**최소 구성의 합성 시험 설치는 승인받아 완료했다.** 개인 Google Drive 업로드·재다운로드와 두 번의 복원 시험까지 승인받아 완료했다. 복구 키는 사용자가 1Password 보관을 확인했다. 자동 외부 백업, 최종 전환과 Windows 부팅 검증은 별도로 구체화해 승인받는다.

## 자동 백업·부팅 순서 구현 준비 (2026-10-29)

[자동 백업 적용안](../minipc/AUTOMATIC_BACKUP.md)과 [운영 runtime](runtime/README.md)을 준비했다. 새 코드의 Linux 검사10개 및 기존 백업 관련11개, Compose/systemd 설정 검사를 통과했다. DB 복원 시험은 반복하지 않았다. Google 전용 앱·장기 연결, rclone 설치·타이머·관리자 알림은 직전 승인 요청 후 대기 중이다. 운영 DB·앱 연결 및 Windows 재부팅은 아직 실행하지 않았다.

## 아직 완료되지 않은 항목

- 외부 자동 백업 OAuth/스케줄러/보존·실패 알림 구성
- 운영 연결용 서비스 의존 순서·자원 예산 확정 (실제 복원과 관측 메모리는 확인)
- 최종 전환 직전 쓰기 동결 후 새 백업·복원 (첫 실제 복원 시험은 완료)
- 앱 연결 전환 및 동작 검증
- Windows 전체 재부팅 → VM/DB/API/앱/알림/Tunnel 자동 복구 실증

## 확인한 공식 자료

- [Self-hosting 운영 책임](https://supabase.com/docs/guides/self-hosting)
- [Docker 구성과 최소 자원](https://supabase.com/docs/guides/self-hosting/docker)
- [확인한 공식 compose v0.8.3](https://github.com/supabase/supabase/blob/self-hosted/v0.8.3/docker/docker-compose.yml)
- [Platform에서 self-host로 복구](https://supabase.com/docs/guides/self-hosting/restore-from-platform)
- [Storage S3 경유 복사](https://supabase.com/docs/guides/self-hosting/copy-from-platform-s3)
