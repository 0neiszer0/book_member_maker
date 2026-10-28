# 미니 PC 설치·전환 실행 순서

재개 기준: `docs/MINIPC_DEPLOY_STATUS.md`. 모든 운영 변경은 직전 사용자 승인 필요.
2026-10-28 추가: 승인된 일반 Cloudflare Tunnel `bookmembers-minipc` 설치/연결 완료.
`bookmembers-cloudflared.service`는 root 전용 토큰을 systemd credential로 읽으며 부팅 자동 시작한다.
새 origin.knu-read.xyz의 DNS 전파/공개 검증 및 최종 Worker 전환은 `docs/MINIPC_DOMAIN_TUNNEL.md`를 따른다.
아래 기존 Funnel은 비교·복귀 경로로 유지 중이다. Enable 상태는 실제 호스트 재부팅 검증을 대신하지 않는다.
Worker는 https://www.knu-read.workers.dev 에 배포되어 현재 미니 PC의
Funnel https://bookmembers-ubuntu.tail97bc40.ts.net 을 가리킨다. 2026-10-28 승인·전환·공개 검증 완료.
개인 식별자가 없는 새 공개 주소로의 변경도 승인·적용·검증 완료. 실제 진행 상태는 상태 문서를 따른다.
이전 alstj816 주소는 중단됐고 자동 리다이렉트되지 않는다. Cloudflare Worker 이름은 `www`이며,
후속 배포는 이 이름을 사용한다. 기존 `book-member-maker` 이름으로 새 Worker를 만들지 않는다.

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
   Render 과도기에는 기존 KAKAO_REDIRECT_URI를 Render 콜백 그대로 유지한다.
   Worker 콜백 등록 승인 후 KAKAO_PROXY_REDIRECT_URI를 Worker 콜백으로 추가하고,
   PUBLIC_BASE_URL을 Worker origin, ADDITIONAL_ALLOWED_ORIGINS를 기존 Render origin으로 설정한다.
   Render에도 Worker와 같은 ORIGIN_AUTH_SECRET을 설정하되 REQUIRE_ORIGIN_AUTH=false로 둔다.
   인증된 Worker 요청만 새 콜백을 사용한다. 두 호스트의 로그인 쿠키는 서로 공유하지 않는다.
4. Hyper-V 기능 활성화 승인 후 관리자 PowerShell에서 `Enable-HyperV.ps1` 실행.
   재부팅은 별도 승인. VM 생성도 별도 승인 후 `New-BookVm.ps1`에 검증된 Ubuntu 24.04 Server ISO와 VM 저장 경로 전달.
   기존 Windows Tailscale/RDP/개인 파일/스위치 변경 금지. VM 이름 bookmembers-ubuntu.
   2 vCPU, 동적 RAM 1/1.5/3GiB, 동적 VHDX 30GiB, Gen2, 자동 시작 Start, 종료 ShutDown.
   설치 후 DVD를 분리하고 시스템 디스크 우선 부팅으로 바꾼다. 변경 전 생성 VM만 대상으로 확인한다.
   선택적으로 `autoinstall.yaml.example`과 `prepare-install-media.py`로 CIDATA 설치 ISO를 만든다.
   제작용 Python에만 pycdlib/PyYAML이 필요하며 운영 앱 요구사항에는 넣지 않는다.
   `--public-key <공개키 파일> --output <새 seed.iso>`로 생성 후 `New-BookVm.ps1 -SeedIsoPath`에 전달.
   관리 개인키는 Git 밖 접근 제한된 위치에 보관한다. 설치 ISO에는 공개키만 포함한다.
   최소 설치의 bookadmin은 키 인증·sudo 관리 계정이고 앱은 별도 bookapp으로 실행한다.
   새 VM에는 지정 VHDX 하나만 부착한다. 자동 설치는 그 VM의 /dev/sda만 사용한다.
   설치 중 startup RAM 3GiB 사용 후 설치 poweroff를 확인하고 1536MiB로 복귀한다.
   설치 확인 화면과 종료 결과를 확인하고, 설치 ISO를 분리한 후 디스크로 부팅한다.
