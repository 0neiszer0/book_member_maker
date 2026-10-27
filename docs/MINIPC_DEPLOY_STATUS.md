# 미니 PC 이전 진행 상태

갱신: 2026-10-28 KST. 재부팅/세션 중단 후 이 파일부터 읽는다.
최신 재개: 사용자가 직접 재부팅한 뒤 계속 진행 요청. 아래 과거 '재부팅 보류' 기록은 이 항목으로 대체한다.
Windows 부팅 시각 2026-10-27 23:05:09 KST. Hyper-V Enabled, HypervisorPresent=true,
vmms Running/Automatic, 기존 VM 0개, Default Switch 확인. 결과: work/hyperv-postboot.json.
원격 main 재조회 bda8a82 유지. 사용자 VM 생성·Ubuntu 설치·SSH 키 등록 승인 후 VM 생성 완료.
Ubuntu 24.04.5·SSH·앱 실행 환경·보호된 비밀 설정·로컬 앱 가동 완료. Tailscale 패키지 설치 완료,
BackendState=NeedsLogin. 노드 가입/Funnel 공개/Worker 원본 전환/호스트 자동 복구 검증은 미완료.
작업 사본: C:/Users/HOME/Documents/Codex/2026-10-27/markdown-0neiszer0-book-member-maker-pc/work/book_member_maker
브랜치: codex/minipc-security. 기준 main: 91b7dd6d9d0c6771a1e07c1ea977396f72dae4ce.
현재 GitHub main 및 Render live: bda8a82e66ac828dd3bfe1971c37e7e98cca356f. 사용자 승인 후 보안 배포 완료. 이후 백업 준비 변경은 로컬에만 있다.
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
- Render My Workspace 읽기 승인 후 확인: srv-d06thnjuibrs73eu1r4g, free/docker/singapore, main 자동 배포 활성. 현재 live SHA는 bda8a82. healthCheckPath 비어 있음. Render 환경변수 변경 없음.
- Hyper-V 기능 활성화만 승인받아 완료: work/hyperv-enable-result.json의 Success=true/State=Enabled/RestartNeeded=true. 재부팅 아직 안 함.
- Ubuntu 24.04.5 Server ISO 다운로드 완료: work/ubuntu/ubuntu-24.04.5-live-server-amd64.iso. 공식 SHA256 일치(97f3d7ffb032c3eb3b23d2c8be9cc76e60c2c1f2c0146ba5ba9fe01cafae0fd8).
- VM 생성·systemd·Funnel·검증 실행 스크립트 및 runbook 준비. Python 3.12.16/venv는 작업 폴더에 격리 설치.

## 다음 순서 / 미완료

1. 완료: 사용자 직접 Windows 재부팅 후 Hyper-V 실제 상태 확인. 서비스 자동 복구 검증용 재부팅은 별도 후속 단계.
2. 완료: VM 생성·Ubuntu 설치·관리 SSH 키 등록, ISO 분리·디스크 부팅·SSH 검증.
   아래 최신 VM 기록부터 재개한다. 다음은 앱 실행 환경 및 Tailscale 패키지 설치.
3. 보안 코드 bda8a82는 Render 운영 배포 완료. 다른 UI 작업은 포함하지 않음. UI 통합 시 최신 main을 기준으로 보안 코드와 CSRF를 보존한다. 추가 main push는 새 배포를 일으키므로 승인 필요.
4. Kakao Worker 콜백 추가 완료. Render의 PUBLIC_BASE_URL/허용 Origin/프록시 콜백/원본 비밀 변경은 필요성 질문 후 보류. 현재 Worker 로그인 시작은 Render 콜백을 사용하므로 Worker OAuth 완료로 표시하지 않는다. VM에서 직접 검증하고 최종 전환 때 복구용 Render 유지 여부를 결정한다.
5. Ubuntu 서비스 설치·비밀 환경 설정·별도 Tailscale 노드 인증. Funnel 공개 및 필요 정책 변경은 별도 승인. 원본 인증 필수, 직접 Funnel 접근은 403이어야 함.
6. 동일 보안 버전 양쪽 원본 검증 후 Worker→Funnel 전환 승인. 외부 예약 잡·알림 중복 여부 확인 필요.
7. 재부팅/로그인 전 자동 복구와 실제 사이트 접근 검증. BIOS 정전 후 자동 켜짐 미확인. Tailscale 노드 인증 만료 정책 확인 필요.
8. Render 중지/삭제 승인 없음. 복구용으로 유지. 취약한 기준 main으로 롤백하지 않음.

