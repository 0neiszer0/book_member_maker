# 카카오톡 링크 미리보기 개선

2026-10-28 17:35 KST. **사용자 승인 후 운영 배포 및 카카오 미리보기 갱신 완료**.

## 운영 적용 결과

- 앱 `7c92f9b200ca91ac249b4dd1936e7aca6030ea4f`, clean. bookmembers 앱만 재시작.
- Worker `6eccf7cc-feb0-42f1-9f25-96889aadf622`. 새 이미지 1파일 업로드, 기존 자산 유지.
- CDN 공개 검사5/5, 앱 적용 후 공개 검사25/25 통과. 앱/DB health 및 카카오 로그인 시작 정상.
- bookmembers와 bookmembers-cloudflared 모두 active/enabled. 재부팅 시험은 별도 미완료.
- 카카오 공식 URL 메타 정보 도구에서 `https://knu-read.xyz/` 캐시 초기화:
  **1개의 스크랩 정보가 삭제되었습니다.** 그 뒤 메타 정보 조회에서 새 이미지 URL과
  **책반우 사이트** 한 줄 미리보기의 실제 렌더링을 확인했다. 실제 채팅 메시지는 보내지 않았다.
- Render·GitHub main·DB 데이터/스키마·카카오 로그인 설정·도메인은 변경하지 않았다.
- 추가 DB 조회 속도 최적화는 이번 배포에 포함하지 않았다. 여전히 분석까지만 완료.
- 증거: 작업 폴더 `outputs/og-preview-release-state.json`, `outputs/og-preview-public-full.json`.
- 복구 기준: 앱8e290f7, Worker a9a69259-ee5b-4cb4-bc44-2fd67c39f491;
  VM manifest 백업 `/home/bookadmin/og-release-7c92f9b/previous-asset-manifest.json`(root600).
  기존 불변 파일을 보존했다. 이미 적용된 배포 스크립트를 다시 실행하지 않는다.

## 이미지 및 구현

사용자는 큰 글자/삽화 시안에 이어 아이콘·학교 설명·주소를 넣은 시안도 수정 요청했다.
최종 시안은 흰 배경 중앙에 **책반우 사이트** 한 줄만 표시한다. 아이콘/학교/주소/삽화 없음.
내장 image_gen으로 생성했으며 별도 API/CLI는 사용하지 않았다.

- 최종 파일: `static/og/club-preview-v2.png`, PNG 1730×909, 903,217 bytes.
- 생성 원본: `C:/Users/HOME/.codex/generated_images/01a17d47-514e-70a2-b11b-d3d134809307/exec-4fcee512-73ea-4d0b-9217-c20054a27edf.png`.
- 최종 프롬프트: 작업 폴더 `outputs/og-preview-text-only-prompt.txt`.
- 코드/이미지 커밋: `7c92f9b200ca91ac249b4dd1936e7aca6030ea4f`.
- 새 자산 묶음 해시: `69f0d779d0e1838053d6bb0dc267c40cd435898c858d772e2c88f58c20153a99`.
- 새 이미지 경로: `/static/_v/69f0d779d0e1838053d6bb0dc267c40cd435898c858d772e2c88f58c20153a99/og/club-preview-v2.png`.
- 새 묶음 45개 + 현재 운영의 f946824 묶음 44개 보존. 기존 파일 44개 내용은 그대로다.

일반 HTML 공유 태그와 engagement 페이지 기본 이미지가 새 파일을 가리킨다.
engagement의 고정 `/static/og/club-preview.png` 경로도 `url_for`로 바꾸어 기존 CDN 버전
생성 로직을 사용한다. 이미지 크기 메타데이터/대체 설명을 실제 파일과 맞췄다.
본문 UI·DB·권한·로그인 설정·도메인·Worker 프록시 동작은 변경하지 않았다.
미리보기 이미지는 OG 메타데이터용이며 페이지 본문 이미지로 추가하지 않았다.

검증: 기존 정적 자산 검사 5개 통과, 합성 데이터로 홈페이지/로그인/책 추천 렌더 및 이미지
바이트·크기·기존 CDN 보존 21/21 통과, 최종 시안으로 Wrangler dry-run 성공, 배포 Bash 문법 검사 통과.
초기 로컬 테스트의 cwd/임시 디렉터리 및 가짜 DB 주입 문제는 테스트 도구에서 수정했다.
위 검증은 배포 전 로컬 준비 단계였다. 운영 적용과 카카오 도구 확인 결과는 맨 위에 기록했다.

준비 파일: 작업 폴더 `work/og-release/`의 bundle, ZIP, 설치 도구, 배포 스크립트,
SHA256SUMS. VM 이전 앱 `8e290f7` 및 clean 상태를 강제 확인하고 이전 manifest를 보존한다.
배포 실패 시 앱과 manifest를 복구하며 기존 불변 정적 파일을 삭제하지 않는다.
이 패키지의 bundle HEAD는 7c92f9b로 고정됐다. 8f4310a 시안 및 당시 승인 질문은 폐기됐다.
이후 문서 커밋 때문에 다시 패키징한다면
배포 스크립트의 정확한 ref 검증도 일치시켜야 하며 무작정 재생성하면 안 된다.

## 승인받아 실행한 범위

1. 준비한 기존 Worker www의 정적 자산 배포(프록시/비밀값 그대로). 새 이미지 공개 GET 검증.
2. 미니 PC에 7c92f9b 코드·동일 자산을 설치하고 bookmembers 앱만 재시작.
3. 공개 홈/로그인/책 추천 OG 태그·이미지·health 확인. 회귀 시 이전 앱/manifest/Worker 복구.
4. Kakao Developers OG 캐시 도구로 홈페이지 URL 캐시 갱신 후 새 공유 카드 확인.
   실제 채팅 메시지 전송은 자동으로 하지 않는다.

Render·GitHub main·DB·카카오 로그인 설정·호스트 재부팅은 이 변경 범위에 없다.
사용자가 이미지 배포·앱 재시작·미리보기 캐시 갱신을 명시적으로 승인한 뒤 실행했다.

카카오는 서버/기기 캐시로 예전 이미지가 남을 수 있으므로 새 이미지 URL을 사용했다.
홈페이지 주소의 기존 스크랩 캐시도 공개 배포 후 갱신했다. 이미 발송된 카드까지 자동
갱신된다고 보장하지 않으며 카카오 도구의 실제 새 카드 표시까지만 확인했다.
공식 안내: https://developers.kakao.com/docs/ko/message-template/faq
및 https://devtalk.kakao.com/t/topic/33298 (캐시/새 이미지 URL),
현재 캐시 도구: https://developers.kakao.com/tool/debugger/sharing
(기존 https://developers.kakao.com/tool/clear/og 는 이 주소로 이동한다).