5. Ubuntu 최소 설치 후 검증된 Git SHA의 소스를 `/opt/book_member_maker`에 배치한다.
   서버에 개인 GitHub 토큰을 복사하지 않고 검증 커밋 archive를 전송해도 된다.
   `infra/minipc/install-service.sh`를 VM 안에서 실행한다. 운영 Node/Docker/Nginx 불필요.
   `/etc/book_member_maker/app.env`는 root:root 0600, 부모 0700. 예시의 정확한 KAKAO_OAUTH_* 이름 사용.
   기존 키는 안전한 로컬 입력으로 이전. 원본 비밀은 Worker와 같은 별도 값.
   PUBLIC_BASE_URL=실제 Worker HTTPS origin, KAKAO_REDIRECT_URI=그 origin + /login/kakao/callback.
6. VM에 공식 Ubuntu 24.04 Tailscale 패키지 설치. 사용자 인증으로 별도 노드 가입.
   `install-tailscale.sh`는 패키지·tailscaled 자동 시작만 수행한다. 현재 패키지 설치가 완료돼도
   NeedsLogin이면 아직 네트워크 가입 전이다. 노드 가입은 명시 승인 후 `tailscale up`으로 시작한다.
   기존 Windows 노드는 그대로 둔다. `systemctl enable --now tailscaled`.
   공개 승인 전 `tailscale funnel --help` 확인. 승인 후 `tailscale funnel --bg 5000` 및 상태 확인.
   MagicDNS, HTTPS, funnel node attribute 필요. 서버 노드 키 만료/인증 만료 정책도 사용자 계정에서 확인한다.
   정책 변경이 필요하면 별도 승인. 자동 로그인·무인 복구는 노드 인증이 유효한 동안만 가능하다.
   현재 승인·적용 상태(2026-10-28): 기존 tail97bc40.ts.net에 bookmembers-ubuntu 가입,
   전용 tag:bookmembers-server 적용, 이 태그만 funnel 허용, 노드 KeyExpiry=null.
   `tailscale-policy.fragment.jsonc`는 기존 정책에 병합하는 조각이며 전체 정책을 덮어쓰는 파일이 아니다.
   HTTPS 인증서 기능 활성화 후 `tailscale funnel --bg --https=443 http://127.0.0.1:5000` 적용 완료.
   실제 원본: https://bookmembers-ubuntu.tail97bc40.ts.net . Worker 전환 완료와는 별개다.
   관리 SSH는 고정 Tailscale IP 100.118.28.68, 기존 VM 호스트 키를 엄격 검증하도록 설정했다.
   Tailscale 장애 때는 Hyper-V에서 현재 DHCP 주소를 읽고 `ssh -F <설정> -o HostName=<현재IP>`로
   같은 호스트 키를 검증해 접속한다. 최초 LAN IP 172.25.178.73을 영구 주소로 가정하지 않는다.
7. 로컬 검증: 서비스 상태 + root로 `.venv/bin/python infra/minipc/healthcheck.py`.
   HTTP 200만 확인하지 않고 status=ok와 supabase=alive 둘 다 확인한다.
   Funnel 직접 접근 403, Worker 접근 정상; 대표 SSE/쿠키/리다이렉트·공유 링크 확인.
   운영 회원/예약/글을 테스트로 작성하지 않는다. OAuth는 승인된 관리자 본인으로만 확인.
8. 전환 승인 후 Worker UPSTREAM_ORIGIN만 실제 Funnel origin으로 변경한다.
   Render는 보안 패치 버전 bda8a82를 보존한다. 사용자 결정으로 Render의 Worker OAuth 환경 설정은
   보류됐으므로, Render로 돌아가면 전환 이전과 같이 Render 직접 로그인 주소를 사용해야 한다.
   두 호스트의 쿠키는 공유되지 않는다. 완전한 Worker OAuth 대체 원본으로 간주하지 않는다.
   실패 시 승인 후 패치된 Render origin으로 되돌린다. 취약한 기준 main으로 롤백하지 않는다.
9. 재부팅 승인 후 수동 서비스 시작 없이 VM→Gunicorn→Tailscale/Funnel→Worker 접속을 검증한다.
   현재 Windows AutoAdminLogon=true이며 기존 설정은 유지한다. 이 환경에서 재부팅 후 접속 성공은
   무인 복구 증거지만, 그 자체로 Windows 로그인 전 접속을 입증하지는 않는다.
   재부팅 전 work/pre-recovery-baseline.json과 Windows 부팅 시각·Ubuntu boot_id를 비교한다.
   SSH는 고정 Tailscale IP와 기존 호스트 키로 접속하며, 서비스 상태부터 확인한다.
   전원 복구 후 자동 켜짐은 BIOS 설정 별도 확인 사항이다. 절전·최대절전 정책도 읽기 확인 후
   서버 운영에 필요하면 별도 승인받아 조정한다. 현재 AC/DC 절전·최대절전 timeout은 모두 0임을 읽기 확인했고 변경하지 않았다.

