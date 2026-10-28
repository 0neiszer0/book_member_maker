# 새 UI 정적 CDN 릴리스

작성: 2026-10-28 KST. 상태: 로컬 검증 완료, **공개 배포·VM 활성화 승인 대기**.

## 변경 범위

- 코드 커밋: `8e290f7bf054035dfdd6f8e520c62f59317f489c` (이 작업의 로컬 브랜치만).
- 정적 파일 기준: 현재 VM UI `f9468246927e1e04b7c71eaa9ab9d8049ca69053`.
- 공개 CSS·JS·WOFF2·폰트 라이선스·공유 이미지 44개, 총 5,775,211 bytes.
- 버전 해시: `14cb36698215c90434d88446d946e2e2eb48b03cc6837025ec89fb599e253c50`.
- URL: `/static/_v/<위 해시>/<파일명>`. CSS의 상대 폰트 경로도 같은 버전 디렉터리 안에 유지한다.
- Cloudflare Static Assets가 파일을 직접 제공한다. `run_worker_first=false`; 정상 정적 요청은 Worker 스크립트 및 Funnel을 거치지 않는다.
- 정적 응답: `Cache-Control: public, max-age=31536000, immutable`, ETag/304, 보안 헤더. Set-Cookie/원본 인증 헤더 없음.
- Flask는 시작할 때 manifest와 원본·버전 파일 해시를 확인하고 `url_for('static')`에 버전을 넣는다. 없거나 손상되면 기존 URL로 복귀한다.
- HTML·API·로그인·업로드·애플리케이션 POST는 기존 보호된 no-store 프록시다. 미등록 버전은 실제 원본 파일로 전달하며 현재 버전으로 바꿔치기하지 않는다.
- Static Assets가 관리하는 **이미 존재하는 공개 파일 URL에 POST하면 플랫폼이 405로 거절**한다. 이 플랫폼 응답에도 경로별 _headers 캐시 헤더가 붙는다. 앱 POST 경로는 여기에 해당하지 않는다. 이 동작을 숨기거나 모든 오류가 no-store라고 일반화하지 않는다.
- UI 파일 내용·도메인·카카오 설정·DB·Render 변경 없음. GitHub main에 push하지 않는다.

## 검증

- 같은 Git 소스로 반복 빌드: 동일 해시/44개/바이트 수.
- 실제 44개 원본 및 버전 파일의 SHA256 일치 확인.
- Python 33개: 새 manifest/복귀 검사 5개와 기존 보안·화면·LMS 경로 검사. 모두 통과.
- Worker 프록시 검사 4개: 스트림, 쿠키, OAuth 리다이렉트, 스푸핑 헤더 제거, no-store, 실패 처리. 모두 통과.
- Wrangler 실제 로컬 HTTP + 합성 화면 56항목 통과: 44개 파일 바이트/헤더, HEAD, ETag 304, 동적 GET/POST, 누락 버전, 공개 자산 POST 거절, 화면 3곳의 버전 URL/존재 파일.
- VM 파일 설치 도구를 임시 폴더에서 두 번 실행해 신규 설치 및 동일 파일 재실행 통과. 배포 Bash 문법 검사 통과. 운영 VM에는 실행하지 않음.
- Wrangler 4.153.0 dry-run 성공. **공개 배포는 실행하지 않음**.
- 실제 브라우저 재방문의 메모리/디스크 캐시 사용과 운영 체감 속도는 배포 후 확인 항목이다. 로컬 측정만으로 운영 개선 수치를 단정하지 않는다.
- 초기 Windows sandbox의 Temp/loopback/metrics 경로 접근 오류는 작업 디렉터리 Temp 및 승인된 로컬 실행 권한으로 해결. 코드 실패와 구별한다.

## Claude 검토

실제 Claude CLI의 `claude-opus-5-5`, effort high로 독립 검토 완료.
정적 CDN 범위에 동의. 공개 경로 지연이 유력하지만 특정 relay/스로틀링 원인은 입증되지 않았다고 평가.
버전 파일 보존, manifest 불일치 시 기존 URL 복귀, 상대 폰트 경로, 공개 파일만 추출하는 방식을 반영했다.
동적 HTML·DB 지연은 남는다. 상세: `CLAUDE_CDN_ADVICE.md`.

## 승인 후 실행 순서

1. VM HEAD가 f946824이고 clean/서비스 active인지 재확인. 현재 Worker 버전은 `9081c2bc-b183-4bb1-a6fc-4f5de9616ba1` (조회 확인).
2. 로컬 `infra/worker/wrangler.jsonc`로 Worker www에 배포. UPSTREAM 기존 Funnel, 기존 비밀키 유지. 새 정적 URL의 GET/HEAD·바이트·캐시 헤더를 먼저 확인.
3. 작업 디렉터리의 `cdn-release.bundle`, `cdn-server-assets.zip`, `install-cdn-assets.py`, `deploy-cdn-app.sh`를 VM 전용 staging 디렉터리로 전송. `cdn-release-checksums.json`과 SHA256 일치 확인.
4. `sudo bash <stage>/deploy-cdn-app.sh <stage>`로 앱 helper 활성화. 현재 HEAD·clean·건강·변경 범위를 확인하고, 잠시 서비스 정지 → 코드 교체 → 검증된 44개 파일/manifest 설치 → 시작. 실패하면 앱 f946824로 복귀.
5. 공개 HTML이 버전 URL을 쓰는지, CSS·JS·폰트·공유 이미지, ETag, 비공개 경로 no-store, 로그인 시작, DB health, 원본 무인증403을 GET/HEAD로 확인. 실제 로그인/쓰기 자동 실행 없음.
6. 공개 회귀면 앱을 f946824로 먼저 복귀하고 필요 시 Worker를 위 이전 버전으로 롤백. 새 `_v` 파일은 남겨 이전 HTML의 참조가 실제 파일로 계속 해석되게 한다. 비밀값/DB 복구는 필요 없다.
7. 결과·Worker 버전·측정·남은 항목을 이 문서와 MINIPC_DEPLOY_STATUS.md/outputs에 갱신.

## 다음 UI 변경 및 롤백

- 현재 UI 파일이 바뀌면 `asset-release.json`의 revision을 새 정확한 커밋으로 갱신하고 retainedRevisions에 직전 UI 커밋을 둔다.
- builder는 오염된 staging 및 같은 해시의 다른 바이트를 거절한다. 무조건 삭제하거나 덮어쓰지 않는다.
- VM `static/_v`와 manifest는 Git ignored. git clean으로 제거하지 않는다. 이전 버전 보관은 기존 열린 화면·Worker 롤백을 위한 것.
- 앱 f946824로 checkout하면 helper가 없어 기존 URL로 돌아간다. manifest가 남아도 이전 앱은 읽지 않는다. 이전 커밋의 .gitignore에는 이 산출물이 없어 untracked로 보일 수 있다.
- 정적 파일 세트 전체의 해시라 CSS만 바뀌어도 폰트 URL이 바뀐다. 현재 범위의 단순성/정합성을 위한 선택이며 글꼴 서브셋이나 UI 변경은 하지 않았다.
- 정적 배포는 무료/무제한 정적 요청 범위이며 동적 Worker의 기존 요청 한도는 그대로다. 공식 문서: https://developers.cloudflare.com/workers/static-assets/billing-and-limitations/