## 승인 경계와 검증 한계

승인 완료: Hyper-V 기능만, Wrangler 권한·키링, Worker 생성·Secret·공개 GET, My Workspace 읽기, 백업 없이 해당 확장 SQL만.
미승인/보류: 추가 호스트 재부팅, Render 추가 코드·환경 변경, 추가 Kakao 설정, Funnel 공개, Worker 원본 전환, Render 중지. VM 생성·Ubuntu 설치·관리 SSH 키 등록은 승인됨. bda8a82 보안 코드 배포와 Worker 콜백 1개 추가는 승인받아 완료.
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

## 향후 이전성을 위한 설계 요구사항 (2026-10-27 사용자 의도 확인)

사용자 의도: 지금 인수인계 구성·배포 묶음·공용 계정 전환을 만들라는 요청이 아니다. 이후 서버 구축 과정에서 다음 원칙을 반영한다. 이번 대화에서는 새 배포 묶음 생성, 계정 초대·이전, 백업 업로드·예약 활성화를 하지 않는다.

- 특정 Windows PC·사용자 경로·개인 계정을 앱 실행의 필수 조건으로 만들지 않는다. Linux 서비스 설치와 설정을 재현할 수 있게 유지한다.
- 회원 공개 URL과 서버 위치를 분리한다. 다른 PC로 이동할 때 새 원본을 검증한 후 Worker의 UPSTREAM_ORIGIN을 바꾸는 구조를 유지한다.
- 서버 교체 시 기존 Supabase 프로젝트와 카카오 앱을 유지하여 DB·회원 식별자·로그인 설정의 불필요한 변경을 피한다. DB 로컬 이전은 현재 실행 범위에 추가하지 않는다.
- 비밀은 코드와 분리한다. 현재 Windows DPAPI 보관본은 임시 로컬 보관 수단이며 다른 PC에서 그대로 복호화할 수 있는 인수인계 백업으로 취급하지 않는다. 실제 이전 시 안전한 별도 전달/교체 절차를 준비한다.
- DB와 Storage의 외부 암호화 백업·복원 검증은 후속 구축 작업에 포함한다. 저장소·복구키 보관 방식 확정 및 실제 연결/활성화 승인은 나중에 받는다. 자동 백업이 이미 동작한다고 표시하지 않는다.
- 향후 운영자 변경은 서비스가 지원하는 조직·멤버 권한을 활용한다. 동아리 공용 Gmail은 그때 선택 가능한 관리 연락처이며, 지금 주소 수집·가입·초대는 하지 않는다.
- Cloudflare 기존 계정/Worker 유지 시 공개 주소 보존을 우선한다. Gmail 기반 Tailscale tailnet의 소유자 변경 제한을 고려하여 필요하면 새 운영자의 tailnet에 새 서버를 등록하고 Worker 원본만 전환한다. 기존 개인 Windows Tailscale 설정은 유지한다.
- 재부팅은 계속 보류. UI 작업 사본은 계속 분리한다.

공식 근거 확인: https://developers.cloudflare.com/fundamentals/manage-members/manage/ , https://tailscale.com/docs/features/sharing/how-to/change-role , https://supabase.com/docs/guides/platform/access-control , https://developers.kakao.com/docs/ko/app-setting/app . 실제 이전 시 당시 정책을 다시 확인한다.

## 재부팅 보류 중 추가 작업 (2026-10-27 KST)

