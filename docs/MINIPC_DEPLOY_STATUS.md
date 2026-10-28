# 미니 PC 이전 진행 상태

**다음 작업: 사이트 문구·위키 안내·탭 로고 로컬 검증 완료, 운영 미반영.**
`docs/SITE_COPY_REVIEW_20261028.md`와 작업 루트 `outputs/site-copy-review-state.json` 참조.
2026-10-29 사용자 승인 후 Claude Opus 5.5 High 검토 완료. 후속 문구 보완과 기능 후보는 `docs/CLAUDE_SITE_REVIEW_20261029.md` 참조. 운영 배포 승인은 아직 대기 중이다.


**최신 완료: 2026-10-28 위키 운영 배포.** https://knu-read.xyz/wiki/ 에서 사용할 수 있다.
운영 앱 `62249f6b6af997eeb4d95318df0c35cc5154c004` clean, Worker `762caede-8d06-4a67-82e1-3eac6cee04af`.
위키는 앞서 배포한 학기 UI·공지 구분·KNU 이미지 변경을 포함한다. 아래의 더 오래된 앱 버전은 과거 기록이다.
사용자 승인 후 공식 openNamu 고정 버전·loopback 서비스·SQLite(문서14/이력19)·서버 키·앱·CDN 적용 완료.
앱/위키 자동 시작 및 하루1회 위키 로컬 백업(최근7회) 활성화. 첫 백업 무결성/키 일치 검증 완료.
공개GET12개, 실제 로그인된 브라우저의 읽기/편집 화면/미리보기/이력 확인, 콘솔 오류·경고0.
본문·이력은 seed/운영/백업에서 동일. Render/main/Supabase 스키마/카카오 설정 변경 없음.
다시 초기 설치하지 않는다. 상세 `docs/WIKI_DEPLOY_REVIEW_20261028.md`, 작업루트 `outputs/wiki-integration-state.json`.
위키 외 회원·출석 등의 업무 DB는 여전히 Supabase다. PC 밖 암호화 백업과 전체 호스트 재부팅 복구 실증은 미완료다.

---

공유 미리보기 완료(2026-10-28 17:35 KST): 사용자 승인 후 **책반우 사이트** 한 줄 이미지를
CDN·미니 PC 운영에 배포하고 앱만 재시작했다. 현재 앱7c92f9b·clean,
Worker 6eccf7cc-feb0-42f1-9f25-96889aadf622, 자산 해시69f0d779…0153a99.
공개 검사25/25 통과(이미지·3페이지 OG·DB health·카카오 로그인 시작), 앱/Tunnel active/enabled.
카카오 공식 도구에서 홈페이지 캐시 1건 초기화 후 새 URL/실제 문구 이미지 재수집·표시 확인.
이 작업은 완료됐으므로 승인이나 배포를 반복하지 않는다. 복구 기준은 앱8e290f7/Worker a9a69259.
상세 docs/MINIPC_OG_PREVIEW.md 및 작업 폴더 work/og-release/. Render/main/DB 변경 없음.
이전 아이콘 시안8f4310a와 그 승인 질문은 더 이상 적용 대상이 아니다.
속도 현황: 정적 CDN/캐시 및 일반 Cloudflare Tunnel 전환은 운영 반영 완료.
추가 DB 중복 조회 제거는 진단만 완료했으며 코드 구현/배포하지 않았다.

추가 진단(2026-10-28 17:02 KST): 공개 비로그인 홈 158~410ms, VM 내부 3~4ms.
운영 DB는 서울 리전이며 최소 읽기 HTTP 왕복 42/94ms(첫 새 연결418ms).
같은 앱 코드/합성 데이터에서 회원 홈15회·관리자13회·강의실17회 DB 호출을 확인했다.
전체 회원 출석 보고서 생성 및 학기/회차 중복 조회를 먼저 줄이는 개선안 기록.
이번에는 분석/기록만 했으며 추가 코드·배포·운영 DB 변경 없음. 상세 docs/MINIPC_PERFORMANCE.md.

