# 발제문 수정 인증 운영 메모

적용일: 2026-09-01
마이그레이션: `20260901134512_secure_topic_edit_identity.sql`

## 현재 방식

- 로그인 회원: Flask 세션의 `user_id`와 `topic_submissions.member_id`가 소유권이다.
- 비회원 신규 제출: 서버가 32바이트 난수 수정 코드를 한 번 발급한다.
- DB에는 수정 코드 원문이 아니라 `FLASK_SECRET_KEY`를 pepper로 사용한
  HMAC-SHA-256 해시만 저장한다.
- 수정 코드는 URL에 넣지 않으며 현재 브라우저의 localStorage에 자동 저장한다.
- 수정 코드 확인 실패는 같은 요청 출처·이벤트 기준 15분 동안 10회로 제한한다.
  출처 주소는 HMAC fingerprint로만 기록한다.
- 발제문 페이지와 제출/불러오기 API 응답은 `no-store`, `no-referrer`로 처리한다.

## 기존 데이터 전환 결과

- 전체 제출: 86행
- `member_id`로 안전하게 연결: 83행
- 기존 4자리 PIN 호환: 3행
- 미해결 `legacy_member`: 0행
- 신규 강한 수정 코드 적용 행: 배포 시점 0행

기존 PIN 3행은 삭제하거나 임의 변경하지 않는다. 해당 작성자가 기존 PIN으로
수정에 성공하면 즉시 강한 수정 코드를 새로 발급하고 `identity_kind = 'guest'`,
`credential_version = 2`로 전환한다. 이후 평문 PIN은 더 이상 저장하지 않는다.

## 비밀값 회전 주의

현재 수정 코드 HMAC은 별도 브라우저 키를 노출하지 않고 기존 서버의
`FLASK_SECRET_KEY`를 사용한다. 이 값을 회전하면 기존 비회원 수정 코드 3개도
검증되지 않으므로, 회전 전에는 다중 pepper 검증 기간 또는 새 코드 재발급 계획을
먼저 세워야 한다. 로그인 회원 제출에는 영향이 없다.

## 배포와 롤백

배포 순서는 additive DB migration → DB 사후 검증 → 앱 배포이다. 구버전 앱은 새
컬럼을 무시하므로 migration이 먼저 적용되어도 계속 동작한다.

앱 장애 시 이전 Render 커밋으로 되돌린다. 새 컬럼과 `topic_edit_attempts` 테이블은
구버전 앱에 영향을 주지 않으므로 즉시 DROP하지 않는다. DB 정리가 필요하면 앱이
안정된 뒤 별도 마이그레이션으로 수행한다. `pin_code` 제거도 모든 legacy 행 전환을
확인한 뒤 마지막 단계에서만 검토한다.
