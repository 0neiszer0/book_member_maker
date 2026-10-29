# 로컬 DB 이전 준비 — 운영 전환 미승인

2026-10-29 기준. 실제 운영은 Supabase를 계속 사용한다. 이 폴더의 검사는 로컬 파일만 읽으며 설치·DB 복구·업로드·전환을 실행하지 않는다.

## 현재 확인한 범위

- PostgreSQL 15.8, DB 약 19.4 MB, public 테이블 67개. 이번 기능 SQL 적용 후 수량은 다시 수집해야 한다.
- Supabase Auth 사용자 0명. 로그인은 Flask·카카오이며 자체 회원/역할 테이블을 쓴다.
- Storage 버킷 4개: board-uploads(private), book-covers(public), engagement-photos(private), engagement-images(private). 조사 시점에는 객체 0개였지만 전환 직전에 다시 확인한다.
- 사용 확장: plpgsql, pg_stat_statements, pgcrypto, pgjwt, supabase_vault, uuid-ossp. 설치 목록과 실제 앱 의존성은 구분해 복구 단계에서 확인한다.
- VM: 현재 동적 할당 메모리 약 946 MiB, 기존 최대 설정 3 GB, 디스크 여유 약 22 GB. PostgreSQL은 아직 설치하지 않았다.
- 위키 SQLite는 이미 로컬이다. DB 전환 시 위키 DB, 게시판 파일, 앱 비밀 설정까지 복원 범위에 포함한다.

## 적용할 설계

PC 주소를 코드에 넣지 않고 API 주소·비밀키·백업 경로를 서버 설정으로 유지한다. 앱 API와 파일 저장소는 같은 VM 내부에서만 접근하고, Worker/Tunnel의 회원용 주소는 유지한다. 새 PC로 옮길 때는 데이터·설정 복구와 Tunnel 연결만 교체할 수 있어야 한다. 지금 인수인계 묶음이나 공용 계정 연결은 만들지 않는다.

`SUPABASE_URL`을 PostgreSQL 주소로 바꾸는 것만으로 이전할 수 없다. 앱은 PostgREST RPC 및 Storage의 업로드·서명 URL API를 사용한다. 우선 API 호환성을 유지하는 self-host 구성으로 복구 시험을 하되, 현재 VM 메모리에 전체 Supabase 스택을 바로 올리지 않는다. 사용할 공식 배포 버전을 고정하고 불필요한 Studio/Analytics 등 관리 서비스를 줄인 후보의 메모리·기동을 검증해야 한다. 구성 축소가 해당 버전에서 지원되지 않으면 VM 자원 조정 또는 경량 DB 접근 계층을 별도로 선택한다.

개발용 `supabase start`를 운영 서버로 사용하지 않는다. 운영 설치 전에 최소 구성·필요 메모리·백업 대상·복원 시험 결과를 구체화해 승인받는다. DB만 먼저 옮기고 Storage를 원격에 남기는 방식은 최종 목표가 아니다.

## 백업과 복구 순서

1. PostgreSQL 연결 정보를 비밀 파일로 받고, PC 밖 백업 목적지 및 age 공개 암호화 키를 지정한다. 비밀번호·개인키는 채팅이나 저장소에 넣지 않는다. 목적지는 아직 미지정이다.
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

새 DB가 쓰기를 받기 전 실패하면 기존 환경 설정으로 즉시 복귀할 수 있다. 쓰기를 받은 뒤 단순히 예전 Supabase로 바꾸면 신규 기록이 사라질 수 있으므로, 다시 쓰기를 멈추고 역동기화·검증 후 복귀한다. Supabase 삭제/해지는 사용자가 별도로 승인할 때까지 보류한다.

## 아직 완료되지 않은 항목

- PostgreSQL 비밀 연결 정보와 PC 밖 암호화 백업 목적지 확정
- 운영용 self-host 구성 버전 고정, VM 자원 검증 및 설치 승인
- 실제 데이터 전체 백업, 저장소 객체 복사, 빈 DB 복구 시험
- 앱 연결 전환 및 동작 검증
- Windows 전체 재부팅 → VM/DB/API/앱/알림/Tunnel 자동 복구 실증

## 확인한 공식 자료

- [Self-hosting 운영 책임](https://supabase.com/docs/guides/self-hosting)
- [Platform에서 self-host로 복구](https://supabase.com/docs/guides/self-hosting/restore-from-platform)
- [Storage S3 경유 복사](https://supabase.com/docs/guides/self-hosting/copy-from-platform-s3)
