# UI 변경을 고려한 서버 구조 검토

2026-10-28 KST. 논의용 설계이며 변경 승인이나 적용 기록이 아니다.
후속 비용 질의: 사용자가 베타 종료 후 유료화 가능성을 우려했다. 공식 가격 페이지는 베타 기간
VPC 무료와 기본 Workers 요금 적용만 명시하며 종료 후 가격·무료 제공 범위는 안내하지 않는다.
B는 영구 무료 운영안이 아니다. 장기 비용 예측을 우선하면 B 평가 권고를 조건부로 보고,
현재 구조의 제한적 최적화 또는 도메인 비용을 고려한 일반 Tunnel을 비교한다. 사용자 선택은 아직 없다.
사용자가 1차 CDN 최적화 배포를 명시 보류했고, UI 변경 예정 및 Claude Opus5.5 High 자문을 요청했다.
실제 자문 완료: Claude Code2.1.293, claude-opus-5-5, effort high, tools/MCP 비활성.
원문은 CLAUDE_ARCHITECTURE_ADVICE.md. 제공된 자료에 대한 의견이며 Claude가 직접 실측한 것은 아니다.

## 권고

현 Windows→Hyper-V→Ubuntu→Flask와 Supabase는 유지한다. 먼저 원본 공개 경로의 지연을 줄인다.
현재 무료 주소 www.knu-read.workers.dev를 유지하는 조건에서는 **B안을 비교 검증하는 것**을 권고한다.
실제 B안이 빠르고 로그인·SSE에 문제가 없음을 확인하기 전 운영 전환을 확정하지 않는다.
연간 도메인 유지가 가능하고 베타 의존을 줄이는 것이 우선이면 C안이 대안이다.

| 안 | 구성 | 장점 | 제약 / 판단 |
|---|---|---|---|
| A | 현재 Worker→Funnel + 정적 CDN | 준비본 존재, 정적 요청의 Funnel 왕복 제거 | 동적 지연은 남고 UI/자산 배포 동기화가 추가됨. 지금은 보류 |
| B | 기존 Worker→단일 VPC Service→비공개 cloudflared→Flask | 기존 주소·카카오 콜백·포트 비공개 유지, 도메인 구매 불필요 | Workers VPC 베타. 향후 가격/API 변경 가능, 실제 성능·호환성 미검증. 우선 평가 후보 |
| C | 일반 Cloudflare Tunnel + 동아리 소유 도메인 | 베타 VPC 의존을 줄이고 계정/호스팅 이동 시 주소 이식에 유리 | 보유 도메인 또는 신규 등록·갱신 관리 필요. Worker 유지 여부는 별도 선택 |

일반 공개 Tunnel과 B의 사설 VPC 연결을 혼동하지 않는다. 전자는 Cloudflare에 등록한 도메인이
필요하지만 B는 원본 공개 도메인 없이 Worker binding으로 localhost의 특정 포트를 연결할 수 있다.
2026-10-28 공식 문서상 VPC는 베타 기간 모든 Workers 플랜에서 추가 비용 없이 제공되며
기존 Workers 사용량 제한이 적용된다. 영구 무료나 성능 보장은 아니다.
Quick Tunnel은 일시적 주소·운영 보장 없음·SSE 미지원으로 후보에서 제외한다.

## B안을 택할 경우의 경계

- 브라우저→기존 공개 Worker→단일 VPC Service→Ubuntu cloudflared→127.0.0.1:5000.
- 전체 사설 네트워크를 연결하는 VPC Network binding은 필요 없다. 앱 하나의 host/port로 제한.
- Tailscale은 SSH/서버 관리용으로 유지한다. Funnel은 비교·복귀 기간에만 현재 설정을 보존하고
  추후 중지는 별도 승인받는다. 공개 Worker의 직전 버전으로 수동 복귀 가능하도록 유지.
- 원본 인증키, 전달 헤더 정리, 쿠키, CSRF, HTML/API no-store, 스트리밍은 유지한다.
- 자동 POST 재시도·원본 이중 전송·Render 자동 우회는 추가하지 않는다. 기존 Render는 Worker용
  OAuth 대체 환경이 완성되지 않았으므로 완전한 무중단 대체 서버로 취급하지 않는다.
- VPC는 cloudflared와 outbound QUIC UDP7844가 필요하다. 현재 Tailscale UDP 성공은
  해당 포트와 VPC의 성공 증거가 아니다. 권한 부여·패키지 설치·서비스 추가는 아직 미승인/미실행.

## UI 릴리스와 정적 파일

86eeda7의 CDN 준비본은 배포하지 않는다. 향후 이를 그대로 배포하면 VM 템플릿과 Worker 자산이
다른 릴리스가 될 수 있다. max-age=0도 올바르지 않은 릴리스 파일을 재검증하면 문제를 해결하지 못한다.

