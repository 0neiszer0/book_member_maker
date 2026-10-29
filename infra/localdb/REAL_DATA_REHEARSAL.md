# 실제 데이터 백업·격리 복원 실행안

2026-10-29. **사용자 승인 후 실행 완료.** [실제 결과](RESTORE_VALIDATION.md)를 먼저 읽는다. 아래는 승인 당시 실행안이다. 운영 앱은 Supabase를 계속 사용한다.

## 확인된 상태

- Windows에 사용자 DB 비밀번호를 DPAPI로 보관했고, 공식 Supabase CA + `verify-full`로 명시적 읽기 전용 접속을 확인했다. VM에는 DB 비밀번호를 아직 저장하지 않았다.
- 운영 PostgreSQL 15.8, public 테이블 72개, DB 약 19.8MB. Auth 사용자·Vault 비밀·Storage 객체/소유자 메타데이터·large object·외부 스키마 FK·Realtime publication 테이블은 모두 0개. cron 스키마 없음. 백업 직전 다시 조회하며, 지원 범위 밖 데이터가 생기면 중단한다.
- Google Drive 연결 도구에서 승인된 개인 계정을 확인했다. 폴더 생성·파일 업로드·공유 설정 변경은 하지 않았다.
- 소스 준비: 같은 사이트의 이미지 GET 경로, backup format 2(위키 SQLite snapshot/첨부/앱·위키 설정), 고정 PG17 클라이언트, 원본 프로젝트 일치 검사, 범위 검사, 프록시 환경 무시, 복구 파일 해시 검사.
- Python 검증 23개 통과. 실제 Linux 합성 시험에서 공개/서명 이미지 2건, PG custom dump 목록, SQLite snapshot, 복구 파일 4개 무결성 통과. 이것은 실제 회원 데이터 복원 성공을 뜻하지 않는다.
- 합성 컨테이너는 모두 중지했고 볼륨은 보존했다. 운영 앱·위키·Tunnel 정상. 이번 코드는 미배포다.

## 이번 승인으로 실행할 범위

1. Ubuntu에 `age=1.1.1-1ubuntu0.24.04.3` 한 패키지 설치(모의 확인: 추가1, 업그레이드0, 제거0). 기존 PG17 Docker 이미지를 클라이언트로 재사용한다. rclone/호스트 PostgreSQL/자동 백업 타이머는 아직 설치하지 않는다.
2. Windows 작업 폴더에 공식 age v1.3.2 portable 도구를 준비한다. ZIP SHA256 `f48d8f8f9ebe903ab5027ed067652f2cc1db94bc206976430133b905dcd8e8c7`과 대조한다. 시스템 PATH 변경 없음. 새 X25519 복구 키를 만들고 개인키는 Windows DPAPI와 사용자 1Password에 보관한다. 개인키·비밀번호를 채팅/로그/저장소에 출력하지 않는다. VM에는 공개 수신자 키만 둔다. 가상 데이터로 Windows↔Ubuntu 암호화 왕복을 먼저 확인한다.
3. `/etc/book_member_maker/backup.env`, `backup.pgpass`, 공식 CA 및 root 전용 백업 폴더를 구성한다. 비밀번호는 암호화 보관본에서 메모리/SSH 입력으로만 전달하고 root:root 0600으로 저장한다. 백업 소스는 승인된 commit의 별도 staging 경로에서 실행하여 운영 앱 checkout은 바꾸지 않는다.
4. 운영 DB를 읽기 전용으로 덤프하고 Storage 버킷·파일, 위키 SQLite의 일관된 snapshot·첨부, app.env/위키 bridge.env/engine.env를 age 암호화한다. 이 자료에는 회원 정보와 서비스 비밀 설정이 들어 있으므로 암호문만 PC 밖으로 보낸다. 일반 운영 쓰기는 중단하지 않으며, 이 첫 사본은 서비스 전체의 동시 시점 복구 지점으로 주장하지 않는다.
5. 연결된 개인 Drive에 비공개 `책반우 서버 백업` 폴더를 만들어 암호문을 올린다. 공유 범위를 바꾸지 않는다. 다시 내려받은 암호문의 SHA256을 Windows에 기록한 기준값과 비교한다. `--export-only`의 EXPORT.json은 외부 검증 완료가 아니므로, 다운로드 비교 증거를 별도로 남긴다.
6. 새 볼륨을 쓰는 격리 복구 환경 두 개에 순서대로 복원한다. 한 번에 한 환경만 실행하고 합계 메모리 상한 1,248MiB, API는 VM loopback 55481/55482만 사용한다. 실제 회원 복사본임을 명시하고 기존 SYNTHETIC-ONLY 볼륨/표식은 재사용하지 않는다. Docker internal 네트워크로 외부 발송을 막고 알림/Telegram/메일/공개 Tunnel/스케줄러는 실행하지 않는다.
7. 첫 복원과 Drive에서 다시 받은 사본의 두 번째 복원을 각각 검증한다. 앱·위키의 운영 DB 연결은 바꾸지 않는다. 검사 후 복구 컨테이너를 중지하고 root 전용 볼륨/암호문과 재개 기록을 보존한다. 운영 자원 여유가 줄거나 응답 악화가 확인되면 시험을 중단한다.

