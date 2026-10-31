# 카페 글 옮기기 + 세미나 후기 비회원 링크 — 적용 순서

브랜치 `grok/seminar-review-link`. 아래 단계는 모두 **회장 최종 OK 후** 한 번에 진행한다.
정적 파일(CSS/JS)은 바뀌지 않아 CDN 릴리스는 필요 없다. 앱만 재시작한다.

벽돌책(menuid 22)은 원래 공개 모집 글이라 제목·본문·작성자(기수+이름)를 그대로 옮긴다. 나머지 게시판은 기수만 표시.
같은 배포에 위키 버전 비교(`/wiki/diff/<문서>?old=&new=`, 수정 이력의 '비교' 링크·두 버전 선택)가 포함된다.

## 0. 백업 (VM)
- `sudo systemctl start bookmembers-backup.service` 후 성공 확인 (DB custom dump + Storage).
- 현재 앱 커밋 기록: `git -C /opt/book_member_maker rev-parse HEAD` (지금 0a31a12).

## 1. 스키마 마이그레이션 (비회원 후기)
- `supabase/migrations/20261031130000_seminar_review_guest_link.sql`을 DB 컨테이너 psql로 실행
  (`sudo docker exec -i bookmembers-db-db-1 psql -U postgres -d postgres -v ON_ERROR_STOP=1 < 파일`).
- 확인: `\d public.seminar_reviews`에 author_name/student_id/identity_kind/edit_token_hash, `review_edit_attempts` 존재,
  PostgREST 스키마 캐시 갱신(`notify pgrst, 'reload schema';`).
- 되돌리기: `supabase/rollback/20261031130000_seminar_review_guest_link.rollback.sql`
  (비회원 후기가 남아 있으면 스스로 멈춘다).

## 2. 앱 배포
- `/opt/book_member_maker`를 이 브랜치 커밋으로 맞추고 `sudo systemctl restart bookmembers`.
- 확인: `/healthz`, 로그아웃 상태로 열린 후기 링크 → 이름·학번 칸, 제출 → 수정 코드 화면,
  로그인 후 같은 링크 → "내 계정에 연결하기", 관리자 후기 목록에 "(비회원)".
- 되돌리기: 이전 커밋(0a31a12)으로 되돌리고 재시작. 1단계 스키마는 그대로 둬도 이전 앱과 호환된다
  (이전 앱은 member_id가 있는 행만 쓴다).

## 3. 데이터 준비 (`prepare.sql`)
- '세미나 후기' 게시판 이름 → '세미나 기록'(주소 seminar-reviews 유지), 운영진 전용 '카페 사진 보관함 (검토 중)',
  로그인 불가 '카페 보관' 작성자 계정, 2026-01-12/01-19 회차 책 제목 맞바꿈(카페 발제문·일지 기준),
  2026-10-01 회차 '나사내금' → '나는 소망한다 내게 금지된 것을'.
- 되돌리기: `prepare.rollback.sql` (가져온 글이 남아 있으면 멈춘다).

## 4. 카페 글 가져오기
1. 박스에서: `python infra/cafe_import/import_cafe.py --archive <카페 백업> --history-json <회차 목록> --export <폴더>`
   (pdftotext로 본문 추출, 이름·학번 제거, 이미지 WebP 변환까지 끝낸 plan.json + images/)
2. 폴더를 VM `/var/tmp/cafe-import/`로 복사.
3. VM에서 dry-run: `.venv/bin/python infra/cafe_import/import_cafe.py --from-export /var/tmp/cafe-import/export`
4. 적용: 앱 환경변수를 읽은 셸에서 `... --from-export ... --apply --state /var/tmp/cafe-import/state.json`
   (중간에 멈춰도 같은 명령으로 이어서 진행, 이미 만든 글은 건너뜀)
5. 공개 게시판 사진 62장은 운영진 확인 뒤 `--public-images attach`로 다시 export → 같은 state로 `--apply`.
- 되돌리기: `... --rollback --state /var/tmp/cafe-import/state.json` (만든 글·첨부·Storage 파일 삭제) → 3단계 되돌리기.