- 원격 main fetch 성공: 91b7dd6 유지. Render live도 같은 SHA. 다른 UI 세션은 codex/lms-v3-navigation 별도 사본에서 계속 작업 중이며 app.py/_header.html 등이 겹친다. 그 사본은 수정·병합하지 않았다.
- Render My Workspace 서비스 목록: book_member_maker와 chatbot_bookclub 웹 서비스 2개. Cron/Background Worker 없음. Supabase pg_cron 미설치, Storage 객체 0개. 타사 예약 호출은 미확인.
- Worker/Render 쿠키 분리를 고려해 선택형 KAKAO_PROXY_REDIRECT_URI 구현. 올바른 원본 인증 헤더가 있는 요청에만 Worker 콜백을 사용하고, 직접 Render 요청은 기존 콜백 유지. 설정하지 않으면 기존 동작 유지. 목적지·공개 주소·원본 비밀 검증 포함.
- OAuth 예외 세부내용을 로그에 남기지 않도록 변경. 관련 보안/로그인 테스트 30개 통과(합성 데이터, 실제 OAuth 호출 없음). 전체 스위트 반복 안 함.
- Kakao 콘솔 로그인 요청 중. 아직 콜백 설정을 읽거나 변경하지 못함.
- 다음 승인 대상: 보안 코드 main fast-forward push로 Render 자동 배포. 이번 단계에서는 환경변수/Kakao/회원 안내 주소를 바꾸지 않음. 이후 Worker 콜백과 과도기 환경 설정은 별도 승인.
- 새 배포 ZIP/패치/인수인계 묶음은 만들지 않는다. 기존 outputs의 ZIP/패치는 이번 수정 전 상태이며 최신 실행 소스는 작업 사본에 있다.


## 실행 결과 갱신 (2026-10-27 KST 22시 이후)

- 사용자 승인: 보안 코드 main 반영·Render 배포. Git Credential Manager 로그인은 사용자 직접 수행.
- main에 bda8a82e66ac828dd3bfe1971c37e7e98cca356f fast-forward push 완료(강제 push 아님).
- Render 배포 dep-dbgaaiqjnfac739rtol0 live 확인. Render·Worker 공개 홈 200,
  /keep-alive status=ok/supabase=alive, 로그인 시작 302 확인. 운영 POST/회원 변경 테스트 없음.
- GitHub Actions tests run 40511290940 completed/success 확인(배포 커밋 자동 CI).
  https://github.com/0neiszer0/book_member_maker/actions/runs/40511290940
- 카카오 운영 앱 독서동아리 ID 1288463 / REST 플랫폼 키 설정 4468347을 현행 로그인 client_id와
  원문 출력 없는 SHA256 비교로 확인. 사용자가 새 Worker 콜백 한 개 추가 승인.
  기존 4개 URI를 유지하고 https://book-member-maker.alstj816.workers.dev/login/kakao/callback 추가,
  저장 후 설정 재조회로 총 5개 확인. 앱 키/시크릿/동의항목 변경 안 함.
- 주의: 카카오 콘솔은 플랫폼 키 편집 화면에서 시크릿을 함께 표시하므로 이후 전체 화면 텍스트를
  출력하지 말고 필요한 URI/필드만 선택 조회한다. 비밀을 저장소/상태 문서에 복사하지 않는다.
- Render 환경변수 변경 승인은 받지 않았다. 사용자가 필요성을 질문하여 목적을 설명하고 보류함.
  PUBLIC_BASE_URL/ADDITIONAL_ALLOWED_ORIGINS/KAKAO_PROXY_REDIRECT_URI/ORIGIN_AUTH_SECRET/
  REQUIRE_ORIGIN_AUTH는 아직 운영 Render에 추가·변경하지 않음. 두 공개 주소 모두 로그인 시작의
  redirect_uri가 기존 Render 콜백임을 확인. Worker의 로그인 전환·실계정 smoke는 미완료.
- Render 환경변수는 이름만 확인했고 기존 값은 내보내지 않았다. VM 예시에 사용 중인 Telegram
  설정 이름을 추가했다. 기타 레거시 환경변수는 현재 앱 사용 여부를 구분하여 이전할 것.
- 백업 실행 준비본을 로컬 추가: infra/minipc/backup.py, backup.env.example,
  bookmembers-backup.service/.timer. public+supabase_migrations custom dump, Storage 데이터/설정,
  참고용 Storage DDL을 age 암호화 후 rclone 외부 업로드/다운로드 비교하는 흐름.
  평문 임시파일은 접근 제한하고 완료 마커는 검증 성공 후 업로드. 삭제/보존 자동화는 없음.
- 합성 백업 테스트 3개 통과(페이지네이션·중첩/빈 버킷·파일 내용·실패 처리·오류값 미노출).
  최초 Windows 샌드박스 임시폴더 권한 오류 후 작업 폴더 전용 임시 경로에서 검증.
