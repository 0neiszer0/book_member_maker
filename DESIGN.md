# Design System — 책 먹는 호반우 (`knu-read.xyz`)

경북대학교 중앙독서동아리 **"책 먹는 호반우"** 웹 서비스의 디자인 시스템 기준서입니다.
모든 내부 LMS·운영 화면과 외부 소개·아카이브 화면이 일관된 시각 언어와 접근성 기준을 따르도록 이 문서를 기준으로 유지·확장합니다.

---

## 1. Visual Direction & Modes

### Mode A: Operate & Read (내부 LMS, 캘린더, 위키, 세미나 사전 자료, 운영진 도구)
- **Intentional KNU Canvas LMS Skeleton**: 경북대 학생이 별도 학습 없이 바로 사용할 수 있도록 KNU Canvas LMS의 구조적 뼈대를 의도적으로 계승합니다.
  - 좌측 고정 `#d20f17` 글로벌 레일 (`84px` / 축소 시 `54px`)
  - 선명한 흰색 본문 캔버스 (`#ffffff`) 및 차분한 보조 표면 (`#f5f7f8`, `#f1f4f6`)
  - 좌측 강의실/위키 내비게이션 (`192px`) 및 우측 보조 패널 (`288px`)
  - `1px` 실선 경계 (`#c7cdd1`, `#d8dcdf`)와 절제된 `4px / 6px / 8px` 반경 체계
- **DO NOT** replace or redesign `lms_base.html` geometry, global rail color (`#d20f17`), or classroom navigation layout.

### Mode B: Persuade & Showcase (외부 랜딩 `/`, 공개 아카이브 `/archive`, 비로그인 공개 셸)
- **Editorial Reading-Club Shell (`public_landing.css`)**:
  - 따뜻한 종이 톤 배경 (`#faf8f2`), 깊은 먹색 잉크 (`#282322`), 명조 계열 디스플레이 헤딩 (`Georgia, "Nanum Myeongjo", Batang, serif`)과 `Noto Sans KR` 본문의 조합
  - 강조색은 KNU 크림슨 계열(`#b60f17` / `#d20f17`)로 내부 LMS와 브랜드 정체성을 공유
- 비로그인 공개 동아리방/캘린더(`/club-room`, `/calendar`)는 `_public_shell.html` 위에서 흰색 카드(`#ffffff`)와 `1px` 웜 그레이 테두리(`#d8d0c5`)로 캘린더 가독성과 대비를 확보합니다.

---

## 2. Unified Color Tokens (`static/lms_ui_tokens.css`)

내부 LMS 및 운영·출석·기록 화면은 반드시 `lms_ui_tokens.css` 토큰을 사용하며, 레거시 쿨 슬레이트(`#0f172a`)나 분산된 레드(`#a6192e`)를 직접 하드코딩하지 않습니다.

| Role | Token | Hex / Value | Usage |
| :--- | :--- | :--- | :--- |
| Primary Brand Accent | `--ui-accent` | `#d20f17` | 글로벌 레일, 주요 CTA, 활성 탭 텍스트 |
| Accent Hover | `--ui-accent-hover` | `#a80b12` | 주요 CTA 호버 (`7.72:1` on `#fff`) |
| Accent Active | — | `#8f090f` | 버튼 눌림 상태 |
| Accent Soft Surface | `--ui-accent-soft` | `#fff5f5` | 강조 배지·미리보기·주의 패널 배경 |
| Canvas Background | `--ui-surface` | `#ffffff` | 기본 카드·본문 캔버스 |
| Page / Panel Surface | `--ui-bg` | `#f5f7f8` | 툴바·보조 배경·테이블 헤더 |
| Subtle Surface | `--ui-surface-subtle` | `#f1f4f6` | 세그먼트 탭 트랙, 기본 필(pill) 배경 |
| Card Border | `--ui-border` | `#d8dcdf` | 기본 1px 카드·구분선 |
| Strong Border | `--ui-border-strong` | `#c7cdd1` | 입력창·버튼·강조 구분선 (Canvas `--lms-line`) |
| Primary Ink | `--ui-ink` | `#2d3b45` | 기본 본문 및 제목 (`11.52:1` on `#fff`) |
| Secondary Ink | `--ui-ink-muted` | `#56616a` | 부제목·설명·라벨 (`6.34:1` on `#fff`, `5.90:1` on `#f5f7f8`) |
| Subtle Ink | `--ui-ink-subtle` | `#626e77` | 메타·보조 캡션 (`5.23:1` on `#fff`, `4.87:1` on `#f5f7f8`) |
| Radius Ramp | `--ui-radius-sm/md/lg` | `4px / 6px / 8px` | 소형 배지·버튼 / 탭·입력 / 카드·다이얼로그 |
| Elevation | `--ui-shadow-sm` | `0 1px 2px rgba(45, 59, 69, 0.06)` | 카드 및 버튼 최소 깊이감 |