최소 설계는 저장소 한 곳에서 HTML·CSS·JS를 같은 릴리스로 만들고, 변경되는 정적 파일에는
내용 해시가 들어간 실제 파일명과 manifest를 사용하는 것이다. 해시만 쿼리에 붙이고 현재 파일로
무조건 매핑하는 방식은 오래된 HTML에 정확한 이전 파일을 보장하지 못한다.
직전 릴리스 자산은 복귀와 열린 탭을 위해 보존한다. immutable 캐시는 이 불변 파일에만 적용한다.
동적 HTML·인증/API는 no-store 유지. 별도 프런트 프레임워크·대형 CI 시스템은 도입할 이유가 없다.

이 변경은 예정된 UI 릴리스와 통합해 검토한다. 다른 UI 세션에 메시지를 보내거나 파일을 수정하지 않았다.
B/C 평가 뒤 정적 전송도 충분히 빨라지면 CDN 별도 배포는 생략할 수 있다. 필요할 때 같은 manifest로
CDN을 생성하고 자산 준비 후 템플릿을 전환하여 배포 순서를 명확히 한다.

## 검증은 짧고 되돌릴 수 있게

지금은 설계 검토만 수행했다. 실제 구축 직전 별도 범위 승인 후:

1. 기존 사용자 경로를 유지한 채 접근 제한된 비교 경로를 준비한다. 기존/후보 경로를 같은 시간대에
   번갈아 5~10쌍 정도 GET 측정하고, 최초 연결과 반복 연결을 구분한다. 편차가 크면 필요한 만큼만 추가.
   이 표본으로 p90/p95 보장을 주장하지 않는다. Claude의 '30회 이상' 제안은 최소 검증 선호에 맞춰 축소.
2. 원본 보호·다중 쿠키·수동 리다이렉트·SSE·업로드 스트리밍은 합성 데이터와 저장하지 않는 격리
   진단 대상으로 확인한다. 실제 출석/회원 POST를 복제하거나 운영 Storage에 테스트 파일을 쓰지 않는다.
3. 승인을 받은 공개 전환 후 본인 카카오 로그인으로 확인한다. 별도 카카오 콜백 추가를 당연한 전제로
   하지 않는다. 회귀 시 직전 Worker 버전으로 복귀한다. 외부 모바일 연결에서도 짧게 비교한다.
4. 운영 구성이 정해진 뒤 Windows→VM→앱→터널 자동 복구를 승인된 재부팅으로 확인한다.

현재 수치는 주요 병목이 공개 경로에 있다는 근거다. 특정 릴레이 위치, 대역폭 제한 발동,
패킷 손실, 첫 요청 핸드셰이크 원인까지 확정한 것은 아니다. 인증된 관리자/회원 화면의 DB 쿼리
지연은 별도 미측정이다. 서버 증설·Gunicorn 증가·로컬 DB 이전·프런트 재작성은 우선 처방으로 채택하지 않는다.

## 이식성·지속 운영

- 서비스 정의·비밀 없는 설정 템플릿·릴리스 SHA는 Git, 실제 비밀은 별도 제한된 환경파일/Secret.
- PC 이전 시 새 Ubuntu와 연결 커넥터를 준비하고 외부 진입점만 전환한다. Supabase 데이터 이전은
  이 작업과 분리한다. 같은 앱/DB를 쓰는 이중 호스트에서 예약 작업을 중복 실행하지 않는다.
- workers.dev는 현재 Cloudflare 계정에 종속된다. PC 이전에는 편하지만 계정 자체를 바꾸면 이름의
  이식성이 도메인보다 낮다. 장기적으로 동아리 소유 도메인/조직별 관리자 권한을 고려하되 지금 설정하지 않는다.
- 공용 Gmail 로그인·계정 이전·인수인계 묶음은 생성하지 않는다.
- 자동 복구 검증, BIOS 정전 복구, DB/Storage 암호화 외부 백업과 격리 복원은 여전히 남은 필수 운영 과제다.
  호스트 백업만으로 Supabase 데이터가 보호되는 것은 아니다.

## 현재 결정 상태

- 운영 Worker 버전9081c2bc 및 VM 보안 버전bda8a82 유지.
- A 배포 보류. B 평가를 권고하지만 아직 사용자 선택/구축 승인 없음. C 도메인 구매 승인 없음.
- 다음 설계 선택은 무료 주소·베타 평가를 우선할지, 동아리 도메인·일반 Tunnel을 우선할지다.

공식 근거(2026-10-28 확인):
- https://developers.cloudflare.com/workers-vpc/get-started/
- https://developers.cloudflare.com/workers-vpc/configuration/vpc-services/
- https://developers.cloudflare.com/workers-vpc/configuration/tunnel/
- https://developers.cloudflare.com/workers-vpc/platform/pricing/
- https://developers.cloudflare.com/workers-vpc/platform/limits/
- https://developers.cloudflare.com/tunnel/get-started/
- https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/
- https://developers.cloudflare.com/workers/static-assets/headers/
