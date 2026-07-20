# 게시판 시스템 설계 문서

네이버 카페에서 운영 중인 콘텐츠(세미나 후기, 회계장부, 세미나 일지, 벽돌책 후기)를
이 앱으로 옮기고, 관리자가 네이버 카페처럼 **게시판을 쉽게 새로 만들 수 있는**
범용 게시판 시스템의 설계안이다. 구현 전 계획 문서이며, 아래 단계 순서대로
나눠서 작업하는 것을 전제로 한다.

## 목표

- 회원이 카카오 로그인 후 글/댓글/사진을 올릴 수 있는 게시판
- 관리자는 대시보드에서 "게시판 이름 + 권한"만 정하면 새 게시판 생성
- 세미나 후기·벽돌책 후기는 기존 기록(history, brick_books)과 연결 가능
- 회계장부는 금액이 구조화되어 월별 합계가 자동 계산
- 모바일 우선(회원 대부분 폰으로 접속), 에디터는 단순 텍스트 + 이미지 첨부

## DB 스키마 (Supabase)

```sql
-- 게시판 정의: 관리자가 자유롭게 생성
CREATE TABLE boards (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    slug        text UNIQUE NOT NULL,          -- URL용: /board/<slug>
    name        text NOT NULL,                 -- "세미나 후기"
    description text,
    board_type  text NOT NULL DEFAULT 'general',
                -- general | review(기록 연결) | ledger(회계) | journal(일지)
    write_role  text NOT NULL DEFAULT 'member',-- member | officer | admin
    is_active   boolean NOT NULL DEFAULT true,
    sort_order  int NOT NULL DEFAULT 0,
    created_at  timestamptz DEFAULT now()
);

CREATE TABLE posts (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    board_id    uuid NOT NULL REFERENCES boards(id),
    author_id   int NOT NULL,                  -- members.id
    title       text NOT NULL,
    body        text NOT NULL DEFAULT '',
    attachments jsonb NOT NULL DEFAULT '[]',   -- [{url, name, size}]
    -- 유형별 확장 필드 (스키마 변경 없이 유형 추가 가능)
    extra       jsonb NOT NULL DEFAULT '{}',
    -- review: {linked_history_id | linked_brick_book_id}
    -- ledger: {entries: [{date, item, amount, memo}], total}
    -- journal: {meeting_date}
    is_pinned   boolean NOT NULL DEFAULT false,
    created_at  timestamptz DEFAULT now(),
    updated_at  timestamptz DEFAULT now()
);
CREATE INDEX posts_board_created_idx ON posts (board_id, created_at DESC);

CREATE TABLE post_comments (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    post_id    uuid NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    author_id  int NOT NULL,
    body       text NOT NULL,
    created_at timestamptz DEFAULT now()
);
CREATE INDEX post_comments_post_idx ON post_comments (post_id, created_at);
```

- 이미지: Supabase Storage 버킷 `board-uploads` 생성, 서버(Flask)가 서비스 키로
  업로드하고 public URL을 `attachments`에 저장. 클라이언트 직접 업로드는
  RLS/Storage 정책 정비 전까지는 하지 않는다.
- 삭제는 소프트 삭제 불필요(동아리 규모) — 하드 삭제 + 관리자만 남의 글 삭제 가능.

## 라우트 설계 (Flask)

| 라우트 | 권한 | 설명 |
|---|---|---|
| `GET /board/<slug>` | member | 글 목록 (페이지네이션 20개) |
| `GET /board/<slug>/write`, `POST /api/board/<slug>/posts` | write_role | 글 작성 |
| `GET /board/<slug>/<post_id>` | member | 글 보기 + 댓글 |
| `POST /api/posts/<id>/update` / `delete` | 작성자·admin | 수정/삭제 |
| `POST /api/posts/<id>/comments` | member | 댓글 |
| `POST /api/upload/board_image` | member | 이미지 업로드(Storage) |
| `POST /api/admin/boards/create` / `update` / `reorder` | admin | 게시판 관리 |

- 헤더 메뉴에 "게시판" 드롭다운: `boards.is_active` 순서대로 노출.
- 관리자 대시보드에 "게시판 관리" 카드: 이름/slug/유형/쓰기 권한 입력 → 생성.

## 게시판 유형별 동작

- **general**: 제목 + 본문 + 이미지. (자유게시판, 공지 등)
- **review** (세미나 후기 / 벽돌책 후기): 글 작성 화면에 "관련 기록 연결" 셀렉트
  (최근 history 회차 또는 brick_books 목록). 연결하면 글 상단에 회차/책 정보 카드가
  자동 표시되고, 반대로 기록 상세 페이지에도 연결된 후기 목록이 붙는다.
- **ledger** (회계장부): 본문 대신 항목 행 편집기(날짜/항목/금액/메모, 행 추가) 입력.
  `extra.entries`에 저장하고 목록 화면에서 월별 합계·잔액을 집계해 표로 보여준다.
  쓰기 권한 기본값 officer.
- **journal** (세미나 일지): general과 동일하되 `extra.meeting_date` 필수,
  날짜 기준 정렬·달력 형태 목록. 단체 대화 내역 붙여넣기 + 사진 첨부 용도.

## 단계별 로드맵

| 단계 | 내용 | 규모(대략) |
|---|---|---|
| Phase 1 | boards/posts/comments 스키마 + general 게시판 CRUD + 이미지 업로드 + 관리자 게시판 생성 UI | 라우트 8개, 템플릿 3개, migration 1개 |
| Phase 2 | review 유형: history/brick_books 연결, 기록 상세 페이지에 후기 섹션 | Phase 1 위에 소규모 |
| Phase 3 | ledger 유형: 항목 편집기 + 월별 합계 뷰 | 템플릿 1개 + 집계 로직 |
| Phase 4 | journal 유형 + 네이버 카페 기존 글 이관 도구(수동 복붙 기준, 필요 시 CSV 임포트) | 소규모 |

각 Phase는 독립 배포 가능. Phase 1만으로도 "세미나 후기"를 general 게시판으로
바로 운영할 수 있다 (review 연결은 이후 업그레이드).

## 주의사항

- **RLS 경고**: 현재 Supabase의 15개 테이블에 Row Level Security가 꺼져 있다.
  이 앱은 서비스 키로만 DB에 접근하므로 anon 키가 클라이언트에 노출되지 않는 한
  동작에는 문제없지만, 게시판(특히 Storage 공개 버킷) 도입 시점에
  테이블별 RLS 정책을 함께 정비할 것을 권장한다. 정책 없이 RLS만 켜면
  서비스 키 외 접근이 전부 차단되므로, 정책 설계 → 적용 순서로 진행할 것.
- 익명 접근은 없다. 모든 게시판은 로그인(멤버) 전제 — 비회원 공개가 필요해지면
  boards에 `read_role` 컬럼을 추가하는 것으로 확장.
- 에디터는 textarea + 이미지 첨부로 시작한다. 서식이 필요해지면 그때
  경량 마크다운(기존 위키의 bleach 재사용)을 붙이는 것이 유지보수에 유리하다.