도메인 전환 기록(2026-10-28 16:46 KST): https://knu-read.xyz 실제 운영 전환 및 Chrome 카카오 로그인→관리자 화면 성공. 기존 workers.dev 링크는 새 주소302 이동. HTTP는HTTPS308. 사용자 최종 전환 승인 적용 완료.
웹 경로: knu-read.xyz→Worker www/정적CDN→origin.knu-read.xyz→Cloudflare Tunnel→Ubuntu앱. 당시 Worker a9a69259-ee5b-4cb4-bc44-2fd67c39f491(소스1909d4c), VM 앱8e290f7/UI f946824. 이후 현재 버전은 위 미리보기 배포 기록을 따른다. 카카오 기존콜백6개+새콜백1개 저장.
공개 검증17/17 통과, 앱/Tunnel active/enabled, 브라우저 error/warn0. 공개 첫 화면 TTFB중앙값252ms(3회). DB업무데이터/스키마·Render·GitHub main·UI코드 변경 없음. 복귀용 Funnel/기존카카오콜백/env root600 보존.
실제 호스트 재부팅 자동복구 시험·DB 이전/백업 등의 원래 잔여 작업은 계속 미완료. 새 도메인/로그인 전환은 완료했으므로 다시 승인받거나 재적용하지 않는다. 상세 docs/MINIPC_DOMAIN_TUNNEL.md, outputs/cutover-verification.json, outputs/domain-tunnel-state.json.

아래는 과거 작업 기록이며 위 최신 상태를 우선한다.
전환 전 검증(16:25 KST): 첫 화면3회 중앙값 Funnel411ms→Tunnel159ms, health439ms→221ms. 결과 outputs/origin-verification.json. Worker 테스트6개/최종dry-run 및 VM URL변경read-only 검증 통과.
이전 준비: 사용자가 hosting.kr에서 knu-read.xyz 구매 후 연결 요청. 일반 Cloudflare Tunnel 전환 준비 중.
hosting.kr 로그인·정상 등록·DNS 레코드 0개 확인. Cloudflare Free zone 준비, 공개 DNS 게시 반영 대기.
사용자 승인 후 Cloudflare 네임서버 ian.ns.cloudflare.com / riya.ns.cloudflare.com을 hosting.kr에 저장 완료.
Tunnel bookmembers-minipc(0be092ee-05e5-4177-afc5-68d47bd2368b) 생성, Ubuntu cloudflared2026.10.5 설치 및 서비스 active/enabled, Cloudflare Healthy/서울4연결 확인. 토큰 root600/LoadCredential 보관.
origin.knu-read.xyz→127.0.0.1:5000 라우트/CNAME 생성 및 catch-all404 확인. 공식 등록부 NS 변경 반영, 공개 DNS는 아직 hosting.co.kr 값. 새 원본 공개 HTTPS/403/속도 검증은 DNS 전파 대기. 재개 검증 스크립트 work/domain-migration/Verify-Origin.ps1 준비.
기존 Worker 트래픽/공개 기준 URL/카카오/앱/Render/main/DB는 유지. 최종 전환은 별도 승인 필요. 1Password 일반 자동 로그인 허용 선호 반영. 상세 docs/MINIPC_DOMAIN_TUNNEL.md.

최신 완료(2026-10-28 15:08 KST): 사용자 승인 후 새 UI 정적 CDN/캐시를 운영에 적용했다.
VM 앱 8e290f7 (UI 내용 f946824 유지), Worker 69847a91-0a3f-49fd-850e-13d35b4410a4.
44개 공개 정적 파일은 해시 버전 URL/1년 캐시로 CDN에서 직접 제공. 공개 검사 22/22 통과.
앱 clean/active/enabled, DB health 정상, Chrome 로그인 화면 상태 유지 및 콘솔 오류 없음.
같은 CSS 3회 비교 중앙값: 원본 829ms → CDN 114ms. HTML/DB/Funnel 동적 지연은 남음.
Render·GitHub main·DB·도메인·카카오 설정 변경 없음. 재부팅 없음.
복귀 기준: 앱 f946824, Worker 9081c2bc-b183-4bb1-a6fc-4f5de9616ba1.
상세 docs/MINIPC_CDN_RELEASE.md 및 outputs/cdn-release-state.json. 실제 Claude Opus5.5 High 자문도 기록됨.
아래 과거 CDN 배포 보류·VM f946824 상태는 이 완료 기록으로 대체한다.
기존 미완료: 실제 Windows 재부팅 후 자동 복구 시험, 로컬 DB 이전/백업 등 이전 운영 전환 잔여 작업.

