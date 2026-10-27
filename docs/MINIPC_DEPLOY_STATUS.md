# 미니 PC 이전 진행 상태

갱신: 2026-10-27 KST. 재부팅/세션 중단 후 이 파일부터 읽는다.
작업 사본: C:/Users/HOME/Documents/Codex/2026-10-27/markdown-0neiszer0-book-member-maker-pc/work/book_member_maker
브랜치: codex/minipc-security. 기준 main: 91b7dd6d9d0c6771a1e07c1ea977396f72dae4ce.
원격 push/운영 배포/DB 쓰기 없음. main은 Render 자동 배포이므로 승인 전 push 금지.
다른 UI 세션: zip-canvas-lms-00-start-here. 그 폴더는 수정하지 않음.
통합 시 app.py, engagement.py, _header.html 및 관련 폼 변경을 반드시 대조한다.

| 단계 | 상태 | 결과/정확한 재개 조건 |
|---|---|---|
| 저장소·Windows 점검 | 완료 | 최신 main 독립 clone. Win11 Pro build 26300, Ryzen 5500U, 가상화/SLAT 활성, 가용 RAM 약 4.7GiB, C 여유 약 373GiB. Windows Tailscale 1.104.1 온라인/자동, RDP 실행. 절전·최대절전 시간 AC/DC 모두 0 |
| 보안 코드 3건 | 로컬 완료 | 수동 연결 신청/트랜잭션 승인, 관리자 보호 RPC, 카카오 세션 기반 회원 명의 작성. 대상 POST CSRF. 신규 표식 없는 기존 로그인은 작성 시 1회 재로그인 |
| 보안 테스트 | 완료 | 기존 전체 Python 301개: 첫 실행 3개 실패(새 CSRF와 migration 목록 기대 변경). 해당 fixture 수정 후 관련 36개 통과. 신규 보안 10개 통과. Worker Node 2개 통과. 전체 스위트 반복 안 함 |
| SQL 준비 | 로컬 완료 | 20261027122104_minipc_account_security.sql: 승인 RPC/관리자 변경 RPC/비어있지 않은 social_id unique index. 중복 있으면 값 노출·자동 정리 없이 중단. PGlite 격리 PostgreSQL 합성 데이터 검증 통과. 운영 미적용 |
| Worker 코드 | 로컬 완료 | 스트리밍 프록시, 위조 전달 헤더 제거, 별도 원본 비밀, 원본 redirect 재작성. Wrangler 4.153.0 dry-run 성공. 공개 배포 없음 |
| Cloudflare 계정 | 진행 | 사용자 가입·이메일 인증 수행. Wrangler account:read/user:read/workers_scripts:write 및 Windows 키링 저장 승인 받음. 첫 OAuth 시간 만료, 재시도 중. 실제 성공은 CLI 결과로 재확인 |
| Worker 주소 | 보류 | 아직 미발급. 공개 배포/원본 비밀 업로드 승인 필요 |
| Render 원본 | 읽기 확인 완료 | https://book-member-maker.onrender.com/keep-alive : status=ok, supabase=alive. 실제 배포 SHA 및 외부 예약 잡은 대시보드 미확인 |
| Worker→Render/OAuth | 보류 | Worker 발급, SQL 승인·적용, 보안 코드 Render 배포 승인, PUBLIC_BASE_URL/허용 Origin 및 Kakao 콜백 승인 필요 |
| Hyper-V | 기능 활성화 완료 | 사용자가 기능 활성화만 명시 승인. 관리자 스크립트 성공: Success=true, State=Enabled, RestartNeeded=true. 재부팅 안 함. 결과 ../hyperv-enable-result.json |
| Ubuntu VM/서비스 | 보류 | 호스트 재부팅 및 VM 생성 각각 승인 필요. VM 아직 없음. 2CPU/동적 RAM 1/1.5/3GiB/30GiB Gen2 스크립트 준비 |
| Funnel/원본 보호 | 코드 준비/공개 보류 | REQUIRE_ORIGIN_AUTH=true, 키 없으면 시작 실패, 키 누락/오류 모든 경로 403. Gunicorn loopback. VM 별도 Tailscale 노드 가입과 공개 승인 필요 |
| Worker→Funnel 전환 | 보류 | 양쪽 원본 동일 보안 커밋/Origin/OAuth 호환, DB 백업·Storage 보존·실제 smoke 후 승인 필요 |
| 재부팅/장애 복구 | 보류 | Windows 로그인 전 VM 자동 시작→systemd→Funnel→Worker 실제 접속 검증 필요. BIOS 정전 후 켜짐은 미확인 |
| Render 구주소 | 보류 | 기존 서비스 유지. 중지/삭제 승인 없음. 구주소 영구 보존 불가 |

## 재현 명령

- `.venv/Scripts/python.exe -m unittest testing.test_minipc_security -v`
- `node --test testing/test_worker_proxy.mjs`
- `npm ci --prefix infra/minipc`, `node infra/minipc/verify-sql.mjs` (합성 데이터만 사용)
- `infra/worker`에서 `npm ci`, `npx wrangler deploy --dry-run --outdir ../../../worker-build`
- 실제 설치·전환 순서는 `infra/minipc/README.md`.

Python 3.12.16 및 venv를 작업 폴더 안에 격리 설치. 기존 Python 3.13 설정 유지.
Wrangler Windows 키링 의존성 @napi-rs/keyring@1.3.0 설치. 키/토큰은 기록하지 않는다.
Supabase CLI가 홈 설정 폴더 생성 권한 오류로 migration new 실행 실패하여 timestamp 파일을 로컬로 작성했다.
전체 db push/reset은 실행하지 않았다. SQL은 운영 PostgreSQL 15/다중 연결에서 아직 미검증이다.
원격 DB 스키마·백업·Storage 보존은 아직 확인 전이며 테스트 통과가 운영 적용 승인을 의미하지 않는다.

## 승인 기록

- Hyper-V 기능 활성화만 승인: 완료. 재부팅/VM 생성 미승인.
- Wrangler 제한된 OAuth 권한 및 Windows 키링 저장 승인: 인증 완료 확인 대기.
- Worker/Funnel 공개, 운영 SQL/Render 배포, Kakao 설정, 운영 전환, Render 중지: 모두 미승인.

자동 승인 검토가 최초 Wrangler 권한 요청을 명시적 승인 부재로 차단했으며,
이후 사용자에게 해당 권한/키링 저장 승인을 받아 동일 인증을 재시도했다.
