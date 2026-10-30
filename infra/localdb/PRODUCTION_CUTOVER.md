# 미니 PC 운영 DB 전환 완료

2026-10-30 KST. 사용자의 “운영 DB 최종 이전·서비스 재시작 승인”에 따라 실행했다.

## 현재 운영

- 회원 사이트: https://knu-read.xyz → 기존 Worker/CDN → Cloudflare Tunnel → Ubuntu 앱.
- 회원·학기·출석·게시글·알림 DB와 Storage는 미니 PC의 PostgreSQL/PostgREST/Storage/Envoy에서 운영한다. 위키는 기존 로컬 SQLite를 그대로 사용한다.
- API는 VM 내부127.0.0.1:55480만 게시하며 DB 포트는 게시하지 않는다. 회원용 도메인·카카오·Flask 세션 키와 UI는 변경하지 않았다.
- Render의 회원 앱은 종료했다. 이후 사용자 승인으로 `render/legacy-redirect` 브랜치의 안내 전용 코드 `070c21e`만 재개했고 자동 배포는 Off다. Supabase 프로젝트는 삭제하지 않고 전환 전 원본으로 보존한다. 새 기록은 로컬 DB에 쌓이므로 Supabase를 현재 데이터로 간주하지 않는다.
- 배포 코드는 기존 앱9459cfc에 검토된 로컬 파일 URL 코드(app.py/boards.py/engagement.py/storage_media.py)를 추가한 구성이다. 백업 실패 알림 overlay도 유지했다. 이후 사용자 승인으로 모든 소스를 GitHub main에 반영했지만, 이것이 미니 PC 재배포를 의미하지는 않는다.

## 최종 이전 결과

- 10:16:52 쓰기 중지 → 최신 원본 백업 암호화·Drive 업로드 대조 → 새 전용 저장 공간 복원 → 10:22:56 앱 재개. 중단 약6분4초.
- 72개 테이블 전체의 행 수·소유자·테이블/함수 권한·시퀀스·제약과 동결 원본 비교가 일치했다. RLS72개, 제약320개.
- Storage 버킷4개와 공개/비공개 속성을 복원했다. 원본 객체0개. 기존 합성 업로드/서명 시험은 반복하지 않았다.
- 위키 백업 무결성 정상, 문서14개/이력32개. 운영 위키 DB 자체는 덮어쓰지 않았다.
- 익명 inbox 조회 차단, 서버 API 회원 조회 성공. 기존 로그인 세션의 실제 대시보드에서 현재/과거 학기·할 일·출석·알림·동아리방 조회 확인.
- 공개 로그인200, /keep-alive 정상, 카카오 로그인 시작302, 원본 비밀키 없는 직접 접근403. 실제 재로그인 완료나 가짜 회원/푸시는 시험하지 않았다.

## 백업과 자동 시작

- Google 백업 앱 Production 및 drive.file 전용 비공개 폴더를 사용한다. Testing의7일 제한에 의존하지 않는다.
- 새 로컬 DB와 database.env/앱 설정/위키를 포함한 암호화 외부 백업이10:21:49에 성공했다. 실제 업로드·재다운로드 대조 완료.
- 매일03:15 이후 최대10분 분산 실행, Persistent 타이머. 일별14개/주별8개 보존 및 기존 관리자 실패 알림 연동.
- Docker, bookmembers-db, 앱, 위키, Tunnel 자동 시작 enabled 확인. 앱·알림은 DB 서비스 이후에 API 준비를 기다린다. 백업 서비스도 DB 이후 실행하도록 연결했다.
- 알림·위키 백업·외부 백업 타이머 모두 active. 임시 복원 TAR/위키 사본은 제거했다. 복구 개인키는 VM에 저장하지 않았다.

## 초기화 문제와 해결

처음 생성된 역할 파일이0600이어서 PostgreSQL의 비특권 사용자가 읽지 못했고 공식 초기화가 중간에 멈췄다. 비밀값 없는 마운트 템플릿을0644로 수정(677e51f)한 뒤, 불완전한 볼륨을 보존하고 새로운 운영 볼륨을 초기화했다. 임의의 추가 권한 부여로 우회하지 않았다. 운영 볼륨 이름은 bookmembers-db_production-database / production-config / production-files다. 이전 불완전 볼륨은 현재 컨테이너에 연결되지 않는다.

앱 시작 파일의 부모 디렉터리도0755로 수정했다. DB 서비스와 공개 앱이 정상 시작하고 인증된 화면 조회가 성공한 이후에 완료로 기록했다.

## 재개·복구 시 주의

- 운영 구성은 /etc/bookmembers-db, 비밀값은 database.env(root0600). 앱 설정은 /etc/book_member_maker/app.env(root0600). 비밀값을 출력하거나 Git에 넣지 않는다.
- 현재 Docker compose 설정의 실제 볼륨 이름을 확인하고 사용한다. 기본 템플릿을 무심코 다시 설치해 다른 빈 볼륨을 연결하지 않는다.
- 전환 후에는 새 로컬 기록이 우선이다. 장애가 나도 예전 Supabase 연결로 자동 복귀하지 않는다. 최신 백업/로컬 DB를 보존하고 수정한다.
- 이 PC의 작업 폴더 outputs/localdb-cutover-result-20261030.json, operations-improvements-state.json과 VM /var/lib/bookmembers-cutover-20261030/COMPLETE.json에 상세 증거가 있다. 이전 설정과 암호화 원본 백업도 보존했다.

## Windows 전체 재부팅 검증 완료

2026-10-30 사용자 진행 승인 후10:36:38에 강제 앱 종료 옵션 없이 Windows 전체 재부팅을 요청했다. Windows 새 부팅 시각은10:37:18, VM boot_id도 이전과 달라졌다. 앱은10:38:50에 자동 시작했다(Windows 부팅 후 약92초). 재연결 뒤 어떤 서비스도 수동으로 시작하거나 재시작하지 않은 상태에서 확인했다.

- DB/API·앱·위키·Tunnel과 알림/외부 백업/위키 백업 타이머 모두active. 앱 재시도0회.
- PostgreSQL·Storage 컨테이너healthy, 실패한 systemd 유닛0개.
- 공개 /login200, /keep-alive200 및 DBalive. 알림 작업은10:50:59에success로 종료했다.
- 다음 외부 백업은10월31일03:19:42 KST로 예약돼 있으며, 기존 최근 백업 성공 상태를 유지한다. 재부팅 검증을 위해 불필요하게 백업/복원을 반복하지 않았다.
- 근거: 작업 폴더 outputs/post-reboot-localdb-20261030.json. 기존 Windows 자동 로그인이 있어 로그인 이전 복구까지 별도로 입증한 것은 아니다. 정전 후 PC 자체가 자동으로 켜지는지는 BIOS 설정의 별도 확인이 필요하다.
