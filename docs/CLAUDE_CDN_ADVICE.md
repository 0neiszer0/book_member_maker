# Claude의 새 UI CDN 검토

2026-10-28. 실제 로컬 Claude CLI 2.1.293, 모델 `claude-opus-5-5`, effort `high`.
도구·MCP·Chrome·파일 접근을 비활성화한 단일 자문. 비밀값/회원 데이터 없이 측정 수치와 설계만 전달.
정상 종료, 모델 응답의 canonicalModel 일치 확인. 원본 응답: 작업 폴더 `work/architecture-review/claude-cdn-review-result.json`.

- 루프백은 빠르고 공개 경로는 가변적으로 느리다는 진단에 중~강 근거가 있다고 평가했다.
- 표본이 작으므로 relay 선택·핸드셰이크·스로틀링을 특정 원인으로 단정하지 말라고 했다.
- 공개 정적 파일만 Static Assets로 옮기는 범위는 타당하다고 평가했다. 동적 HTML/인증 대시보드/DB 지연은 별도다.
- 세트 해시로 CSS와 상대 폰트 경로를 묶고, 실제 이전 파일도 보존하라는 조언을 반영했다.
- manifest 누락/손상 시 기존 URL로 복귀, 원본과 manifest 검증, 같은 버전의 다른 바이트 덮어쓰기 거절을 반영했다.
- 파일 allowlist, private 데이터·source map 제외, scoped _headers, 쿠키 없음, 최소 검사 범위를 반영했다.

검토자의 주장을 그대로 사실로 옮기지는 않았다. 원문은 no-store로 엣지 캐시까지 완전히 사용되지 않는다고 단정했지만, 기존 측정에 CF-Cache-Status REVALIDATED/EXPIRED가 있어 이 단정은 채택하지 않았다. 확실한 사실은 no-store로 브라우저 재사용을 막고 신선한 HIT를 확인하지 못했다는 것이다. workers.dev의 Cache API 제한에 대한 원문의 일반화도 이번 구현 근거로 쓰지 않았다.

원본 fallback에 immutable을 추가하라는 제안은 채택하지 않았다. 기존 보호 프록시의 no-store를 유지하고 Cloudflare에 실제 등록된 공개 파일에만 캐시를 적용했다. Static Assets의 존재 파일에 POST하면 플랫폼이 405 및 경로별 캐시 헤더로 답하는 동작은 로컬에서 확인했으며, 실제 앱 POST는 기존 no-store 경로다.
