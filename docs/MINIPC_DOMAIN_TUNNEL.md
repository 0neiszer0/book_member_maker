# knu-read.xyz / Cloudflare Tunnel 연결 준비

2026-10-28. 사용자: hosting.kr에서 knu-read.xyz를 1년 구매했다고 알림. 페이지 이동 약 4초 지연을 호소.
상태: **hosting.kr 등록 및 Cloudflare 무료 zone 확인 완료. 네임서버 변경·Tunnel 설치 직전 승인 대기. 기존 운영 변경 없음.**

## 최신 진행 / 승인 요청안

- hosting.kr 로그인 완료. knu-read.xyz 정상, DNS 레코드 0개, 만료 2027-10-28 23:59 표시. 자동연장 설정은 건드리지 않았다.
- 공식 .xyz RDAP에서도 등록 2026-10-28T06:15:02Z 및 기존 네임서버 4개 확인. transfer prohibited/add period 상태이며 client/server hold는 없다. 1.1.1.1·8.8.8.8·.xyz 권한 DNS는 이 시점 NXDOMAIN이라 DNS 게시 반영을 추가 확인해야 한다.
- Cloudflare Free zone을 생성하고 DNS scan 0개 확인. Bot Preference Sync는 꺼서 애플리케이션 robots.txt를 자동 변경하지 않도록 준비했다.
- 할당 네임서버: `ian.ns.cloudflare.com`, `riya.ns.cloudflare.com`.
- hosting.kr 변경 모달에 위 두 개만 입력했고 **저장은 누르지 않았다**. 기존 ns1~ns4.hosting.co.kr은 아직 적용 중이다.
- 공식 cloudflared 2026.10.5 amd64 deb 다운로드 및 SHA256 검증 완료. VM에는 설치하지 않았다.
- 다음 승인 범위: 위 네임서버 저장, 일반 Tunnel bookmembers-minipc 생성, 전용 토큰을 VM root 전용 파일에 저장, cloudflared 서비스 설치·자동 시작, origin.knu-read.xyz를 localhost5000에 연결하고 무인증403 및 읽기 전용 건강/속도 비교.
- 기존 공개 Worker 원본/회원 안내 URL/카카오/Render/DB/재부팅은 이 준비 승인 범위에 넣지 않는다. 공개 전환 직전 별도 승인 유지.

## 로그인 선호 변경

사용자가 1Password 연결 후 앞으로 자동 로그인도 처리해 달라고 요청했다. 이 프로젝트의 일반 로그인은 브라우저 확장 자동완성이 가능한 범위에서 사용하도록 허용한 것으로 기록한다. 이전 첨부 지침서의 일반 로그인 수동 위임보다 최신 사용자 요청을 우선한다.
브라우저 AX에서 1Password 메뉴 안내를 확인했다. 현재 도구에는 금고 직접 조회/인증 전용 API가 없다. 1Password 잠금 해제·휴대폰 확인·보안키 등 사용자 확인이 필요한 경우에만 요청한다. 비밀번호를 채팅/로그/기록에 출력하지 않는다. DNS·서비스·새 보안 권한 변경 직전 승인 조건은 그대로다.

## 최초 확인 (아래 미완료 표시는 위 최신 기록으로 대체)

- Cloudflare 계정 d282d00422ba114110e1e47218b88516 로그인 유지. 도메인 추가 화면만 열었고 생성하지 않았다.
- hosting.kr은 Megazone Accounts 로그인 필요. 사용자에게 로그인 요청하고 해당 탭을 handoff로 유지.
- 1.1.1.1 공개 DNS에서 NS/A/MX/DS 모두 NXDOMAIN. 이것만으로 미구매라고 단정하지 않는다. 신규 등록 반영 대기 또는 정확한 도메인명 확인이 필요하다.
- Ubuntu amd64, cloudflared 미설치. 기존 bookmembers active/enabled, 앱 8e290f7, clean.
- 현재 Worker 69847a91-0a3f-49fd-850e-13d35b4410a4 / 기존 Funnel / 정적 CDN 정상 유지.

## 준비한 연결 구조

브라우저 → knu-read.xyz → 기존 Worker www 및 정적 CDN → origin.knu-read.xyz → Cloudflare Tunnel → Ubuntu 127.0.0.1:5000.