- 실제 DB 백업/외부 업로드/복구키 생성/예약 설치는 아직 하지 않음. DB 연결 자격증명,
  외부 저장소와 복구키 보관, 보존 정책·실패 알림, 첫 실행 승인과 격리 복원이 선행 조건.
  Ubuntu pg_dump/age/rclone 설치와 실제 왕복 검증은 재부팅·VM 준비 이후 진행.
- 재부팅 및 VM/Funnel 구축은 계속 대기. 새 ZIP/패치/인수인계 묶음은 생성하지 않았다.

## 재부팅 후 준비 (2026-10-27 KST)

- 관리자 읽기 점검에서 Hyper-V 정상, 기존 VM 없음, Default Switch 확인. 가용 RAM 약 4.5GiB,
  C 여유 약 366GiB. 기존 Windows Tailscale/RDP/네트워크 설정 변경 없음.
- 검증된 ISO 내부 casper/install-sources.yaml에서도 ubuntu-server-minimal ID 확인.
- autoinstall.yaml.example 준비: 최소 설치, bookadmin SSH 공개키 인증, 암호 로그인 잠금,
  관리키 보유자에게 sudo 권한, Asia/Seoul, 보안 업데이트, Hyper-V 게스트 통합 도구.
  새 VM의 /dev/sda 가상 디스크만 설치 대상으로 사용. 설치 완료 시 VM만 poweroff.
- New-BookVm.ps1에 선택적 CIDATA ISO 부착 지원 추가. PowerShell 구문 및 YAML 파싱 확인.
- 승인 제안: C:/Users/HOME/Documents/Codex/servers/bookmembers-ubuntu에 Gen2 VM,
  2 vCPU, 30GiB 동적 디스크. 설치 중 최대 3GiB RAM 사용 후 기존 계획 1/1.5/3GiB 적용.
  부팅 자동 시작 30초/호스트 종료 시 정상 종료. SSH 개인키는 Git 밖 접근 제한 로컬 파일.
- 실제 VM 생성·시작·설치·SSH 키 등록은 아직 하지 않음. 별도 승인 후 진행.

### VM 생성 승인 후 실행

- 사용자: 'VM 생성·Ubuntu 설치·관리 SSH 키 등록 승인'.
- VM 생성·시작 완료: bookmembers-ubuntu, UUID b2d974cc-c827-42ac-a974-5d54c17a6864,
  디스크 C:/Users/HOME/Documents/Codex/servers/bookmembers-ubuntu/system.vhdx.
- 2 vCPU, 30GiB VHDX, 설치 중 3GiB startup, 설치 후 1.5GiB로 복귀 예정.
- SSH 키는 work/vm-access에 현재 Windows 사용자·SYSTEM·Administrators만 접근 가능하도록
  NTFS ACL 제한. 개인키 원문 출력 없음. 공개키만 CIDATA 설치 ISO에 포함.
- Ubuntu 최소 설치 설정을 실제 설치 프로그램에서 읽고 검증한 상태. 설치 확인 대기/진행은
  VM 연결 창으로 확인. 설치 완료 전에는 Complete-UbuntuInstall.ps1을 실행하지 않는다.
- 정상 설치 종료 후 VM Off 확인 → 설치 DVD 분리 → 시스템 디스크 부팅 → SSH 검증 예정.
- Computer Use에서 관리자 VMConnect의 입력은 SendInput Access Denied로 차단됨.
  Hyper-V TypeText('yes')는 반환값 0이었지만 화면상 문자가 전달되지 않고 같은 확인을 반복함.
  따라서 설치가 시작됐다고 간주하지 않음. 개별 TypeKey로 재시도하려던 두 번째 관리자
  UAC가 Windows에서 '사용자가 작업을 취소했습니다'로 반환되어 실행하지 못함.
- 사용자에게 VM 연결 창의 'Continue with autoinstall? (yes|no)'에 직접 yes/Enter 입력을 요청함.
  이 입력 완료 후 화면을 새로 확인한다. 취소된 UAC 요청을 무단 재시도하지 않는다.
- work/Confirm-ApprovedUbuntuInstall.ps1은 개별 키 코드로 수정돼 있으나 해당 버전은 미실행.
  사용자가 관리자 요청 재시도를 요청하면 새 화면을 확인한 뒤에만 실행한다.