갱신: 2026-10-28 KST. 재부팅/세션 중단 후 이 파일부터 읽는다.
최신 UI 요청: f946824 로컬 통합 완료(e88a3f4), 관련 Python 94개 및 Node 검사 통과.
사용자 '미니 PC에만 배포' 승인 후 2026-10-28 14:22:53 KST VM 앱 f946824 배포 완료.
공개 검증 15항목 통과. GitHub main push/Render 변경 없음. 서비스 active/enabled, clean.
세부 범위·검증·복귀 절차: docs/MINIPC_UI_RELEASE.md. Worker CDN 배포 보류는 유지.
아래의 과거 VM bda8a82 표기는 이 최신 앱 릴리스 상태로 대체한다. bda8a82는 앱 복귀 기준이다.
최신 추가: 응답 속도 진단 완료. 공개 Funnel 지연과 정적 파일 no-store 확인.
Worker 정적 파일 CDN 제공 최적화는 로컬 검증까지 완료했으나 사용자가 공개 배포를 명시 보류했다.
곧 UI가 바뀔 예정이므로 전체 구조를 먼저 검토했다. 실제 Claude Opus5.5 High 자문 완료.
docs/MINIPC_ARCHITECTURE_REVIEW.md: 기존 Workers 주소+단일 VPC Service+비공개 Tunnel 평가 권고,
UI 릴리스에 정적 자산 해시/manifest 통합 검토. 모두 설계안이며 새 설치·배포·전환은 하지 않았다.
사용자가 VPC 베타 종료 후 비용을 우려함. 베타 이후 가격 미공개 확인; 영구 무료 전제로 채택하지 않는다.
상세 수치와 재개 절차: docs/MINIPC_PERFORMANCE.md. 운영 Worker·VM 코드는 아직 그대로다.
최신 재개: 사용자가 직접 재부팅한 뒤 계속 진행 요청. 아래 과거 '재부팅 보류' 기록은 이 항목으로 대체한다.
Windows 부팅 시각 2026-10-27 23:05:09 KST. Hyper-V Enabled, HypervisorPresent=true,
vmms Running/Automatic, 기존 VM 0개, Default Switch 확인. 결과: work/hyperv-postboot.json.
원격 main 재조회 bda8a82 유지. 사용자 VM 생성·Ubuntu 설치·SSH 키 등록 승인 후 VM 생성 완료.
Ubuntu 24.04.5·SSH·앱 실행 환경·보호된 비밀 설정·로컬 앱 가동 완료. Tailscale 패키지 설치 완료,
기존 tail97bc40.ts.net에 bookmembers-ubuntu 가입 완료, Running/Online 확인.
Funnel 공개·서버 전용 권한·인증키 만료 해제 완료. 공개 GET 검증 12항목 통과.
Worker 원본을 Funnel로 전환 완료, 공개 검증 8항목 통과. 호스트 자동 복구 검증 미완료.
공개 주소 변경 완료: https://www.knu-read.workers.dev . Cloudflare 계정용 이름 knu-read,
Worker 이름 www. 새 카카오 콜백 저장 및 VM의 기준 URL 변경·앱 재시작 완료.
새 주소의 공개 검증 8항목, 관리자 본인 실제 로그인·로그아웃, 조 편성 SSE 1회,
비로그인 추천 조회 및 기존 발제 공유 링크 확인 완료. 재부팅 후 자동 복구 검증은 남아 있다.
구축 후 검증용 Windows 재부팅 승인을 요청한 상태이며 아직 실행하지 않았다.
기존 Windows AutoAdminLogon=true를 읽기 확인했다. 설정은 유지하고, 자동 로그인 환경에서의
무인 복구와 엄밀한 'Windows 로그인 전' 복구 증거를 구분한다. 후자는 아직 미검증이다.
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
- Worker 주소: https://www.knu-read.workers.dev . 현재 원본은 https://bookmembers-ubuntu.tail97bc40.ts.net . GET 200, keep-alive status=ok/supabase=alive, no-store. 전환 버전 9081c2bc-b183-4bb1-a6fc-4f5de9616ba1(이름 변경 후 보존).
- 원본 비밀은 작업 폴더 work/origin-auth-secret.dpapi에 Windows DPAPI 암호화 저장. 절대 출력/커밋하지 말 것. 향후 VM에 같은 값을 안전하게 전달. Flask/Supabase 기존 키 재사용 안 함.
- Render My Workspace 읽기 승인 후 확인: srv-d06thnjuibrs73eu1r4g, free/docker/singapore, main 자동 배포 활성. 현재 live SHA는 bda8a82. healthCheckPath 비어 있음. Render 환경변수 변경 없음.
- Hyper-V 기능 활성화만 승인받아 완료: work/hyperv-enable-result.json의 Success=true/State=Enabled/RestartNeeded=true. 재부팅 아직 안 함.
- Ubuntu 24.04.5 Server ISO 다운로드 완료: work/ubuntu/ubuntu-24.04.5-live-server-amd64.iso. 공식 SHA256 일치(97f3d7ffb032c3eb3b23d2c8be9cc76e60c2c1f2c0146ba5ba9fe01cafae0fd8).
- VM 생성·systemd·Funnel·검증 실행 스크립트 및 runbook 준비. Python 3.12.16/venv는 작업 폴더에 격리 설치.