원본 비밀은 Gunicorn access log에 기록하지 않는다. 기본 access log는 꺼둔다.
코드에서 별도 주기 scheduler는 발견하지 않았지만 Render 대시보드 외부 예약 작업/알림 설정은 아직 미확인이다.
운영 전환 전에 중복 예약 작업을 확인한다.

2026-10-27 추가 점검: Render My Workspace에는 웹 서비스 2개만 있고 Cron/Background Worker는 없다.
Supabase에는 pg_cron 확장이 없고 Storage 객체는 0개다. 타사 예약 호출의 존재 여부는 이 조회로 확정하지 않는다.

## 재부팅 전 실행 가능한 운영 반영 순서

1. 최신 main이 91b7dd6인지 직전 다시 확인하고, 승인 후 보안 브랜치를 main에 fast-forward push한다.
   다른 UI 사본의 미완료 변경은 포함하지 않는다. main이 바뀌었으면 강제 push하지 말고 재검토한다.
2. Render의 main 자동 배포 결과와 실제 SHA를 확인한다. 별도 중복 deploy 호출은 하지 않는다.
   이 첫 단계에서는 환경변수·Kakao 설정·회원 안내 주소를 바꾸지 않는다.
3. 비회원 공개 GET과 keep-alive의 status/supabase 값을 확인한다. 운영 데이터로 POST 테스트를 하지 않는다.
   실패하면 원인을 수정한 보안 커밋으로 재배포 승인을 받는다. 취약 버전으로 자동 rollback하지 않는다.
4. Kakao 콘솔의 기존 앱·콜백 확인 후 정확한 Worker 콜백 추가를 별도 승인받는다.
   이후 위의 Render 과도기 환경변수 변경을 승인받고 두 호스트 OAuth를 각각 확인한다.
5. DB/Storage 백업은 복구키와 외부 저장소를 확정한 뒤 활성화하고 격리 복원을 확인한다.
   현재 백업은 미설정이며, SQL 확장에 대한 기존 백업 예외 승인이 다른 DB 변경으로 확대되지 않는다.

## 백업 준비 상태와 활성화 조건

`backup.py`, `backup.env.example`, `bookmembers-backup.service/.timer`는 로컬 준비본이다.
설치·예약 활성화·실제 데이터 추출·클라우드 업로드는 아직 하지 않았다. 별도 ZIP도 만들지 않는다.
현재는 공용 Gmail/Drive 연결을 요청하지 않는다. 실제 구축 시 승인된 외부 저장소를 지정한다.

- Ubuntu에 PostgreSQL 클라이언트(원본 15 이상을 읽을 수 있는 버전), age, rclone이 필요하다.
  기존 Python venv의 storage3/python-dotenv를 재사용한다. Docker나 로컬 DB 서버는 필요 없다.
- `backup.env`와 `backup.pgpass`, `rclone.conf`, `app.env`는 Git 밖 root:root 0600.
  Supabase Connect 화면의 실제 session pooler 호스트·사용자와 기존 DB 비밀번호를 사용한다.
  서비스 키는 DB 비밀번호를 대체하지 않는다. 비밀번호를 모르더라도 임의 재설정하지 않는다.
- 서버에는 age **공개키만** 둔다. 복구용 개인키는 PC 밖에 안전하게 보관하고 실제 복호화로 확인한다.
  현재 DPAPI 파일은 다른 PC에서 바로 복호화할 수 있는 백업이 아니다.
- rclone remote가 승인된 외부 저장소를 가리키는지 확인한다. local/alias로 같은 디스크를 지정하면
  오프사이트 백업이 아니다. 해당 OAuth와 첫 업로드 범위를 승인받는다.
- `/var/lib/bookmembers-backup`을 root:root 0700으로 준비한다. 첫 실행 전 용량과 보관 기간을 정한다.
  이 준비본은 로컬/원격 백업을 자동 삭제하지 않는다. 계속 실행하면 용량이 증가하므로
  보존 정책·삭제 승인·실패 알림 방법이 정해지기 전 timer를 활성화하지 않는다.