도메인 등록·갱신은 hosting.kr에 둔다. 기관 이전이나 웹호스팅/별도 SSL 상품 구매가 필요하지 않다.
Cloudflare Free DNS zone과 일반 공개 Tunnel을 사용한다. Workers VPC 베타를 도입하지 않는다.
도메인 문자열 변경 자체가 속도 개선은 아니다. Funnel을 대체하는 연결의 실제 지연을 확인해야 한다.
기존 Worker의 원본 인증키 검사·헤더 정리·HTML/API no-store·정적 CDN은 유지한다.
Tunnel 원본 직접 호출은 기존 비밀키가 없으면 403이어야 한다. 원본 비밀키를 URL에 넣지 않는다.
Tailscale SSH 관리는 계속 사용하고, Funnel은 최초 비교/복귀 기간에 보존한다.

## 실행 순서와 승인 경계

1. 사용자가 hosting.kr 로그인 완료 → 나의 서비스 > 도메인 > 정확한 구매 도메인과 등록 상태 확인. 기존 네임서버·DNSSEC·사용 중인 DNS 레코드 확인.
2. Cloudflare의 Connect a domain(Transfer/Buy 아님), Free 플랜으로 zone 준비. 실제 할당된 네임서버 두 개를 기록한다. 다른 도메인의 값을 추측하지 않는다.
3. 준비된 정확한 네임서버 변경안과 Tunnel 설치·토큰 root 보관·자동 시작·원본 공개 범위를 제시하여 실행 직전 승인받는다. hosting.kr 네임서버/DNS 탭에서 네임서버를 교체한다. 로그인/MFA/소유자 인증은 사용자에게 맡긴다.
4. DNS 활성화 후 Ubuntu cloudflared 설치 및 remotely-managed tunnel 생성/연결. origin.knu-read.xyz 한 호스트만 localhost5000에 연결하고 catch-all은404. 새로운 토큰은 채팅·로그·Git에 출력하지 않는다.
5. 기존 URL/앱 설정을 유지하며 후보 원본의 건강·무인증403·GET 시간을 소수 쌍으로 비교한다. 실제 회원 POST를 복제하지 않는다.
6. 최종 전환 직전 승인 후 Worker UPSTREAM을 새 origin으로 바꾸고 knu-read.xyz Custom Domain 연결. 공개 기준 주소/허용 Origin/카카오 콜백의 정확한 변경값도 함께 승인받아 적용한다. 기존 workers.dev/콜백은 복귀 및 기존 링크 호환을 위해 유지하는 안을 검토한다.
7. 공개 GET/OAuth 시작/본인 로그인/속도 확인. 회귀 시 이전 Worker 원본과 보관한 앱 공개 URL 설정으로 복귀. Render/main/DB는 변경하지 않는다.

hosting.kr 공식 안내상 네임서버 반영은 약 24시간 내외이며 실제 DNS 상태를 확인해야 한다. 기존 workers.dev 운영에는 새 도메인 DNS 대기 자체가 영향을 주지 않는다.

## 준비 파일 (운영 미적용)

작업 폴더 `work/domain-migration/`:
- `proposal.json`: 도메인/원본 제안, 현재 복귀 기준 및 설치 버전/해시.
- `bookmembers-cloudflared.service`: 부팅 자동 시작, 장애 재시작, 토큰을 systemd LoadCredential 및 --token-file로 전달. 토큰을 프로세스 명령줄에 넣지 않는다.
- `install-cloudflared.sh`: root/amd64/토큰 root600/기존 설치 없음/공식 패키지 SHA256을 확인한 후 설치하는 초안. Bash 문법 검사 통과, 실행하지 않음.

공식 최신 stable 조회: cloudflared 2026.10.5, 2026-10-27T13:31:37Z 공개.
Ubuntu amd64 deb SHA256 `149d1ec4ac8e58bdbf08a41cc42347da9184d9fb4ef0df6528d75c90a85ac0ed`.
실제 설치 전 제안 파일과 현재 환경을 재확인한다. token-file 기능은 공식 2025.4.0 이상 지원.

## 공식 근거

- hosting.kr 네임서버 변경: https://help.hosting.kr/hc/ko/articles/5075903480857
- Cloudflare DNS 연결: https://developers.cloudflare.com/dns/zone-setups/full-setup/setup/
- 일반 Tunnel: https://developers.cloudflare.com/tunnel/get-started/
- Worker Custom Domain: https://developers.cloudflare.com/workers/configuration/routing/custom-domains/
- 토큰 파일/서비스 옵션: https://developers.cloudflare.com/tunnel/reference/run-parameters/
- 공식 패키지: https://github.com/cloudflare/cloudflared/releases/tag/2026.10.5