## 다음 순서 / 미완료

1. 완료: 사용자 직접 Windows 재부팅 후 Hyper-V 실제 상태 확인. 서비스 자동 복구 검증용 재부팅은 별도 후속 단계.
2. 완료: VM 생성·Ubuntu 설치·관리 SSH 키 등록, ISO 분리·디스크 부팅·SSH 검증.
   앱 실행 환경·비밀 이전·서비스 활성화 및 Tailscale 기기 가입도 완료.
3. 보안 코드 bda8a82는 Render 운영 배포 완료. 다른 UI 작업은 포함하지 않음. UI 통합 시 최신 main을 기준으로 보안 코드와 CSRF를 보존한다. 추가 main push는 새 배포를 일으키므로 승인 필요.
4. Kakao 새 www.knu-read 콜백까지 저장 완료(기존5개 유지, 총6개). 새 기준 URL·보안 쿠키 및 본인 관리자 계정 OAuth·로그아웃 확인 완료. Render의 과도기 OAuth 환경 변경은 계속 보류.
5. 완료: Ubuntu 서비스·비밀 설정·Tailscale 기기 가입. 별도 승인 후 HTTPS·서버 전용 태그·Funnel 공개·키 만료 해제 완료. 공개 경로에서 인증 없음/오류 403, 정상 키 앱·DB·로그인 시작 정상 확인.
6. 완료: 공개 Funnel 검증 후 사용자 승인으로 Worker→Funnel 전환. 별도 승인으로 www.knu-read 주소 변경·재검증 완료. 실제 OAuth·SSE·기존 공유 링크·추천 공개 조회 검증 완료. 운영 POST/실제 사진 업로드는 테스트 쓰기 금지에 따라 수행하지 않았다.
7. 재부팅/로그인 전 자동 복구와 실제 사이트 접근 검증. BIOS 정전 후 자동 켜짐 미확인. Tailscale 서버 노드 KeyExpiry=null 확인 완료.
8. Render 중지/삭제 승인 없음. 복구용으로 유지. 취약한 기준 main으로 롤백하지 않음.

## 승인 경계와 검증 한계

승인 완료: Hyper-V 기능만, Wrangler 권한·키링, Worker 생성·Secret·공개 GET, My Workspace 읽기, 백업 없이 해당 확장 SQL만.
미승인/보류: 추가 호스트 재부팅, Render 추가 코드·환경 변경, 여기 기록되지 않은 추가 Kakao 설정, Render 중지. VM 생성·Ubuntu 설치·관리 SSH 키 등록, 런타임·비밀 이전, 기존 tailnet 가입 및 HTTPS·전용 Funnel·서버 키 만료 해제는 승인받아 완료. bda8a82 보안 배포, Worker 원본 Funnel 전환, www.knu-read 주소 변경·새 콜백 추가·서버 URL 갱신·앱 재시작도 승인받아 완료.
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

## Tailscale 기존 계정 기기 추가 승인 (2026-10-28)

- 사용자가 새 계정이 필요한지 질문하여 기존 minipc와 같은 계정에 Ubuntu VM만 별도 기기로
  추가하는 구조를 설명함. 이어 'ㅇㅇ 걍 계속 진행해'로 기기 추가 승인.
- 기존 자동 승인 검토 차단은 위 명시 승인으로 해소. VM에서
  tailscale up --hostname=bookmembers-ubuntu --accept-routes=false --timeout=3m 실행.
  기존 Windows 노드 설정 변경 없음. exit node/서브넷/Tailscale SSH 광고 안 함.
- Chrome의 인증 탭에서 기존 계정 로그인·기기 연결을 사용자에게 요청 중.
  인증 링크/토큰은 이 파일에 기록하지 않음. auth 대기 CLI 종료만으로 연결 성공을 판단하지 말 것.
- 현재 Funnel status --json은 {}. 공개 설정 없음. 인증 후 status에서 실제 DNSName과
  tail97bc40.ts.net 일치, Online/BackendState 및 KeyExpiry를 확인한 뒤 다음 공개 승인 준비.