- 현재 운영 사이트/DB/Worker 원본에는 이번 재개 작업으로 변경 없음.
- 사용자 직접 yes/Enter 입력 완료 후 설치 종료 감시용 UAC도 사용자 확인 완료.
  work/Monitor-ApprovedVmInstall.ps1 실행 중(당시 PID 2024). 이 작업은 최대 30분간 새 VM의
  설치 종료를 기다린 뒤 승인 범위 내에서 DVD 분리/시스템 디스크 우선/시작 RAM 1536MiB/부팅을
  수행하고 최대 5분간 게스트 IP를 읽는다. 예약 작업·상시 관리자 서비스는 만들지 않음.
  진행은 work/vm-install-progress.json, 후처리 결과는 work/vm-install-finalize.json.
  Stage=InstalledDiskStarted여도 SSH로 OS·설치 로그·키 인증을 확인해야 설치 완료 판정 가능.
- 화면 제어는 관리자 입력 Access Denied, 이후 화면 캡처가 검은 화면을 반환하여 신뢰할 수 없음.
  VM 상태 및 후속 SSH 검증을 우선한다. 게스트 설치 중 강제 종료/호스트 재부팅 금지.
- VM 전용 install-tailscale.sh 준비 및 bash 구문 검사 완료. 공식 noble 서명 저장소 사용,
  패키지 설치와 tailscaled 자동 시작만 수행하며 노드 가입/Funnel 공개는 포함하지 않는다.
  아직 실행하지 않음. 공식 문서: https://pkgs.tailscale.com/stable/#ubuntu-noble .

### Ubuntu 설치 완료 및 SSH 검증 (2026-10-27 23:40 KST 이후)

- 설치 로그 subiquity/Install/install SUCCESS, state DONE 및 error null 확인.
- 최초 후처리는 디스크 정확 경로 검사에서 중단됨. 실제 원인은 Windows Hyper-V의 첫 시작
  자동 검사점: system_15F28D67-2C34-4F27-86E0-0BA3489E943A.avhdx → system.vhdx.
  두 경로 모두 승인된 VM 디렉터리 내부이고 동일 원본 디스크임을 Get-VHD로 확인 후 진행.
  이후 자동 검사점은 껐고, 기존 자동 검사점 2e82f3ee-1f05-4ea6-843a-39d5804f956b는 보존됨.
  새 VM 스크립트도 자동 검사점 비활성화를 기본 적용. AVHDX를 직접 삭제/이동하지 말 것.
- DVD 0개, 시스템 디스크 우선, 시작 RAM 1536MiB(최소1GiB/최대3GiB), 디스크 부팅 성공.
- Hyper-V 확인 게스트 IPv4: 172.25.178.73 (Default Switch DHCP, 재부팅 후 바뀔 수 있음).
- bookadmin SSH 키 인증·sudo 동작, Ubuntu 24.04.5 LTS, ssh active, 실패한 systemd unit 없음.
  루트 디스크 29GiB 중 4.4GiB 사용/23GiB 여유, 게스트 RAM 약340MiB 사용(초기 확인값).
- 작업별 SSH 설정: work/vm-access/ssh-config, 별칭 bookmembers-vm.
  최초 호스트 키를 별도 known_hosts에 고정함. 개인키/호스트 설정은 Git 밖 ACL 제한 폴더.
  명령 예: ssh.exe -F ./work/vm-access/ssh-config bookmembers-vm <읽기 명령>.
- cloud-init은 installer의 marker에 의해 disabled, errors/recoverable_errors 없음.
  OS 설치 실패가 아니며 설치 결과는 SSH·설치 성공 로그로 별도 확인함.
- 후처리 감시 프로세스 정상 완료. 추가 호스트 재부팅 없음.
- SSH 설정 추가 확인: passwordauthentication no, pubkeyauthentication yes,
  permitrootlogin without-password. ssh 서비스는 socket activation 사용(ssh active이나 서비스
  enable 상태 자체는 disabled); ssh.socket enable 여부는 다음 런타임 설치 검증에서 확인.
  Asia/Seoul, NTP synchronized, Ubuntu 커널 6.8.0-147-generic.

