# 자동 외부 백업 적용안 — 2026-10-29

현재 실제 회원 백업의 외부 업로드·재다운로드·복원은 완료했다. 자동 연결·스케줄러는 아직 미설치다.

## Google 연결

개인 Google 계정의 기존 `rclone` 프로젝트는 Testing이며 게시에 필요한 브랜딩이 미완료다. 기존 개인용 클라이언트의 권한과 인증 상태를 바꾸지 않고 `bookmembers-backup` 전용 프로젝트를 만든다. Drive API와 데스크톱 OAuth 클라이언트만 사용하고 결제 계정은 연결하지 않는다.

요청할 범위는 `https://www.googleapis.com/auth/drive.file` 한 개다. 해당 앱이 만든 파일만 다룬다. Testing 토큰의 7일 만료를 피하도록 Production 상태를 사용하지만 접근 철회/계정 보안 정책 등으로 인증이 만료될 수 있어 실패 알림을 둔다. 실제 동의 화면이 이 범위보다 넓으면 중단한다.

새 앱으로 비공개 자동 백업 폴더를 생성하고 그 ID를 rclone root_folder_id에 고정한다. 이전 수동 백업 폴더는 다른 앱이 만든 것이므로 그대로 보존한다. 비밀값은 root 0600 설정에 저장하고 로그나 인수인계 Markdown에 넣지 않는다. 복구 개인키는 VM에 저장하지 않는다.

## 일정과 보관

- 매일 한국 시각 03:15 + 최대10분 분산, PC가 꺼져 있으면 다음 기동 후 실행.
- 실제 DB/Storage/위키/서버 설정을 age 암호화한 뒤 업로드·재다운로드 대조.
- 완료 마커가 있는 새 자동 백업만 일간14개·주간8개 보관(겹치는 사본은 한 개). 이전 수동 백업과 불완전 사본은 자동 삭제하지 않는다.
- 오래된 외부 사본은 Drive 휴지통으로만 이동하며 휴지통 비우기는 하지 않는다. 대응하는 로컬 오래된 암호문만 정리한다.
- backup 코드 별도 경로 `/opt/bookmembers-backup`에서 실행하므로 앱 버전과 독립적으로 유지한다.
- 서버의 `/var/lib/bookmembers-health/backup.json`에는 상태·시각만 기록한다. 실패 또는 36시간 경과 시 전체 활성 관리자에게 기존 사이트 알림/푸시 체계로 전달하며 성공하면 자동 해결한다. 반복 실패는 같은 알림을 유지한다.
- 서버 자체가 꺼져 있으면 이 서버에서 알림을 보낼 수 없다. 별도 외부 장애 감시는 이번 설치 범위가 아니다.

## 승인 후 적용

Ubuntu 공식 저장소의 rclone 1개만 추가한다. 전용 OAuth 연결 후 수동 자동백업 실행 1회가 성공해야 타이머를 켠다. 알림 코드 두 파일과 상태 파일 경로만 반영하며 DB 연결/전체 웹앱 배포는 별도 단계다. 원본/복원 검증은 이미 완료한 검사를 반복하지 않는다.

공식 근거: [Google OAuth 만료](https://developers.google.com/identity/protocols/oauth2#expiration), [Drive 최소 권한](https://developers.google.com/workspace/drive/api/guides/api-specific-auth), [rclone SSH 인증](https://rclone.org/remote_setup/), [Drive 삭제는 기본 휴지통](https://rclone.org/drive/#deleting-files).