- CLI는 사용자 로그인 대기 3분 제한으로 종료됐으며, 마지막 상태는 NeedsLogin.
  Chrome 인증 탭(1023347714)을 handoff로 유지. 로그인 화면에는 아직 변화가 없었음.
  사용자 인증 완료 답변 후 먼저 VM status만 조회한다. CLI timeout을 링크 만료로 단정하거나
  불필요하게 새 인증 링크를 생성하지 않는다. 현재 서버 앱/기존 Windows Tailscale은 유지됨.

## Tailscale 연결·공개 Funnel 완료 (2026-10-28)

- 사용자 로그인 완료 후 기존 Windows 계정과 화면의 대상 계정이 일치함을 확인하고,
  승인된 bookmembers-ubuntu 기기 연결을 완료. Running/Online, tail97bc40.ts.net 일치.
- 실제 DNS: bookmembers-ubuntu.tail97bc40.ts.net, IPv4 100.118.28.68.
  초기 KeyExpiry 2027-04-26T00:35:43Z. 사용자가 후속 HTTPS·전용 권한·만료 해제·Funnel 공개 승인.
- 기존 정책의 grants/ssh 규칙은 그대로 유지하고 tagOwners 및 nodeAttrs만 추가.
  tag:bookmembers-server의 소유자는 autogroup:admin, funnel 허용 대상은 이 태그뿐.
  기본 마법사의 autogroup:member 전체 공개 권한 추가는 사용하지 않음.
- 정책 편집기 장문 입력이 중간에 멈춰 미저장 변경을 취소하고 전체 붙여넣기 사용.
  재진입한 편집기 전체 문자열이 준비안과 정확히 일치함을 확인한 뒤 저장함.
- Ubuntu 기기에만 태그 적용. 인증키 만료 해제 후 CLI KeyExpiry=null 확인.
  Windows minipc 노드는 변경하지 않음. HTTPS 활성화 UI에서 Disable HTTPS 버튼 확인.
- VM: tailscale funnel --bg --https=443 http://127.0.0.1:5000 성공.
  status JSON의 TCP443 HTTPS, / Proxy127.0.0.1:5000, AllowFunnel true 확인.
- Windows DNS는 공개 리졸버 지정에도 MagicDNS 내부 IP를 반환하므로, 외부 DNS-over-HTTPS로
  공개 릴레이 IP를 읽어 해당 IP에 연결하되 원래 호스트명으로 TLS 검증/SNI를 유지하여 테스트.
  인증서 검증 비활성화 없음. 원본 비밀은 DPAPI 복호화 메모리→stdin에서만 사용, 리다이렉트 추적 없음.
- work/vm-funnel-verification.json: 12항목 모두 true. 공개 경로, 누락/오류 키403,
  홈200·status=ok/supabase=alive, Kakao302·Worker콜백·state, Secure/HttpOnly/Lax,
  응답 비밀 미노출. 운영 POST·실제 OAuth 완료·회원 변경 없음.
- 관리 SSH를 고정 Tailscale IP로 실제 접속·기존 호스트 키 대조 후 로컬 설정에 반영.
  StrictHostKeyChecking=yes. 장애 시 Hyper-V에서 현재 LAN DHCP를 조회해 HostName만 일회 override.
- 원격 main 재확인 bda8a82 유지. UI 세션 파일은 변경하지 않음.
- Worker의 로컬 UPSTREAM_ORIGIN은 Funnel 전환안으로 준비, Wrangler4.153.0 dry-run 통과.
  아직 공개 배포하지 않았고 실제 Worker는 Render 유지. 전환·검증·실패 시 기존 원본 복귀 승인 대기.
- 공식 문서: https://tailscale.com/docs/reference/tailscale-cli/funnel (--bg 재부팅 복구),
  https://tailscale.com/docs/features/tags (태그와 키 만료),
  https://tailscale.com/docs/how-to/set-up-https-certificates (공개 인증서 기록).

## Worker 미니 PC 원본 전환 완료 (2026-10-28 09:47 KST 이후)

- 사용자: '오케이 바로 전환하고'로 Worker 원본 변경·검증·실패 시 기존 원본 복귀 승인.
- wrangler deploy 성공. Version ID 9081c2bc-b183-4bb1-a6fc-4f5de9616ba1.
  공개 URL https://book-member-maker.alstj816.workers.dev 유지,
  UPSTREAM_ORIGIN=https://bookmembers-ubuntu.tail97bc40.ts.net. 기존 Secret 유지.
