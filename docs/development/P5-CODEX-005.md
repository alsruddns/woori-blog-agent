# P5-CODEX-005 — Blogger 테마 호환성 및 게시 준비 검증

## 목적 및 기준

P5-CODEX-004의 디자인 시스템·안전 HTML 렌더러·SEO 검사·미리보기를 이어받아, 게시 전에 Blogger 대상과 원고 버전을 묶은 재현 가능한 준비 자료를 확인할 수 있도록 했다. 기준 커밋은 `322a8effc2de8f3d5232548ff84604f31c0e7ea2`이며 develop에서 작업했다.

선행 구현을 확인했다. 렌더러와 네임스페이스 CSS는 1.1.0, SEO 메타데이터는 migration 041 기반이며, P5-CODEX-004 기록에는 관련 테스트와 build 결과가 있다. 이번 구현은 운영 DB에 migration을 적용하지 않았다.

## 구현

- 기존 게시용 미리보기에 등록된 같은 언어의 Blogger 대상 선택을 추가했다. 원고 상세 API는 기존 `blogger_blogs` 정보를 SELECT만 하며, OAuth 토큰이나 외부 Blogger API를 조회하지 않는다.
- 미리보기 응답에 게시 준비 JSON을 추가했다. 게시 제목, 안전 렌더링 HTML, 언어·라벨, Blog ID 및 등록 레코드, 원고·편집 버전, 본문/렌더 결과 SHA-256, 렌더러·디자인 버전, SEO 메타데이터, 출처, 검증 결과, 차단 사유와 생성 시각을 포함한다.
- 패키지 해시는 생성 시각을 제외해 동일 입력에서 재현되며, idempotency key는 블로그 레코드·콘텐츠 버전·렌더 HTML을 기반으로 한다. 미리보기에서 JSON을 내려받을 수 있다. API·승인·저장·예약·발행은 호출하지 않으며, 이 패키지는 operations DB에 저장되지 않는다.
- 패키지 생성은 승인 상태를 평가하거나 변경하지 않는다. 항상 `publish_ready=false`, `submission_performed=false`이며 현재 Blogger 접근 재확인 차단 사유를 포함한다. 출처의 공식성을 새로 증명하지 않으므로 패키지에서는 미검증으로 표시한다.
- 예시 Blogger 요청 본문은 `title`, `content`, `labels`만 제공한다. 검색 설명 및 맞춤 permalink는 API 전송 필드로 추측하지 않고 Blogger 편집기/테마에서 확인할 수동 작업으로 분리했다. canonical, robots, Open Graph와 구조화 데이터 중복 여부도 테마 검토 항목이다.
- 공통 작성 표준을 렌더러가 대체하지 않으며, P5-CODEX-003의 사실·분석 구분과 전문가 칼럼 품질 기준은 유지된다.

## 테마·미리보기 확인 범위

저장소에 네 블로그의 실제 Blogger 테마 XML/CSS가 없었다. 이번 Phase에서 Blogger 테마나 게시물을 가져오거나 수정하지 않았으므로 네 실제 테마의 CSS 충돌, 본문 폭/글꼴, 위젯, canonical·robots·Open Graph·구조화 데이터는 미검증이다. 등록 Blog ID/URL도 최신 Blogger API 응답으로 확인하지 않았다. 화면과 문서에 이 차이를 명시했다.

로컬 Playwright fixture는 `post-body`, `entry-content`, `blog-post` 형태의 대표 선택자 충돌을 사용해 ko/en/ja/zh-CN 본문이 CSS에 의해 잘리는지 확인했다. 미리보기 E2E는 mock API의 한국어 예시 원고로 대상 선택, SEO 탭, 차단 사유, JSON 다운로드를 확인했다. 따라서 UI 검증은 실제 외부 Blogger가 아닌 로컬 코드와 fixture 검증이다.

스크린샷:

- 데스크톱: `docs/development/assets/P5-CODEX-005-package-desktop.png`
- 모바일: `docs/development/assets/P5-CODEX-005-package-mobile.png`

테마 백업·네임스페이스 CSS 수동 검토·Blogger 편집기 확인 절차와 플랫폼 제한은 `docs/operations/blogger-theme-integration.md`에 기록했다. 공식 참고자료는 [Blogger Posts resource](https://developers.google.com/blogger/docs/3.0/reference/posts) 및 [Blogger theme CSS help](https://support.google.com/blogger/answer/176245?hl=en-US-u-mu-fahren)다.

## 검증 결과

- `scripts/verify.ps1`: 최종 실행 통과. Ruff, mypy(35개 소스), pytest(253 passed), Python wheel, Dashboard ESLint, production build, TypeScript typecheck, `git diff --check` 통과.
- Playwright 변경 범위: desktop/mobile 프로젝트에서 게시 준비 미리보기와 4개 언어 theme fixture 등 4 tests passed. preview widths: 320, 390, 430, 768, 1280, 1920px; locale fixture widths: 320, 390, 768, 1280, 1920px. 테스트는 페이지 외부 요청이 없음을 확인했다.
- 최초 전체 검증에서 레거시 manuscript detail fixture에 `language_code`가 없는 경우 신규 블로그 매핑 조회가 실패했다. 해당 필드가 있을 때만 매핑을 읽고, 없으면 대상 목록을 빈 상태로 두도록 수정한 뒤 전체 검증을 다시 통과했다.
- 테스트 과정에서 Blogger API 호출, Google OAuth 요청, AI provider 호출, 운영 DB 쓰기, migration 적용, 승인/readiness 상태 변경은 수행하지 않았다. 테스트용 UI API 응답은 mock이었다.

## 상태 및 남은 작업

- 구현 완료: 미리보기 대상 선택 및 로컬 게시 준비 artifact, 재현 가능한 hash/idempotency 식별, API 필드 제한, 수동 테마/SEO 점검 안내, 로컬 브라우저 fixture 검증.
- 실제 테마 호환성: 미검증. 각 Blogger 템플릿을 사람이 백업한 뒤 적용 전 미리보기 및 네 언어별 렌더 확인이 필요하다.
- Blogger 접근 권한/Blog ID 최신성, 검색 설명·permalink 설정, 실제 게시 결과: 미검증이며 본 단계에서 호출하지 않았다.
- Google Search Console 실측 데이터 없음. 순위·클릭 예상값을 만들지 않았다.
- 게시 준비 JSON은 요청 시 생성/다운로드하는 비영속 미리보기 산출물이다. 승인·게시 시스템이나 운영 감사 DB에 기록하지 않는다.

## Git

develop에서만 변경했다. 커밋 해시와 `origin/develop` 푸시 상태는 최종 실행 보고에서 확인한다.
