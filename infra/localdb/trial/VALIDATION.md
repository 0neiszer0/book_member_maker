# 실제 합성 시험 결과 — 2026-10-29

사용자가 시험 환경 설치·실행을 승인했다. 운영 전환·Drive 업로드·재부팅은 승인 범위에서 제외했다.

## 완료

- Ubuntu 공식 Docker 29.1.3, Compose 2.40.3과 의존 패키지 총6개 설치. 기존 패키지 업그레이드/삭제 없음, Windows/VM 재부팅 없음. 운영 앱·위키·Tunnel은 계속 정상.
- PostgreSQL17.6.1.136 / PostgREST14.18 / Storage1.81.0 / Envoy1.39.1 기동. 내려받아 검증한 image digest를 compose에 고정했다.
- 최초 시작에서 root umask 때문에 공개 bind 설정이600으로 만들어져 초기화가 중단됐다. `prepare.py`가 공개 설정3개는644, 비밀env는600으로 만들도록 수정했다. 불완전하게 초기화된 기존 볼륨은 중지·보존하고 **새 v2 볼륨**에서 공식 초기화를 끝까지 수행했다. 임의로 역할 권한을 확대해 우회하지 않았다.
- 전체 migration 재생 중 초기 baseline의 `topic_events.book_author text nullable` 누락 발견. 운영 정보 스키마 읽기 조회로 기존 열을 확인하고 schema-only baseline에 보완했다. 운영 DB에는 추가 변경하지 않았다.
- 새 빈 DB에 저장소 migration **33개 전체 적용 성공**. 축약 PGlite 스키마만의 검증과 구분한다.
- 운영과 같은 Python SDK로 실제 HTTP CRUD/upsert, anon 테이블/RPC 거절, 학기 권한/명단 RPC, 실제 출석 확정과 stale-write 거절, 업무 중복 방지와 공동 완료 확인.
- 비공개 PNG 업로드/다운로드/서명 URL 만료/anon 접근 차단 확인. 공개 책 표지는 실제 정책인 WebP로 업로드/다운로드/삭제 확인. PNG/JPEG 입력을 거절하는 버킷 정책은 유지했다.
- 시험 컨테이너4개 전체 stop/start 후 DB와 비공개 파일 보존 확인. Windows 전체 부팅 시험은 아직 하지 않았다.
- 시험 종료 후 컨테이너는 **중지**, 볼륨과 설정은 보존. Docker 데몬은 설치된 상태이며 시험 컨테이너의 restart policy는 no다. 운영 앱은 계속9459cfc, Supabase 연결도 그대로다.

## 관측값과 한계

- 재기동 후 Docker 표시 메모리: DB59.29MiB, REST9.551MiB, Storage84.66MiB, proxy14.27MiB, 합계 약168MiB. 실제 운영 부하나 복원 피크 메모리 측정은 아니다.
- VM이 기존 Hyper-V 동적 메모리 범위에서 약2.93GiB까지 늘었고 측정 시 available 약2GiB. Hyper-V 설정은 변경하지 않았다.
- 합성 회원4행을 읽는 내부 쿼리8회: 중앙값5.465ms, 최대66.37ms. 실제 사이트 페이지 속도와 동일한 지표가 아니다.
- 실제 회원 데이터는 사용하지 않았고 테스트 푸시는 발송하지 않았다. 실제 운영 데이터 복원이나 외부 백업은 미완료다.

## 재개 위치

- VM root 전용 설정: `/var/lib/bookmembers-db-trial`, compose project `bookmembers-db-trial-v2`.
- 초기 중단된 project `bookmembers-db-trial`의 볼륨도 보존. 삭제하지 않았다.
- 시험 전용 JWT는 생성 후24시간 만료. 운영 키로 대체하지 않는다.
- VM 로그/결과: `migration-progress.json`, `synthetic-verification.json`, `trial-results.json`, `image-digests.jsonl`.
- Windows 결과: 작업 루트 `outputs/localdb-trial-results-20261029.json`.
- 실행한 검증 스크립트: 작업 루트 `work/operations-review/trial-*.py`. 비밀 파일은 결과 JSON이나 Git에 포함하지 않았다.

## 다음 단계

1. 실제 PostgreSQL 접속 비밀과 개인 Google Drive 연결, 복구키 보관 방법 확정.
2. 외부 암호화 백업 실제1회 + 다시 다운로드하여 빈 DB에2회 복원 검증.
3. 브라우저용 파일 URL/미디어 경로와 로컬 기준 통합 백업(위키·첨부·설정 포함) 보완.
4. 실제 복원 성능/자원 측정 후 최종 쓰기 중지·동기화·앱 연결 변경과 Windows 부팅 복구를 별도 승인받는다.
