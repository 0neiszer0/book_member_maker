# 미니 PC 이전 진행 상태

갱신: 2026-10-27 KST. 재부팅/세션 중단 후 이 파일부터 읽는다.
작업 사본: C:/Users/HOME/Documents/Codex/2026-10-27/markdown-0neiszer0-book-member-maker-pc/work/book_member_maker
브랜치: codex/minipc-security. 기준 main: 91b7dd6d9d0c6771a1e07c1ea977396f72dae4ce.
보안 코드 커밋: c44220d, 085141b. 원격 push 및 Render 코드 배포 없음.
다른 UI 세션의 별도 사본(zip-canvas-lms-00-start-here)은 수정하지 않았다.
통합 시 app.py, engagement.py, _header.html 및 관련 폼 변경을 대조한다.

## 완료한 작업

- Windows 11 Pro build 26300 / Ryzen 5500U / 가상화·SLAT 확인. 가용 RAM 약 4.7GiB, C 여유 약 373GiB(점검 당시). 기존 Windows Tailscale 1.104.1 온라인·자동 시작, RDP 실행. AC/DC 절전·최대절전 timeout 0.
- 독립 브랜치에 계정 연결 신청·승인 RPC, 관리자 보호, 카카오 인증 회원 명의 쓰기, 민감 POST CSRF, Worker 원본 인증·Origin 검증 구현. 기존 세션은 회원 명의 작성 시 1회 재로그인 필요.
- Python 기존 전체 301개 최초 실행 중 3개 기대값 실패. CSRF/마이그레이션 fixture 수정 후 관련 36개 통과. 신규 보안 10개, Worker Node 2개 통과. PGlite 합성 데이터 SQL 검증 통과. Wrangler dry-run 통과. 전체 스위트 재실행은 하지 않음.
- Supabase 프로젝트 lzvfkbekhbcqfbknldmo: 실제 스키마 일치, 중복 social_id 그룹 0, pending 0, 활성 관리자 2, Storage objects 0 확인. 개인정보 행 내보내기 없음.
- 무료 플랜 자동 백업 없음 확인. 사용자가 '백업 없음 인지, 해당 SQL만 승인'하여 이번 확장 SQL에 한해 지침의 백업 조건 예외 승인.
- 운영에 20261027122104_minipc_account_security.sql 적용. RPC account_request_mutate / protected_member_mutate 및 members_social_id_unique_nonempty 인덱스만 생성. 기존 회원 행 수정 호출 없음. 트랜잭션에 lock_timeout 5s, statement_timeout 30s 적용.
- 적용 후 카탈로그 확인: 두 함수 SECURITY INVOKER / 빈 search_path / anon·authenticated 실행 불가 / service_role 실행 가능. 인덱스 unique·valid·ready 모두 true. 운영 계정 변경 테스트 없음. execute_sql 직접 적용이므로 migration history 등록 없음. 전체 db push/reset 금지.
- Cloudflare 제한 OAuth(account:read,user:read,workers_scripts:write) 인증 성공, Windows 키링 보호 저장. 사용자 승인 후 Worker 생성·Secret 저장·공개 GET 검증 완료.
- Worker 주소: https://book-member-maker.alstj816.workers.dev . 원본은 https://book-member-maker.onrender.com . GET 200, keep-alive status=ok/supabase=alive, no-store, 응답에 원본 비밀 없음.
- 원본 비밀은 작업 폴더 work/origin-auth-secret.dpapi에 Windows DPAPI 암호화 저장. 절대 출력/커밋하지 말 것. 향후 VM에 같은 값을 안전하게 전달. Flask/Supabase 기존 키 재사용 안 함.
- Render My Workspace 읽기 승인 후 확인: srv-d06thnjuibrs73eu1r4g, free/docker/singapore, main 자동 배포 활성. 현재 live SHA는 기준 main 91b7dd6. healthCheckPath 비어 있음. 설정 변경 없음.
- Hyper-V 기능 활성화만 승인받아 완료: work/hyperv-enable-result.json의 Success=true/State=Enabled/RestartNeeded=true. 재부팅 아직 안 함.
- Ubuntu 24.04.5 Server ISO 다운로드 완료: work/ubuntu/ubuntu-24.04.5-live-server-amd64.iso. 공식 SHA256 일치(97f3d7ffb032c3eb3b23d2c8be9cc76e60c2c1f2c0146ba5ba9fe01cafae0fd8).
- VM 생성·systemd·Funnel·검증 실행 스크립트 및 runbook 준비. Python 3.12.16/venv는 작업 폴더에 격리 설치.