- work/worker-cutover-verification.json의 8항목 모두 true: home, app_and_database,
  no_store, kakao_start, worker_callback, oauth_state, secure_session, no_origin_header.
  롤백 불필요. Render/DB/Kakao 설정/운영 UI 코드는 변경하지 않음.
- 사용자가 alstj816과 book-member-maker도 변경 가능한지 요청. Cloudflare 공식 문서에서
  계정용 subdomain 및 Worker 이름 모두 변경 가능함을 확인. 무료 주소는
  <worker-name>.<account-subdomain>.workers.dev 구조를 유지해야 함.
- 사용자 knu_read 희망에 대해 하이픈 knu-read로 대안 안내. www/app/read 중 앞부분 선택 및
  실제 Cloudflare 사용 가능 여부 확인 예정. 이름 확정·새 callback/앱 URL 준비 후 변경 직전 승인 필요.
- Chrome Cloudflare 로그인 탭 1023347728은 로그아웃 상태. IAB에 기존 탭 없음.
  Wrangler 키링 인증은 정상 유지되어 전환은 완료했으나 이름 변경 대시보드 로그인은 사용자 대기.
- work/pre-recovery-baseline.json 기록. Windows vmms/Tailscale 자동 시작·Running,
  guest bookmembers/tailscaled enabled/active, NRestarts0. 이번 작업에서 재부팅하지 않음.
  기존 부팅은 앱/Funnel 구축 전이므로 이 기록만으로 부팅 자동 복구 검증 완료라 표시하지 않는다.

## 공개 주소 www.knu-read 변경 완료 (2026-10-28)

- 사용자 최종 이름 www.knu-read.workers.dev 선택, Cloudflare·카카오 직접 로그인 완료.
- Cloudflare 계정 목록에는 Worker 1개만 존재. subdomain knu-read 사용 가능 확인.
  원래 주소 즉시 중단·전파 지연·새 주소 재로그인을 설명한 뒤 사용자 명시 승인받음.
- Kakao 앱1288463 / REST키4468347의 기존5 URI를 유지하고
  https://www.knu-read.workers.dev/login/kakao/callback 한 개 추가. 저장 후 키 목록으로
  이동한 화면에서 URI0개가 조회된 것은 저장 실패 증거가 아니었음. 원래 키 편집 화면에
  재진입하여 총6개와 기존5개 보존을 확인. 키·시크릿·동의항목 변경 없음.
- 콜백 재조회 전 서버 URL 변경 실행은 자동 승인 검토가 선행조건 미확인으로 차단.
  실제 콜백6개 저장을 확인한 뒤 같은 사용자 승인 범위로 재시도하여 허용됨.
- work/change-public-url.py: 기본 읽기 검증에서 applied=false, URL두값 외 보존 검증.
  승인 후 --apply로 /etc/book_member_maker/app.env의 PUBLIC_BASE_URL/KAKAO_REDIRECT_URI만
  원자 교체. 복구 사본 app.env.before-public-url-change는 root전용. 기존 비밀 유지.
- 앱 서비스만 재시작. 직후 첫 헬스는 준비 중 실패했지만 이어 active 및 app/database alive 확인.
- Cloudflare 기존 Worker 이름 www로 저장, 계정 subdomain knu-read로 저장.
  기존 Secret·원본 Funnel·배포이력 보존. wrangler deployments list --name www에서
  현재100% 버전9081c2bc-b183-4bb1-a6fc-4f5de9616ba1 확인. 별도 Worker 생성 안 함.
- 새 HTTPS 최초 검사에서 TLS handshake 오류가 있었으나 전파 후 정상 해소됨.
  인증서 검증 우회 없음. work/worker-new-url-verification.json의 8항목 모두 true.
- 브라우저 실제 URL과 DOM 링크 모두 https://www.knu-read.workers.dev 확인.
  접근성 화면에서 www가 생략되는 것은 표시 축약이며 실제 URL 리다이렉트가 아니었음.
  outputs/knu-read-live-site.png에 성공 화면 기록.
- 현재 공개 GET/DB/로그인 시작은 검증 완료. Chrome 탭1023347730의 새 사이트 로그인 화면에서
  기존 관리자 본인 카카오 로그인 완료를 사용자에게 요청 중. 아직 OAuth 완료로 기록하지 않는다.
- 재부팅·Render중지·운영 회원/예약/글 쓰기·다른 UI 세션 편집 없음.

