# 위키 회원 연동 · 로컬 검토 (2026-10-28)

기준: `codex/minipc-security`의 `d8378b4719c114b7ab633cdebbfc696044b6f3e6`에서 별도 `codex/wiki-member-integration` 브랜치. 원본 작업 폴더는 변경하지 않았다. 운영 배포·운영 DB·Kakao 앱 설정·원격 push 없음.

## 확인 주소와 저장 위치

- 통합 사이트: http://127.0.0.1:5105/wiki/
- 예시 회원 전환: http://127.0.0.1:5105/__wiki_preview
- 내부 엔진: `127.0.0.1:5097` (외부 공개 금지)
- 본문·수정 이력: 이 PC의 `../bookbanwoo-wiki/integration-runtime/data.db` (SQLite)
- 기존 초안 DB `../bookbanwoo-wiki/runtime/data.db`는 보존했다. SQLite backup API로 복사했으며 원본에 연동 실험을 하지 않았다.
- Supabase에는 위키 본문을 저장하지 않는다. 운영 연동 코드가 기존 `members`, `seminar_terms`, `seminar_term_members`를 읽어 권한을 판정한다. 로컬 미리보기는 예시 데이터만 사용한다.
- `wiki_content/`는 14개 초안의 추적 가능한 스냅샷이다. 편집 이후의 최신 내용과 전체 이력은 SQLite가 기준이다. 폴더를 재가져오기 해 사용자 편집을 덮어쓰면 안 된다.

## 권한

| 상태 | 읽기 | 편집·새 문서·미리보기·저장 |
| --- | --- | --- |
| 비로그인 / Kakao 인증이 없는 세션 | 로그인 필요 | 불가 |
| 가입 대기·차단·탈퇴 계정 | 불가 | 불가 |
| 가입 승인 회원, 현재 학기 활동 명단 `active` | 가능 | 가능 |
| 가입 승인 회원, 현재 학기 `paused` / `left` / 명단 없음 | 가능 | 불가 |
| 현재 학기 없음·기간 겹침·명단 미확정 | 가능 | 불가 |
| 회원 또는 학기 조회 실패 | 503 안내 | 불가 |

한국시간 오늘이 `start_date`~`end_date` 안에 있고 `is_active=true`인 학기 하나를 사용한다. 기존 `is_active`는 학기 삭제/활성 표시이므로 그것만으로 현재 학기를 정하지 않는다. URL의 선택 학기나 지난 학기, 전역 회원 `is_active`, 임원 역할은 편집 권한을 대신하지 않는다. 매 요청 및 저장 직전에 새로 조회한다. 학기별 휴식과 계정 차단은 다른 상태다.

기존 `/login` → `/login/kakao` → callback이 세션을 만들고 `next=/wiki/...`로 돌아온다. 위키 자체 로그인·가입은 노출하지 않는다. 로컬에서는 **공급자 응답만 가짜로 대체**하며 실제 Kakao 서버에 접속하지 않는다. 예시 계정 선택기는 `testing/wiki_local_preview.py`에만 있고 일반 앱에 등록되지 않는다.

## 변경 파일

| 파일 | 변경 |
| --- | --- |
| `wiki_access.py` | 기존 회원 및 현재 학기 활동 상태로 권한 결정; 과거 명단으로 대체하지 않음 |
| `wiki_engine.py` | 고정 버전 openNamu와 서버 내부 연결; 회원별 가명 계정; 본문 저장·버전 충돌은 엔진 사용 |
| `wiki_routes.py` | `/wiki` 읽기·목록/검색·편집·미리보기·새 문서·이력/과거 버전; CSRF, 비공개 캐시, 안전한 HTML 변환 |
| `templates/wiki/*`, `static/lms_wiki.css` | 기존 LMS shell·빨강 `#d20f17`·회색·로컬 폰트 재사용; PC/모바일 문서·입력·이력 화면 |
| `app.py` | 설정 스위치와 라우트 연결; 기존 `/docs` URL 이동; 기존 폐쇄 편집 API의 안내 링크 갱신 |
| `_lms_navigation.html`, `_header.html`, `my_page_member.html`, `help_admin.html`, `lms_base.html` | 위키 메뉴·계정 메뉴·안내 링크를 같은 창으로 연결; 위키 메뉴 접기 이름 |
| `testing/test_wiki_integration.py` | 권한/학기/로그인/CSRF/실패 차단 중심의 8개 테스트 |
| `testing/verify_wiki_native.py` | 실제 로컬 엔진 저장·미리보기·이력·충돌·원문 복원·휴식 회원 확인 |
| `testing/wiki_local_preview.py` | 운영 .env 미로딩·가짜 Supabase·가짜 OAuth 공급자·외부 HTTP 차단 미리보기 |
| `wiki_content/*` | 기존 초안 14개 보관; 편집 안내를 현재 학기 활동 회원 기준으로 정정 |

