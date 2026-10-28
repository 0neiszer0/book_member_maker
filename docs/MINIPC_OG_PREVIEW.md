# 카카오톡 링크 미리보기 개선

2026-10-28 KST. **로컬 준비 완료, 운영 배포 승인 대기**.

사용자는 첫 시안의 큰 글자/삽화를 거절하고 최대한 미니멀한 이미지로 다시 요청했다.
최종 시안은 밝은 배경, 작은 빨간 책 아이콘, 한 줄 동아리 이름, 학교 설명, 작은 새 주소로 구성했다.
내장 image_gen으로 생성했으며 별도 API/CLI는 사용하지 않았다.

- 최종 파일: `static/og/club-preview-v2.png`, PNG 1730×909, 1,084,135 bytes.
- 생성 원본: `C:/Users/HOME/.codex/generated_images/01a17d47-514e-70a2-b11b-d3d134809307/exec-9cab746a-5ecc-4c2b-9849-6baf9c58852e.png`.
- 최종 프롬프트: 작업 폴더 `outputs/og-preview-generation-prompt.txt`.
- 코드/이미지 커밋: `8f4310a714f28e8c184396f5b7ea4b46570be06a`.
- 새 자산 묶음 해시: `a461f5f756882c70306eab9378f7a1bde7262ef5bc1333ee2d80b80cbc75f03a`.
- 새 이미지 경로: `/static/_v/a461f5f756882c70306eab9378f7a1bde7262ef5bc1333ee2d80b80cbc75f03a/og/club-preview-v2.png`.
- 새 묶음 45개 + 현재 운영의 f946824 묶음 44개 보존. 기존 파일 44개 내용은 그대로다.

일반 HTML 공유 태그와 engagement 페이지 기본 이미지가 새 파일을 가리킨다.
engagement의 고정 `/static/og/club-preview.png` 경로도 `url_for`로 바꾸어 기존 CDN 버전
생성 로직을 사용한다. 이미지 크기 메타데이터/대체 설명을 실제 파일과 맞췄다.
본문 UI·DB·권한·로그인 설정·도메인·Worker 프록시 동작은 변경하지 않았다.
미리보기 이미지는 OG 메타데이터용이며 페이지 본문 이미지로 추가하지 않았다.

검증: 기존 정적 자산 검사 5개 통과, 합성 데이터로 홈페이지/로그인/책 추천 렌더 및 이미지
바이트·크기·기존 CDN 보존 21/21 통과, 최종 시안으로 Wrangler dry-run 성공, 배포 Bash 문법 검사 통과.
초기 로컬 테스트의 cwd/임시 디렉터리 및 가짜 DB 주입 문제는 테스트 도구에서 수정했다.
운영 데이터/서비스는 사용하지 않았으며 아직 실제 카카오톡 카드가 바뀐 것은 아니다.

준비 파일: 작업 폴더 `work/og-release/`의 bundle, ZIP, 설치 도구, 배포 스크립트,
SHA256SUMS. VM 이전 앱 `8e290f7` 및 clean 상태를 강제 확인하고 이전 manifest를 보존한다.
배포 실패 시 앱과 manifest를 복구하며 기존 불변 정적 파일을 삭제하지 않는다.
이 패키지의 bundle HEAD는 8f4310a로 고정됐다. 이후 문서 커밋 때문에 다시 패키징한다면
배포 스크립트의 정확한 ref 검증도 일치시켜야 하며 무작정 재생성하면 안 된다.

## 승인 후 실행할 범위

1. 준비한 기존 Worker www의 정적 자산 배포(프록시/비밀값 그대로). 새 이미지 공개 GET 검증.
2. 미니 PC에 8f4310a 코드·동일 자산을 설치하고 bookmembers 앱만 재시작.
3. 공개 홈/로그인/책 추천 OG 태그·이미지·health 확인. 회귀 시 이전 앱/manifest/Worker 복구.
4. Kakao Developers OG 캐시 도구로 홈페이지 URL 캐시 갱신 후 새 공유 카드 확인.
   실제 채팅 메시지 전송은 자동으로 하지 않는다.

Render·GitHub main·DB·카카오 로그인 설정·호스트 재부팅은 이 변경 범위에 없다.
사용자 요청에 따라 실제 서비스 변경 직전 승인받아야 한다.

카카오는 서버/기기 캐시로 예전 이미지가 남을 수 있으므로 새 이미지 URL을 사용했다.
홈페이지 주소의 기존 스크랩 캐시는 공개 배포 후 갱신해야 하며, 현재 미공개 URL을 미리
스크랩하면 안 된다. 이미 발송된 카드까지 자동 갱신된다고 보장하지 않는다.
공식 안내: https://developers.kakao.com/docs/ko/message-template/faq
및 https://devtalk.kakao.com/t/topic/33298 (캐시/새 이미지 URL),
캐시 도구: https://developers.kakao.com/tool/clear/og .