승인 후 먼저 `sudo .venv/bin/python infra/minipc/backup.py`로 로컬 설정만 검사한다.
`--run`을 붙여야 원본 읽기와 업로드를 수행한다. 스크립트는 DB INSERT/UPDATE/DELETE를 하지 않는다.
표준 PostgreSQL custom dump(public + supabase_migrations, 데이터·함수·RLS·ACL 포함),
Storage 버킷 설정·파일 내용·원래 경로 매핑과 SHA256, 확장 버전 목록을 암호화 TAR에 담는다.
Storage 관리 스키마의 DDL도 참고용으로 보존하지만 새 Supabase에 그대로 덮어쓰지 않는다.
Supabase 프로젝트 설정, Auth 사용자, 글로벌 역할 비밀번호, 앱/Worker 비밀은 이 백업에 포함하지 않는다.
현재 앱은 자체 카카오 세션과 public 회원 테이블을 사용한다. 사용 범위가 늘면 백업 범위도 검토한다.

DB dump는 일관된 스냅샷이지만 Storage와 하나의 원자적 스냅샷은 아니다. 삭제·크기 변경·조회 실패는
백업을 실패 처리하나 동시 수정 전체를 검출한다고 보장하지 않는다. 최종 이전용 백업은 승인된
쓰기 중지 구간에 수행한다. 임시 평문 dump는 0700 폴더에서만 생성하고 정상/예외 종료 시 정리한다.
정전·강제 종료 후 남은 `.plain-*` 폴더는 상태 확인 후 별도 정리한다.
업로드 뒤 rclone download 비교가 성공해야 `COMPLETE.json`을 올린다. 완료 표시 없는 원격 폴더는
성공한 복구 지점으로 쓰지 않는다. 업로드 검증은 실제 DB 복원 성공을 뜻하지 않는다.

첫 실행 후의 격리 복원 검증:

1. 암호문과 COMPLETE.json을 별도 작업 위치에 내려받아 SHA256을 비교하고, 외부 보관 개인키로
   `age --decrypt`하여 접근 제한된 임시 위치에 복호화한다. manifest와 파일 hash를 대조한다.
2. 신규 격리 Supabase 또는 필요한 역할·확장을 준비한 폐기 가능한 PostgreSQL만 대상으로 한다.
   운영 연결 문자열 사용 금지. `pg_restore --list`로 내용을 검토한 뒤
   `pg_restore --exit-on-error --single-transaction --no-owner --dbname=<격리 DB> database.dump` 실행.
   ACL을 생략하지 않는다. 익명 역할의 새 보안 RPC 실행 금지, service_role 실행 가능을 확인한다.
3. manifest의 버킷 공개 여부·MIME/크기 제한을 재현하고, 파일을 원래 경로에 복원해 hash를 비교한다.
   Storage 테이블에 직접 INSERT하지 않고 Storage API를 쓴다. 공개 버킷에 회원 사진을 옮기지 않는다.
4. 회원/주요 테이블 건수, 시퀀스, 보안 함수·인덱스, 첨부 파일 하나를 비교한다.
   실제 계정으로 운영 쓰기 테스트하지 않는다. 증거·복구 시각만 상태 문서에 기록한다.
5. 성공·보존/알림 정책 승인 뒤에만 systemd 파일을 설치하고 timer를 enable한다.
   준비된 일정은 한국 시각 매일 03:15(+최대 10분), Persistent=true. 지금 활성화된 일정이 아니다.

합성 검증: `python -m unittest testing.test_minipc_backup -v`.
네이티브 pg_dump/age/rclone 및 실제 암호화 왕복·외부 저장소·복원은 Ubuntu 준비 후 확인해야 한다.

## 공식 문서 확인 (2026-10-27)

- https://developers.cloudflare.com/workers/platform/limits/ : Free 100,000/day, CPU 10ms, 요청 body Free 100MB.
- https://tailscale.com/docs/features/tailscale-funnel : MagicDNS/HTTPS/funnel 권한, 조정 불가능한 대역폭 제한.
- https://tailscale.com/docs/reference/tailscale-cli/funnel : `--bg` 지속 구성은 실제 VM CLI 도움말로 다시 확인.
- https://supabase.com/docs/guides/database/functions : SECURITY INVOKER, EXECUTE 권한 제한.

PGlite 검증은 WASM PostgreSQL 기반의 격리 SQL 검증이다. 운영 PostgreSQL 15에서의 실제 적용과
다중 연결 동시성 검증을 대신하지 않는다. SQL은 일관된 순서로 테이블/행 잠금을 획득한다.
