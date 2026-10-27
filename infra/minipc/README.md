# 미니 PC 설치·전환 실행 순서

재개 기준: `docs/MINIPC_DEPLOY_STATUS.md`. 모든 운영 변경은 직전 사용자 승인 필요.
실제 Worker/Funnel 주소는 아직 미발급. 설정 예시의 빈 값은 확정 주소로만 채운다.

1. 보안 SQL `supabase/migrations/*_minipc_account_security.sql`을 검토한다.
   운영 백업 및 Storage 보존을 확인하고 중복 social_id **그룹 수만** 읽기 조회한다.
   승인된 해당 SQL만 적용한다. 전체 db push 금지. 기존 계정 연결 pending은 자동 처리하지 않는다.
2. Render 코드 배포는 사용자 승인 후 검증 커밋으로 수행한다. main은 자동 배포이므로 지금 push 금지.
   구형 연결 pending은 별도 수동 점검. 새 RPC 없는 상태에서 앱부터 배포하면 관련 API가 실패하므로 SQL 먼저.
   새 카카오 인증 표식 없는 기존 세션은 회원 명의 작성 시 1회 재로그인한다. 기존 조회 로그인은 유지.
3. Worker: `infra/worker`에서 `npm ci`, `npx wrangler login`(사용자 직접 인증).
   공개 승인 후 `npx wrangler secret put ORIGIN_AUTH_SECRET`, `npx wrangler deploy`.
   새 원본 비밀은 로컬 입력으로 넣고 출력/채팅/커밋 금지. 기존 Flask/Supabase 키 재사용 금지.
   현재 Render 원본 URL은 저장소 설정에서 확인했으며 실제 운영 대시보드와 대조 후 배포한다.
   주소가 발급되면 기록하고 PUBLIC_BASE_URL 및 Kakao 콜백을 승인 후 설정한다.
   Worker 주소가 준비되기 전 OAuth 성공을 기대하지 않는다.
4. Hyper-V 기능 활성화 승인 후 관리자 PowerShell에서 `Enable-HyperV.ps1` 실행.
   재부팅은 별도 승인. VM 생성도 별도 승인 후 `New-BookVm.ps1`에 검증된 Ubuntu 24.04 Server ISO와 VM 저장 경로 전달.
   기존 Windows Tailscale/RDP/개인 파일/스위치 변경 금지. VM 이름 bookmembers-ubuntu.
   2 vCPU, 동적 RAM 1/1.5/3GiB, 동적 VHDX 30GiB, Gen2, 자동 시작 Start, 종료 ShutDown.
   설치 후 DVD를 분리하고 시스템 디스크 우선 부팅으로 바꾼다. 변경 전 생성 VM만 대상으로 확인한다.
5. Ubuntu 최소 설치 후 검증된 Git SHA의 소스를 `/opt/book_member_maker`에 배치한다.
   서버에 개인 GitHub 토큰을 복사하지 않고 검증 커밋 archive를 전송해도 된다.
   `infra/minipc/install-service.sh`를 VM 안에서 실행한다. 운영 Node/Docker/Nginx 불필요.
   `/etc/book_member_maker/app.env`는 root:root 0600, 부모 0700. 예시의 정확한 KAKAO_OAUTH_* 이름 사용.
   기존 키는 안전한 로컬 입력으로 이전. 원본 비밀은 Worker와 같은 별도 값.
   PUBLIC_BASE_URL=실제 Worker HTTPS origin, KAKAO_REDIRECT_URI=그 origin + /login/kakao/callback.
6. VM에 공식 Ubuntu 24.04 Tailscale 패키지 설치. 사용자 인증으로 별도 노드 가입.
   기존 Windows 노드는 그대로 둔다. `systemctl enable --now tailscaled`.
   공개 승인 전 `tailscale funnel --help` 확인. 승인 후 `tailscale funnel --bg 5000` 및 상태 확인.
   MagicDNS, HTTPS, funnel node attribute 필요. 서버 노드 키 만료/인증 만료 정책도 사용자 계정에서 확인한다.
   정책 변경이 필요하면 별도 승인. 자동 로그인·무인 복구는 노드 인증이 유효한 동안만 가능하다.
7. 로컬 검증: 서비스 상태 + root로 `.venv/bin/python infra/minipc/healthcheck.py`.
   HTTP 200만 확인하지 않고 status=ok와 supabase=alive 둘 다 확인한다.
   Funnel 직접 접근 403, Worker 접근 정상; 대표 SSE/쿠키/리다이렉트·공유 링크 확인.
   운영 회원/예약/글을 테스트로 작성하지 않는다. OAuth는 승인된 관리자 본인으로만 확인.
8. 전환 승인 후 Worker UPSTREAM_ORIGIN만 실제 Funnel origin으로 변경한다.
   Render는 보안 패치 및 동일 Worker Origin/OAuth 지원 상태로 보존한다.
   실패 시 승인 후 패치된 Render origin으로 되돌린다. 취약한 기준 main으로 롤백하지 않는다.
9. 재부팅 승인 후 Windows 로그인 없이 VM→Gunicorn→Tailscale/Funnel→Worker 접속을 검증한다.
   전원 복구 후 자동 켜짐은 BIOS 설정 별도 확인 사항이다. 절전·최대절전 정책도 읽기 확인 후
   서버 운영에 필요하면 별도 승인받아 조정한다. 현재 이를 확인/변경하지 않았다.

원본 비밀은 Gunicorn access log에 기록하지 않는다. 기본 access log는 꺼둔다.
코드에서 별도 주기 scheduler는 발견하지 않았지만 Render 대시보드 외부 예약 작업/알림 설정은 아직 미확인이다.
운영 전환 전에 중복 예약 작업을 확인한다.

## 공식 문서 확인 (2026-10-27)

- https://developers.cloudflare.com/workers/platform/limits/ : Free 100,000/day, CPU 10ms, 요청 body Free 100MB.
- https://tailscale.com/docs/features/tailscale-funnel : MagicDNS/HTTPS/funnel 권한, 조정 불가능한 대역폭 제한.
- https://tailscale.com/docs/reference/tailscale-cli/funnel : `--bg` 지속 구성은 실제 VM CLI 도움말로 다시 확인.
- https://supabase.com/docs/guides/database/functions : SECURITY INVOKER, EXECUTE 권한 제한.

PGlite 검증은 WASM PostgreSQL 기반의 격리 SQL 검증이다. 운영 PostgreSQL 15에서의 실제 적용과
다중 연결 동시성 검증을 대신하지 않는다. SQL은 일관된 순서로 테이블/행 잠금을 획득한다.
