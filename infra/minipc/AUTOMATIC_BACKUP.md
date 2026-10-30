# 자동 외부 백업 적용안 — 2026-10-30

**2026-10-30 설치·인증·첫 자동 백업·타이머·실패 알림 연결 완료.** Google 앱은 Production이며 drive.file 범위로 전용 비공개 폴더만 사용한다. 첫 자동 백업은 09:58 KST에 업로드·재다운로드 대조까지 성공했다. 운영 DB는 계속 Supabase다.

## 현재 운영 상태

- 매일 03:15 KST 이후 최대10분 분산 실행, 다음 관측 실행은 2026-10-31 03:18:12 KST. `bookmembers-backup.timer` enabled.
- 알림 서비스에 `BACKUP_STATUS_FILE`과 검증한 상태 조회 코드 연결 완료. 정상 상태에서는 알림을 만들지 않으며 시험 푸시도 보내지 않았다. 웹앱 서비스 재시작은 없었다.
- 새 자동 백업 폴더는 개인 계정 소유자 한 명만 접근하며 rclone root_folder_id로 고정했다. 이전 수동 백업 폴더는 유지했다. 폴더 ID·계정·실행 ID 등 개별 운영 값은 저장소 밖 상태 기록에 있다.
- Google 안내 페이지 3개와 공개 소유 확인 파일만 Worker에 추가했다. 회원 UI의 파일 digest와 연결 원본은 유지했다. Search Console 소유 확인 및 Google OAuth Production 전환 완료.
- 설치 전/중간 기록은 아래에 남긴다. 현재 재개 시 새 프로젝트·클라이언트·폴더를 만들거나 인증을 다시 시작하지 않는다. 정상 백업을 먼저 확인한다.

## 10월 30일 설치 중간 기록

- Render의 자동 배포를 끄고 서비스를 중지했다. 삭제하지 않았다. 이후 knu-read.xyz 로그인 200, DB alive, 원본 인증키 없는 직접 접속 403을 확인했다.
- 전용 Google Cloud 프로젝트 `bookmembers-backup`과 Desktop 클라이언트 `bookmembers-minipc-backup`을 만들고 Drive API를 활성화했다. Google 사용자 데이터 정책 동의는 사용자에게 별도로 승인받았다.
- 클라이언트 JSON은 Windows DPAPI로 보관하고 다운로드된 평문은 제거했다. 서버 설정은 root 0600이며 `drive.file`만 사용한다. 토큰 발급 전 대기를 취소했으므로 재개 시 새 인증 흐름을 시작한다. 중복 프로젝트·클라이언트를 만들지 않는다.
- Google Audience의 Publish app은 브랜딩 미완료로 비활성이다. 공식 [브랜딩 도움말](https://support.google.com/cloud/answer/15549049)은 외부 Production 앱에 홈페이지·개인정보처리방침·약관 링크를 요구한다. 테스트 상태의 7일 토큰으로 무인 운영이 완성됐다고 간주하지 않는다.
- `infra/worker/backup-info/`에 전용 소개·개인정보처리방침·이용약관 3개를 준비했다. 공개 전에 사용자 승인을 받는다. 승인 후 실제 주소를 Google 브랜딩에 등록하고 필요한 도메인 소유 확인을 진행한다. 기존 사이트의 앱 메뉴나 인증 정책은 바꾸지 않는다.
- 백업 실행 파일은 `/opt/bookmembers-backup/infra/minipc/`, 유닛은 `/etc/systemd/system/bookmembers-backup.{service,timer}`에 있다. 알림 연동 두 파일과 `BACKUP_STATUS_FILE`은 아직 운영에 적용하지 않았다.

## Google 연결

개인 Google 계정의 기존 `rclone` 프로젝트는 Testing이며 게시에 필요한 브랜딩이 미완료다. 기존 개인용 클라이언트의 권한과 인증 상태를 바꾸지 않고 별도 `bookmembers-backup` 프로젝트를 사용한다. Drive API와 데스크톱 OAuth 클라이언트만 사용하고 결제 계정은 연결하지 않는다.

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

## 적용 원칙

Ubuntu 공식 저장소의 rclone 1개를 추가했다. 전용 OAuth 연결 후 수동 자동백업 실행 1회가 성공해야 타이머를 켠다. 알림 코드 두 파일과 상태 파일 경로만 반영하며 DB 연결/전체 웹앱 배포는 별도 단계다. 원본/복원 검증은 이미 완료한 검사를 반복하지 않는다.

공식 근거: [Google OAuth 만료](https://developers.google.com/identity/protocols/oauth2#expiration), [Drive 최소 권한](https://developers.google.com/workspace/drive/api/guides/api-specific-auth), [rclone SSH 인증](https://rclone.org/remote_setup/), [Drive 삭제는 기본 휴지통](https://rclone.org/drive/#deleting-files).