기존 제출·출석·예약·운영진 기능과 운영 DB 스키마를 수정하지 않았다. 위키는 본문/이력을 기존 openNamu API로 저장한다. 계정 연동에 필요한 가명 계정과 그룹만 **로컬 위키의 기존 계정 테이블**에 생성한다. 엔진 코드를 복사해 재작성하지 않았다.

## 확인 결과

- `python -m unittest testing.test_wiki_integration -v`: **8개 통과**. 실제 Kakao 공급자 호출 대신 응답을 대체했으며 callback의 state와 세션/복귀 동선을 사용했다.
- `python testing/verify_wiki_native.py`: **통과**. 실제 엔진 미리보기는 이력 미변경, 저장/작성자 기록, 오래된 버전 409와 입력 유지, 원문 복원, 휴식 회원 읽기 허용/편집 차단.
- 실제 Chrome 한 탭에서 로그인 동선, 대문, 편집 안내 저장, PC/모바일 확인. 이미지와 최종 결과는 작업공간의 `outputs/wiki-integration-2026-10-28/`에 보관.
- 전체 사이트 회귀 검사·운영 Kakao 실계정·운영 DB·배포·복구 훈련은 실행하지 않았다.

## 남은 범위

본문·표·목록·내부 링크·검색·편집·미리보기·이력·과거 버전을 연결했다. openNamu 원본 관리실, 계정 설정, 파일 업로드/다운로드, 토론, 문서 이동/삭제는 이 사이트 경로에 노출하지 않는다. 실행 스크립트/iframe을 포함하는 고급 문법은 제거한다. 엔진 스킨 전체를 프록시하지 않으므로 네이티브 주소 우회로 회원 검사를 건너뛰는 경로가 없다.

내부 엔진 자체는 회원 DB를 모른다. **운영 전에는 loopback 포트·SQLite·연동 키를 외부에서 접근할 수 없도록 구성해야 한다.** 이번 작업은 로컬 통합이며 미니PC 서비스를 설치하거나 프록시를 변경하지 않았다. 실제 Kakao 호출과 운영 명단 확인, 운영용 엔진 설정, 파일 백업/복구 검증은 배포 단계에서 별도 진행한다.

## 설정과 실행

일반 앱에서 위키는 기본 꺼져 있다. 설정이 없으면 기존 Notion 링크를 유지한다.

```
WIKI_ENABLED=1
WIKI_UPSTREAM=http://127.0.0.1:5097
WIKI_DATABASE=<초기화된 별도 openNamu SQLite 절대 경로>
WIKI_IDENTITY_SECRET=<32자 이상 서버 전용 랜덤 값>
```

가명 계정 매핑에 사용한 키는 DB와 함께 안전하게 보관한다. 키를 바꾸면 작성자 계정 식별도 바뀐다. API/화면/로그에 키나 엔진 쿠키를 출력하지 않는다. 원본 엔진은 openNAMU `v4.4.0-beta.3`, commit `5a413c05b620df4ef131e7805d07f22d436606c6`. Windows 바이너리 SHA256 `94d5ccb39a7e28003eeee367fa2ba751ae016ea298e105a084eb22cbd3ab373b`.

현재 PC에서는 별도 `integration-runtime` 안에서 `../engine-current/main.amd64.exe 5097 --localhost`를 실행하고 앱 저장소에서 `testing/wiki_local_preview.py`를 실행한다. 기본 Python 실행 파일이 Windows 앱 제어에 차단되어 설치된 Codex Python 3.12.14와 기존 앱의 site-packages를 사용했다. 보안 설정을 변경하지 않았다. 실행 명령은 현재 PC의 경로에 의존하므로 운영 실행 명령으로 복사하지 않는다.

## 되돌리기

로컬 두 프로세스를 종료하면 통합 미리보기가 중단된다. 일반 앱은 `WIKI_ENABLED=0`으로 원래 Notion 링크와 기존 동작으로 돌아간다. 브랜치 변경을 되돌리려면 위키 통합 커밋을 revert한다. 새 SQLite와 연동 키는 삭제하지 않고 보존한다. 기존 브랜치·운영 DB·원본 위키 DB는 변경하지 않아 복원 작업이 필요 없다.

향후 미니PC 배포 시 위키의 SQLite 일관된 스냅샷, 첨부파일 디렉터리(사용하는 경우), 연동 키를 별도로 백업해야 한다. 기존 Supabase 백업에 위키 본문이 자동 포함되지는 않는다.
