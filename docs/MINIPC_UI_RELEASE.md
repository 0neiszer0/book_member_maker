# UI f946824 운영 반영 준비

2026-10-28 KST. 사용자 요청: f946824 UI 적용. 공개 배포 직전 승인 조건 유지.

- 원본: 다른 UI 세션의 로컬 codex/lms-v3-navigation 브랜치.
- 고정 대상: f9468246927e1e04b7c71eaa9ab9d8049ca69053.
- GitHub에는 아직 없는 커밋. 원본 작업 사본을 수정하지 않고 로컬 fetch.
- 기존 보안 bda8a82가 대상의 조상임을 확인. 현재 통합 브랜치에 e88a3f4로 병합.
- 앱·템플릿·정적 파일은 f946824와 동일. 미니 PC 운영 문서는 통합 브랜치에 별도 보존.
- 기존 운영 대비 114파일: LMS 공통 화면, 강의실/공지 맥락, 역할별 탐색,
  출석 표시와 통합 캘린더. DB 마이그레이션·requirements·minipc_security 변경 없음.
- 합성 데이터 Python 관련 테스트 94개 통과. Node 캘린더/예약 검사 및 새 UI JS 구문 통과.
- 변경 공백 검사: 원본 OFL 라이선스 문구의 기존 줄끝 공백 2개만 검출. 원문 유지.
- 로컬 합성 데이터 대시보드 렌더, 강의실 공지 링크의 term_id 유지 브라우저 확인.
  운영 계정/DB를 이용한 POST 테스트는 하지 않음.
- 새 한글 폰트는 약 3.9 MB이며 font-display:swap 사용. 이번 UI 반영은 Funnel 속도
  최적화가 아니며 초기 폰트 전송량이 늘 수 있음. 보류된 CDN을 함께 배포하지 않음.

## 현재 운영 읽기 점검

- Ubuntu /opt/book_member_maker: bda8a82e66ac828dd3bfe1971c37e7e98cca356f, clean/detached.
- bookmembers 서비스 active/enabled. 소스 root 소유, .venv 기존 경로 유지.
- 운영 URL https://www.knu-read.workers.dev . 기존 Worker/Funnel 및 비밀 설정 유지.

## 승인 후 실행 범위

1. 고정 UI 커밋만 담은 Git 전송 파일을 관리 SSH로 VM의 제한된 임시 폴더에 전달.
   이는 이번 앱 배포 전송용이며 인수인계 패키지나 개인정보/비밀 백업이 아님.
2. work/deploy-ui-f946824.sh로 현재 SHA·clean 상태·사전 건강 상태·전송 커밋·보안
   조상/스키마/의존성 동일성을 확인. 다른 상태면 중단하고 다시 검토.
3. bookmembers 서비스 정지 → f946824 detached checkout → 서비스 시작.
   짧은 접속 중단 가능. Windows/Ubuntu 재부팅 및 패키지 설치 없음.
4. 로컬 건강 검사 실패 시 같은 스크립트가 bda8a82로 복귀 후 서비스를 시작.
5. 공개 GET으로 홈/로그인/새 CSS·JS/캘린더·DB 상태/카카오 시작 검증.
   공개 회귀가 확인되면 bda8a82 앱으로 복귀. 운영 데이터 테스트 쓰기 없음.

GitHub main push, Render 배포, Worker CDN 배포, 도메인 구매·Tunnel 전환,
카카오 설정, DB·환경변수 변경은 이 UI 배포 범위에 포함하지 않음.

## 운영 배포 완료 — 2026-10-28 14:22:53 KST

사용자 승인: '미니 PC에만 배포하고, render쪽에는 가지 않도록 해.'

- 미니 PC에만 전송·적용. GitHub push/Render 도구/Worker 배포 호출 없음.
- 전송 SHA256: 202f61386302b7742ca8bb93962fb487d6c961fc5dd2c76680299de1618a00cf.
- 사전/사후 앱·DB 건강 정상. VM HEAD f9468246927e1e04b7c71eaa9ab9d8049ca69053,
  clean/detached. bookmembers active/enabled, NRestarts=0, tailscaled active.
- 공개 검증 15항목 통과: 새 LMS 홈/로그인/캘린더, DB 건강, 카카오 시작·콜백·state·
  보안 쿠키, no-store·원본 헤더 비노출, CSS/JS의 해당 커밋 내용 일치, 폰트 HEAD,
  세미나 캘린더 API 로그인 요구(401), Funnel 직접 접속 거부(403).
- 검증 시각 2026-10-28T05:24:18Z. 증거 work/ui-f946824-public-verification.json.
- 로그인 완료를 새로 수행하거나 운영 데이터를 작성하지 않았다. 실패 회귀가 없어 복귀하지 않음.
- 현재 운영 UI는 f946824. 즉시 앱 복귀가 필요할 때의 기준은 보안 패치 bda8a82.
- 기존 Funnel 지연/no-store 경로는 그대로이며 이번 릴리스로 속도가 해결됐다고 판단하지 않는다.
- 다음 필수 작업: 운영 구조 선택, 승인된 재부팅 자동 복구 점검, 오프사이트 백업·격리 복원.