## 다음 순서 / 미완료

1. 사용자 재부팅 승인 후 Windows 재시작. 다른 세션 작업 저장 확인. 강제 종료 금지. 재접속 후 Hyper-V 실제 상태 확인.
2. 별도 VM 생성·Ubuntu 설치 승인 후 New-BookVm.ps1 실행. bookmembers-ubuntu, Gen2, 2CPU, 동적 RAM 1/1.5/3GiB, 30GiB, Default Switch, 자동 시작/정상 종료. VM 아직 없음.
3. 다른 UI 변경과 충돌 검토 후 보안 코드 운영 배포 승인. main push는 Render 자동 배포를 일으키므로 승인 전 금지. 현재 공개 Worker도 아직 구형 Render 코드를 사용하므로 보안 전환 완료 상태가 아님.
4. PUBLIC_BASE_URL/허용 Origin 및 Kakao 콜백 설정 변경 각각 승인 후 적용. Worker 주소를 회원 안내 URL로 아직 전환하지 않음.
5. Ubuntu 서비스 설치·비밀 환경 설정·별도 Tailscale 노드 인증. Funnel 공개 및 필요 정책 변경은 별도 승인. 원본 인증 필수, 직접 Funnel 접근은 403이어야 함.
6. 동일 보안 버전 양쪽 원본 검증 후 Worker→Funnel 전환 승인. 외부 예약 잡·알림 중복 여부 확인 필요.
7. 재부팅/로그인 전 자동 복구와 실제 사이트 접근 검증. BIOS 정전 후 자동 켜짐 미확인. Tailscale 노드 인증 만료 정책 확인 필요.
8. Render 중지/삭제 승인 없음. 복구용으로 유지. 취약한 기준 main으로 롤백하지 않음.

## 승인 경계와 검증 한계

승인 완료: Hyper-V 기능만, Wrangler 권한·키링, Worker 생성·Secret·공개 GET, My Workspace 읽기, 백업 없이 해당 확장 SQL만.
미승인: 호스트 재부팅, VM 생성·설치, Render 운영 코드·환경 변경, Kakao 설정, Funnel 공개, Worker 원본 전환, Render 중지.
SQL 합성 검증은 PGlite이며 실제 다중 연결 동시성 시험은 하지 않았다. 운영에서는 정의·권한·인덱스 읽기 검증만 했다.
Supabase CLI migration new는 홈 설정 폴더 권한 오류로 실패하여 로컬 timestamp 파일을 작성했다.
최초 Wrangler 권한 요청은 자동 승인 검토가 차단했으나 이후 명시적 사용자 승인으로 해소됐다.

## 재현 명령

- .venv/Scripts/python.exe -m unittest testing.test_minipc_security -v
- node --test testing/test_worker_proxy.mjs
- node infra/minipc/verify-sql.mjs (합성 데이터 전용)
- infra/worker에서 npx wrangler deploy --dry-run

운영 실행 순서는 infra/minipc/README.md. outputs의 상태 문서·runbook·소스 ZIP·패치는 재개용 배포 사본이다.

## 사용자 결정 갱신 (2026-10-27 KST)

- Hyper-V 적용을 위한 재부팅 질문에 사용자가 '재부팅은 나중에'로 답함.
- 재부팅 예약/실행하지 않음. 재부팅은 이후 사용자의 명시적 승인 또는 직접 실행 후 재개한다.
- 따라서 VM 생성·Ubuntu 설치·Funnel 및 부팅 자동 복구 검증은 대기 상태다.
