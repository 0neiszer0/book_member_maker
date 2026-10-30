# 이전 Render 주소 안내 전용

현재 책반우 사이트는 https://knu-read.xyz 에서 미니 PC로 운영한다.
이 디렉터리는 기존 book-member-maker.onrender.com을 방문한 사람에게 공식 주소를 안내하고3초 후 이동시킨다. DB·Flask·카카오 SDK·알림·백업 코드나 패키지가 없고 환경 비밀값을 읽지 않는다.

- GET/HEAD 읽기 링크는 고정된 새 사이트의 같은 경로로 이동한다. 공유 링크 query는 보존한다.
- 로그인/로그아웃 링크는 새 /login으로 보내며 과거 OAuth code/state를 전달하지 않는다.
- POST/PUT/PATCH/DELETE는410안내를 반환한다. 원래 요청 본문을 새 서버로 보내지 않는다.
- /healthz와 과거 /keep-alive는DB조회 없는200상태 확인 경로다.
- 요청 URL·토큰·방문자 주소를 로그로 남기지 않고 외부 자산을 요청하지 않는다.

이 폴더만 포함하는 독립적인 `render/legacy-redirect` 브랜치를 만들어 기존 Render 서비스에 연결한다. Render자동배포는Off로 유지한다. main은 미니 PC 운영 코드 보관용이며 Render는main을 추적하지 않는다. 기존 Render무료웹서비스를 사용하므로 유휴 후 첫 방문은 시작 대기가 있을 수 있다.

배포 전 기존서비스의branch/plan/autoDeploy/suspended를 확인한다. 무료plan유지·별도브랜치·명시적수동배포를 확인한 뒤 사용자 승인 시에만 기존서비스를 재개한다. 원래 Flask 앱을 다시 실행하지 않는다.