## 복원 시 반드시 확인할 것

- 호스트 PG16 클라이언트를 설치하지 않는다. 고정 PG17 이미지 digest는 `trial/compose.yaml`에 있다. 원본 확장 6개와 PG17 가용 확장/실제 의존성을 비교한다. 없어도 되는 설치 기록과 필요한 함수 의존성을 구분하며, 필요한 확장을 조용히 생략하지 않는다.
- Storage가 관리하는 기본 스키마와 역할을 먼저 준비하고 **public은 비운 새 DB**에 dump만 복원한다. 앱 migration 33개를 중복 적용하지 않는다. `pg_restore --exit-on-error --single-transaction`을 사용한다. `--no-owner` 사용 여부는 소유자 목록을 확인한 후 결정하고 ACL은 생략하지 않는다. 기존 public 스키마 항목 충돌은 TOC에서 그 항목만 제외하여 처리한다.
- 테이블별 행 수, 시퀀스, PK/FK, RLS, 함수/테이블 권한 및 익명 접근 차단을 비교한다. 원본이 쓰기 중인 첫 시험에서는 동시 변경 가능성을 기록한다. 최종 전환은 쓰기 동결 후 기준값과 완전히 일치해야 한다.
- Storage 내부 DDL을 통째로 덮어쓰지 않는다. 버킷의 공개 여부·MIME·용량 제한을 복원하고 API로 파일을 올린 뒤 재다운로드 해시를 비교한다. 현재 0개라도 절차를 생략하지 않는다. DB 컬럼의 이전 hosted Storage URL 잔존 여부를 확인한다.
- 위키는 SQLite `integrity_check`, 문서/이력 수, 첨부 해시를 비교한다. 복구 설정 파일은 root 전용, 위키 파일은 해당 서비스 계정 권한으로 복구한다. 운영 비밀 설정으로 시험 앱·알림을 그대로 시작하지 않는다.
- 개인키를 1Password에서 복구할 수 있어야 한다. 같은 PC의 DPAPI만으로 외부 복구 가능하다고 판단하지 않는다. 평문 임시 파일은 root 전용 디렉터리에서 다루고 정상/실패 시 정리한다. 정전으로 남은 staging은 다음 백업이 잠금 획득 후 검사·정리한다. 현재 VM 디스크 암호화는 검증하지 않았으므로 at-rest 전체 암호화를 보장하지 않는다.

## 이후 별도 승인할 작업

- 자동 Drive 백업: rclone 공유 Google client ID는 2026년 종료 예정이므로 사용자 소유 OAuth client + `drive.file`로 설계한다. 해당 client가 만든 전용 폴더를 사용한다. 이번 연결 도구가 만든 폴더에 다른 client의 `drive.file` 권한이 자동으로 생기지 않는다. OAuth Testing 7일 만료 조건/Production 설정을 공식 문서로 확인한 후 계정 연결과 타이머를 승인받는다.
- 최종 전환: 실제 복원 시간·자원 여유·외부 복구 검증 결과를 제출하고, 앱/위키/타이머 쓰기 중지 → 최종 백업 → 최종 복원 → 로컬 DB 연결 → 앱 재시작을 승인받는다. 새 기록을 받은 뒤에는 Supabase로 자동 되돌리지 않는다.
- Windows 재부팅 및 전체 부팅 자동 복구 시험. Supabase 삭제/해지, Render/GitHub main/도메인/카카오 설정 변경은 포함하지 않는다.

공식 자료: [age v1.3.2](https://github.com/FiloSottile/age/releases/tag/v1.3.2), [rclone Drive](https://rclone.org/drive/), [Supabase 복구](https://supabase.com/docs/guides/self-hosting/restore-from-platform).