### 앱 실행 환경 설치 승인 후 진행

- 사용자 승인: VM 앱·Tailscale 설치 및 기존 비밀 설정 이전·로컬 가동.
  기존 Render Flask/Supabase/Kakao/Telegram 설정과 Worker 원본 비밀을 VM root 전용
  app.env에 전달하는 범위. Tailscale 가입/Funnel 공개/Worker 전환/Render 변경은 제외.
- work/bootstrap-guest.sh를 관리 SSH로 실행 중. 공식 GitHub 저장소에서 정확한 bda8a82를
  detached checkout하고 Python3.12/venv/고정 requirements/systemd 및 Tailscale 패키지 설치.
  앱 환경 파일이 없으면 서비스는 시작하지 않음. 로그: work/vm-runtime-install.log.
- Render 연결 도구는 기존 환경값 읽기 기능이 없어 브라우저로 승인된 값만 읽어 이전할 예정.
  재부팅 후 Chrome 연결이 없고 native launch가 GetCursorPos access denied이므로 사용자에게
  기존 로그인 Chrome의 Render env 화면 열기를 요청함. 비밀값을 채팅에 요청하지 않음.

### VM 로컬 앱 가동 완료

- Render 환경 화면에서 승인된 7개 설정만 읽음: FLASK_SECRET_KEY, SUPABASE_URL,
  SUPABASE_SERVICE_KEY, KAKAO_OAUTH_CLIENT_ID/SECRET, TELEGRAM_BOT_TOKEN/CHAT_IDS.
  나머지 비사용 레거시 비밀번호는 이전하지 않음. Render 값/배포 자체는 변경하지 않음.
- 브라우저 도구 자식 SSH는 읽기 전용 hostname도 exit255/출력없음으로 실패. 실제 값 문제는
  아님을 확인. Windows DPAPI 임시 암호문으로 승인된 shell 실행 경로에 전달해 SSH 성공.
  Windows 평문 임시파일 없음, 브라우저 화면 다시 숨김, 메모리 참조 정리, 임시 DPAPI 삭제.
  Worker 원본 비밀 DPAPI 원본은 계속 work/origin-auth-secret.dpapi에 보존.
- VM /etc/book_member_maker/app.env root:root 0600, 부모 0700. 기존 Flask 키 보존.
  PUBLIC_BASE_URL=Worker, KAKAO_REDIRECT_URI=Worker 콜백, REQUIRE_ORIGIN_AUTH=true,
  SESSION_COOKIE_SECURE=true. 이전 설정값 원문은 출력/커밋하지 않음.
- VM 소스 bda8a82 detached, Python 3.12.3(Ubuntu 배포판 보안 패치), 의존성 pip check 통과.
  새 Linux 환경에서 합성 보안 테스트 13개 통과. 전체 테스트 반복 없음.
- bookmembers.service enabled/active/running, bookapp 사용자, 127.0.0.1:5000만 수신,
  NRestarts=0, 서비스 메모리 약105MiB(첫 확인). ssh.socket enabled.
- Tailscale 1.104.2 공식 패키지 설치, tailscaled enabled/active, NeedsLogin. 아직 tailnet 가입 안 함.
- 실제 GET 검증: 원본 헤더 없음/오류 403, 올바른 헤더 홈200·status=ok/supabase=alive,
  카카오 로그인 시작302·Worker 콜백·state, Secure/HttpOnly/SameSite=Lax 세션 쿠키 모두 통과.
  work/vm-local-verification.json에 boolean만 기록. 실계정 OAuth 완료/운영 POST는 수행하지 않음.
- 공개 Worker는 계속 Render를 가리킴. VM 원본은 아직 인터넷에 공개하지 않음.
- 기존 Windows Tailscale 읽기: Running, MagicDNS enabled, tail97bc40.ts.net.
- tailscale up 시작 요청은 자동 승인 검토가 차단함: 기존 승인은 패키지 설치까지이며
  노드 가입은 제외됐으므로 지속적 네트워크 접근 추가의 명시 승인 필요. 실제 명령 미실행.
  사용자에게 bookmembers-ubuntu를 기존 tail97bc40.ts.net에 별도 노드로 가입하는 승인을 요청 중.
  가입 승인 후에도 Funnel 공개/Worker 전환은 별도 승인 유지.
