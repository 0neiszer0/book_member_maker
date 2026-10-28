# 응답 속도 진단과 1차 최적화

2026-10-28 13:32~13:41 KST. 운영 코드는 bda8a82, Worker 버전은
9081c2bc-b183-4bb1-a6fc-4f5de9616ba1. 아래 최적화는 로컬 준비본이며 공개 배포 전이다.

## 실측 결과

Windows 미니 PC에서 공개 Worker를 읽고, Ubuntu 내부에서 같은 비로그인 GET을 읽었다.
경로별 순차 3회, 응답 전체 수신 시간의 중앙값이다. 병렬 부하 시험이나 브라우저 전체 로딩
시간 측정이 아니다. 본문·쿠키·회원 정보는 결과 파일에 저장하지 않았다.

| 대상 | Ubuntu loopback | 공개 Worker |
|---|---:|---:|
| 홈 / | 4ms | 2,683ms |
| 로그인 /login | 3ms | 4,763ms |
| DB 확인 /keep-alive | 66ms | 1,253ms |
| 지금 참여 /now | 279ms | 2,328ms |
| 추천 목록 /books/suggestions | 35ms | 1,317ms |
| /static/tailwind.css | 3ms | 1,280ms |
| /static/app_ui.css | 3ms | 1,366ms |

첫 연결과 반복 연결의 편차가 크다. 홈 공개 응답은 1.45~5.60초였으며 이 짧은 표본을
모든 사용자·시간대의 보장값이나 p95로 해석하지 않는다. 공개 응답의 Cloudflare edge는 HKG였다.
curl 1회 분해: DNS 28ms, TCP 연결 누적 91ms, TLS 누적333ms, 첫 바이트1,268ms, 전체2,181ms.

Funnel 자체는 비밀키 없는 작은 403 응답만 비교했다. 원본 키를 전송하거나 인증을 우회하지 않았다.

- 내부 Tailscale 경로: 최초98ms, 이후6ms/6ms.
- 공개 릴레이1: 최초3,666ms, 이후978ms/1,109ms.
- 공개 릴레이2: 최초3,437ms, 이후879ms/1,156ms.
- 공개 IP는 Google DNS-over-HTTPS로 조회했고 TLS/SNI 검증을 유지했다. 개인 MagicDNS 경로를
  공개 Funnel 성능으로 잘못 측정하지 않도록 했다. Worker가 쓰는 릴레이와 완전히 같은 경로라고 단정하지 않는다.

서버 load average 0.00, app MemoryCurrent 약141MiB, guest available454MiB, swap0,
NRestarts0. Tailscale netcheck UDP=true, 가장 가까운 DERP Tokyo40.6ms.
이 표본에서 CPU·RAM 증설이나 Supabase 이전을 우선할 근거는 없다. 공개 Funnel 경로의 지연과
모든 파일에 no-store를 붙인 초기 Worker 설정이 확인된 개선 대상이다.
Funnel 대역폭 제한은 공식 문서에 있지만 현재 지연이 그 제한에 걸린 결과인지는 확인하지 못했다.

로그인한 대시보드는 이번 측정에 포함하지 않았다. 소스상 여러 DB 요청을 순차 실행하지만
그 비용은 별도로 계측해야 한다. 인증 검사를 캐시하거나 사용자 세션을 위조해서 측정하지 않는다.

## 로컬에 준비한 변경

- Cloudflare Workers Static Assets binding으로 /static의 기존 CSS·JS·공유 PNG만 제공.
- asset-release.json이 운영 VM과 같은 bda8a82 전체 SHA를 고정한다. prepare-assets.mjs는 해당
  Git 커밋에서 허용된 18개(1,167,009bytes)만 추출한다. 미추적 파일·다른 UI 세션의 변경·비밀·HTML은 제외.
- 정적 요청의 로그인 쿠키·Authorization·원본 비밀은 ASSETS에 전달하지 않는다.
- 정적 응답은 public,max-age=0,must-revalidate와 ETag 재검증. 고정 URL의 오래된 CSS/JS를
  장기간 브라우저에 남기지 않는다. 없는 파일은 기존 원본으로 전달한다.
- HTML·API·OAuth·SSE·업로드는 기존 프록시와 no-store 유지. 원본 비밀 검증·쿠키·리다이렉트 보존.
- 따라서 정적 파일의 Funnel 왕복을 제거하지만 동적 페이지의 기본 지연까지 해결하지는 않는다.

검증: Worker 회귀/보안 경계 테스트6개 통과, Wrangler4.153.0 deploy --dry-run 통과.
127.0.0.1:8793 로컬 런타임에서 CSS/JS/PNG SHA256 일치, ETag304, HEAD200 빈본문,
동적 경로의 원본 전달/no-store 등6항목 통과. 합성 키와 upstream.invalid만 사용했고 개발 서버 종료.
실제 공개 CDN 개선 수치는 배포 승인 후에만 측정할 수 있다.

## 배포·재개

사용자가 '아직 배포하지 말고 구조부터 논의'를 선택했고 UI 교체도 예정되어 있어 공개 배포는 보류.
이 준비본을 자동 배포하지 않는다. 향후 이 방식을 선택하고 새 승인을 받은 경우에만 아래를 수행한다.
서버 재시작·DB 변경·카카오 변경·주소 변경·GitHub main push·Render 배포는 이 정적 파일 변경에 필요 없다.

1. 배포 직전 VM 실제 커밋과 asset-release.json 일치 재확인. UI가 배포됐으면 과거 파일을 올리지 말고 재검토.
2. 정적 파일의 내용 hash·ETag·쿠키 없음과 캐시 헤더 확인. 같은 CSS를 소량 재측정.
3. 기존 work/verify-worker-new-url.py의 공개8항목, 로그인 시작·no-store 확인.
4. 새 버전·실측 결과 기록. 공개 배포에 회귀가 있으면 바로 직전 보안 버전9081c2bc로 복귀.

UI를 나중에 VM에 배포할 때는 asset-release.json도 같은 릴리스 SHA로 갱신하여 Worker 정적 파일과
서버 템플릿을 맞춰야 한다. 이 동기화가 필요하다는 점을 UI 통합 계획에 포함한다.
잔여 동적 지연은 현재 workers.dev 주소를 유지하는 원본 연결 대체안을 비교한 뒤 결정한다.
네트워크 변경·새 도메인/유료 서비스·터널 설치는 아직 실행하거나 승인받지 않았다.

측정 원본(작업 디렉터리): work/perf-loopback.json, work/perf-worker.json,
work/perf-funnel-network.jsonl, work/perf-local-assets-verification.json.

공식 근거:
- https://developers.cloudflare.com/workers/static-assets/binding/
- https://developers.cloudflare.com/workers/static-assets/headers/
- https://tailscale.com/docs/features/tailscale-funnel