## 새 주소 로그인·최소 실제 기능 검증 완료 (2026-10-28)

- 사용자가 기존 본인 카카오 계정으로 로그인 완료. 실제 URL /admin/dashboard와
  관리자 메뉴 표시 확인. 세션 쿠키를 추출하거나 서버 비밀로 세션을 위조하지 않음.
- 조 편성 화면에서 4명/1개조의 저장 없는 계산1회 수행. Worker→Funnel 경로의 EventSource
  시작 표시 후 '조 편성 결과'·'추천안1/총4명/1개조' 결과 렌더링 확인. '확정' 버튼은 누르지 않음.
  회원명·학번·명단·요청쿼리·공유토큰은 검증 출력/상태 파일에 기록하지 않음.
- 계산 중 MemoryCurrent=148094976bytes(약141MiB), NRestarts0, swap사용0,
  guest available 약451MiB 관찰. 대규모 부하 시험 아님.
- journalctl 본문을 출력하지 않고 서버 내부에서 민감한 명단 INFO 로그 패턴만 집계: 0개.
- 인증 쿠키가 없는 별도 IAB에서 /now 공개 목록과 기존 발제 링크를 실제로 열어
  정상 폼 표시·유효하지 않은 링크 오류 없음 확인. 링크 기준 origin이 새 www.knu-read와 일치.
  공유 토큰은 파일/출력에 저장하지 않음. /books/suggestions 공개 조회·로그인 안내 확인.
- 실제 관리자 페이지 재조회도 정상. 한 번 브라우저 navigation timeout 후 이미 로딩 완료된
  정상 페이지를 확인했으며 앱 오류 페이지는 아니었음.
- 기존 로그인 세션의 정상 '로그아웃' 링크를 눌러 공개 홈 복귀·로그인 링크 표시·관리자 메뉴 없음 확인.
  로그인·로그아웃 최소 확인 완료. 현재 Chrome 사이트 탭은 로그아웃된 새 공개 홈.
- app.env와 복구 사본 app.env.before-public-url-change 모두 root:root0600 확인.
- Windows/VM 재부팅은 아직 수행하지 않음. 자동 시작 구성과 Funnel 지속 설정은 적용됐지만,
  구축 후 Windows 로그인 전 접속 복구 증거가 없으므로 마지막 검증은 별도 승인 후 진행한다.

## 현재 완료 판정표

| 단계 | 상태 | 증거 / 남은 조건 |
|---|---|---|
| 저장소·Windows 환경 | 완료 | 원격 main bda8a82, 별도 사본·브랜치, UI 세션 파일 미수정 |
| 보안 코드·최소 회귀 | 완료 | 보안 배포 bda8a82, 관련 테스트와 CI 통과 |
| 운영 확장 SQL | 완료 | 사용자 백업 예외 승인, RPC2개·인덱스1개만 적용 |
| Worker·원본 인증 | 완료 | www.knu-read.workers.dev, 독립 Secret, Funnel 직접 누락/오류403 |
| Hyper-V·Ubuntu·앱 | 완료 | VM 자동 시작, systemd enabled/active, root전용 환경, Python3.12 |
| Tailscale·Funnel | 완료 | 전용 태그만 funnel 허용, HTTPS443→loopback5000, --bg, KeyExpiry=null |
| Worker→미니 PC 전환 | 완료 | 공개8항목·관리자 OAuth/로그아웃·SSE1회·추천/공유 링크 조회 |
| 사진/운영 POST | 제한 검증 | 프록시 코드·합성 테스트/경로 검토. 실제 데이터 쓰기·업로드 테스트 안 함 |
| Windows 재부팅 후 자동 복구 | 승인 대기 | 구축 후 재부팅 미실행. 기존 AutoAdminLogon=true 유지; 수동 서비스 시작 없이 복구 확인 예정 |
| Windows 로그인 전 자동 복구 | 미검증 | 기존 자동 로그인 때문에 재부팅 후 정상 접속만으로 로그인 전 복구를 입증할 수 없음 |
| 정전 후 전원 켜짐 | 미확인 | BIOS 전원 복구 정책은 OS에서 확정 못 함 |
| DB/Storage 외부 복구 | 보류 | 백업 스크립트만 준비, 외부 저장소·복구키·활성화·격리 복원 미완료 |
| Render·구주소 | 보존 | 기존 Render 직접 주소 유지. Worker OAuth 대체 설정은 사용자 결정으로 보류; 중지/삭제 미승인 |

## 재부팅 검증 직전 재개 기록 (2026-10-28)