### Semantic Status Colors (WCAG AA ≥ 4.5:1 Verified)
- **Info / Focus**: `#0374b5` (`5.04:1` on `#fff`)
- **Success**: `#256d44` (`6.27:1` on `#fff`; soft `#ecfdf5` / border `#b7e4c7`)
- **Warning**: `#9a4d00` (`6.11:1` on `#fff`; soft `#fffbeb` / border `#f5d08a`)
- **Danger**: `#b42318` (`6.57:1` on `#fff`; soft `#fff5f5` / border `#f3c4c6`)

---

## 3. Typography, Measure & Numeric Alignment

- **UI & Body Stack**: `'Noto Sans KR', 'Lato Extended', 'Noto Sans', Helvetica, Arial, sans-serif` (번들된 로컬 `woff2` 폰트만 사용하며 외부 CDN 폰트를 추가하지 않습니다).
- **Reading Measure**: 위키(`.lms-wiki`), 세미나 사전 자료, 발제문 본문(`.lms-topic-reading`), 게시판 리치 본문(`.lms-board-body.is-rich`), 아카이브 본문은 `68ch–72ch` 읽기 폭을 유지합니다.
- **Asymmetric Heading Spacing**: 본문 산문에서는 제목 위 여백을 아래 여백보다 크게 두어 섹션 소속감을 명확히 합니다.
- **Tabular Figures**: 날짜, 횟수, 출석 매트릭스, 캘린더 셀 숫자, 통계·KPI 카드는 반드시 `font-variant-numeric: tabular-nums`를 적용합니다.

---

## 4. Component & Anti-Pattern Rules

1. **No `border-accent-on-rounded` or `side-tab` Stripes**:
   - 둥근 모서리(`border-radius > 0`)를 가진 카드·배너·행에 `border-top: 3px` 또는 `border-left: 3px` 색상 띠를 두지 않습니다.
   - 강조가 필요하면 전체 `1px` 테두리(`border-color`), 은은한 배경 틴트(`#fff5f5`, `#f2fbf6`, `#fffbeb`), 또는 인라인 상태 필(`.ui-pill`)을 사용합니다.
2. **Minimum Legible Text Size**:
   - 기능적 UI 텍스트(배지, 메타 정보, 시간표 시간축, 캘린더 라벨)는 최소 `12px`를 유지하며 `11px` 미만을 사용하지 않습니다(아이콘 위 숫자 카운트 배지는 최소 `11px`).
3. **One Primary Crimson CTA per Viewport Section**:
   - 한 화면 구획에는 핵심 행동 1개만 빨간 Primary CTA(`.lms-button-primary`, `.ui-btn-primary`, `.cr-primary`)를 사용하고, 보조 동작은 중립 아웃라인 버튼(`.lms-button`, `.ui-btn`)을 사용합니다.
4. **Browser Surfaces**:
   - 텍스트 선택(`::selection`), 키보드 포커스(`:focus-visible` with `#0374b5` 2px outline), 링크 밑줄 간격(`text-underline-offset: 3px`), 테이블 숫자 정렬(`tabular-nums`), 정돈된 스크롤바를 기본으로 유지합니다.