- Windows Winlogon의 AutoAdminLogon 플래그만 조회하여 true 확인. 사용자명·비밀번호는 조회하거나 기록하지 않았다.
- 기존 자동 로그인 설정 변경 없음. Windows 재부팅은 별도 질문으로 승인 대기 중이며,
  승인이 없으면 실행하지 않는다. 승인 시 강제 앱 종료 없이 재부팅한다.
- 다른 UI 세션은 읽기 상태 조회에서 idle/마지막 검토 완료였다. 그 세션의 파일·설정은 변경하지 않았다.
- work/pre-recovery-baseline.json에 Windows 부팅 시각, Ubuntu boot_id, 서비스 enabled/active,
  Funnel 지속 설정, 현재 Worker 버전 및 URL을 저장했다.
- 재개 시 어떤 서비스도 먼저 수동 시작하지 말고 부팅 시각/boot_id 변경과 현재 상태를 조회한다.
  이어 새 Worker의 공개 8항목 검증을 수행하고 자동 복구 결과를 기록한다.
- 자동 로그인 환경의 정상 복구가 확인돼도 '로그인 전'을 별도로 입증했다고 기록하지 않는다.
  BIOS 정전 후 전원 복구와 외부 백업·격리 복원도 여전히 미확인/미활성 상태다.

## 성능 진단·최소 최적화 준비 (2026-10-28 13시 KST)

- 사용자 느린 반응 문의에 공개/loopback GET3회, 비인증 Funnel403 경로 비교, 자원 상태 읽기.
  운영 데이터·로그인 세션 변경 없음. 공개 네트워크 구간이 주요 지연; CPU/메모리 부족 증거 없음.
- 원격 main/VM bda8a82 유지 확인. 공개 홈 중앙값2,683ms vs loopback4ms,
  tailwind.css1,280ms vs3ms. 공개 Funnel 작은403도 반복879~1,156ms, 내부6ms 수준.
- infra/worker에 ASSETS binding·운영 릴리스 고정 공개 파일18개 준비. UI 원본 파일 수정 없음.
  HTML/API/OAuth/SSE no-store 유지. 관련 테스트6·dry-run·로컬 런타임6항목 통과.
- 아직 공개 배포하지 않음. 후속 사용자 답변은 '아직 배포하지 말고 구조부터 논의'.
  이후 UI 변경 예정과 Claude Opus5.5 High 자문 요청을 반영해 구조 검토를 먼저 진행한다.
  기존 최적화 배포를 자동 진행하지 않는다. VM 재시작·DB/Kakao 변경 없음.
- 재부팅 자동 복구 검증 승인 대기와 백업 미활성 등 기존 남은 항목은 그대로다.


## 2026-10-28 LMS 개선 작업 — 운영 적용 완료

10개 UX/기능 개선 및 브라우저 푸시를 사용자 승인 후 적용했다. 운영 앱 8610b17, Worker 4529a9b6-e824-4fbe-b11e-6802d0c92fd1.
SQL 확장/추가 회차 11개 숨김, 새 타이머 자동 시작/키 생성 완료. 패키지 읽기 권한 오류 복구 후 작업 성공.
공개 GET·권한·CDN 해시 및 운영 화면 점검 통과. 사용자의 휴대폰 알림 허용 후 실제 수신/클릭은 확인 대기.
상세/재개 기록은 `LMS_IMPROVEMENTS_20261028.md`, 작업폴더 `outputs/lms-improvements-state.json`.
전체 호스트 재부팅·백업/격리 복원은 위의 별도 미완료 상태 유지. Render/GitHub main 변경 없음.


## 2026-10-28 학기별 UI·공지·KNU 공유 이미지 — 운영 적용 완료

사용자 ‘SQL·앱·CDN·미리보기 갱신 승인’ 후 앱 1e1caed, Worker fa1b1796-2570-45ef-8eed-d237851a9051 적용.
공지 범위 열/FK/인덱스 확장, 기존 글 보존 확인, 공개·로그인 시작·개인 내역 보호·운영 화면 조회 검증 통과.
카카오 홈페이지 미리보기 캐시 초기화 및 KNU 책반우 배너 확인 완료.
최신 상세: `SEMESTER_NAVIGATION_REVIEW_20261028.md`, 작업 루트 `outputs/semester-ui-state.json`.
Render/main/위키/도메인/카카오 로그인/Windows 재부팅 변경 없음. 기존 푸시 수신·자동 복구·외부 백업 검증은 별도 미완료.
