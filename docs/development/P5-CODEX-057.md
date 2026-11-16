# P5-CODEX-057 — 수동 원고 실제 Blogger 공개 발행 기능

- 작업 시각: 2026-10-30 (Asia/Seoul)
- 브랜치: `develop`
- 작업 상태: 구현 및 런타임 확인 완료, 사용자별 공개 승인과 실제 게시 전
- 커밋: 후속 기록은 `git log`의 P5-CODEX-057 커밋 참조

## 목적과 기존 상태

수동 Import 원고가 예약 Export 전용 발행 레인과 일반 `publish_ready` 게이트에 걸려 사용자의 명시적인 공개 게시 동작으로 Blogger에 전달되지 않았다. 기존 정책 레코드는 등록되어 있으나 비활성이었고, 수동 원고 locale의 `language_profiles.target_country`가 빈 기본 프로필과 매칭되지 않아 Publishing Job의 필수 `policy_id`도 조회되지 않았다.

수동 발행 요청은 예약 Auto와 분리했다. 요청은 최신 원고 버전·제목·본문·정제 HTML 해시를 재확인하고, 명시적 화면 동의가 있을 때만 append-only 승인 이벤트와 실제 Blogger Job을 같은 DB 트랜잭션에서 생성한다. 사용자가 승인한 범위 밖의 예약·Trends·일반 Auto 정책은 바꾸지 않는다.

## 변경 사항

- 원고 상세의 `다국어·발행` 탭에 `수동 원고 Blogger 발행` 영역을 제공한다. 대상 블로그, 최신 Content Version, 제목·본문·HTML 해시, OAuth 쓰기 scope 상태, 게시 후 보완 항목, 기존 Job을 표시한다. 세 가지 확인 항목과 승인자·사유가 채워지기 전에는 제출이 비활성이다.
- `POST /admin/publications/manual-live-requests`는 원고 해시를 다시 대조하고 최신 버전·Blog/language 연결·OAuth·라벨·중복·긴급 정지를 확인한다. 일반 품질·SEO·사람 검토 미완료는 상태를 통과로 위조하지 않고 게시 후 보완 항목으로 기록한다. idempotency와 기존 Job 조회로 중복 요청을 막는다.
- 기본 Blogger 비용 검토가 유효할 때만 사용자의 정확한 원고 승인 이벤트를 해당 수동 Job에 한정해 공개 작업 컨텍스트로 전달한다. 이 컨텍스트는 스케줄/전체 공개 승인으로 승격되지 않는다. 예약 레인은 기존 별도 승인 정책을 계속 사용한다.
- Worker는 `manual-confirmed` 또는 `scheduled-auto-manual` 실행 모드에서 승인 이벤트가 붙은 수동 Job만 처리한다. payload hash, Blog OAuth mapping, 중복 원격 게시물, 제한, emergency stop을 재확인하고 Blogger 응답/원격 조회 성공 후 게시 원장 및 보완 기록을 연결한다. 네트워크 결과가 모호하면 자동 재게시하지 않는다.
- 기본 언어 프로필(빈 국가 코드)을 후보 정책 조회의 fallback으로 사용하여 게시 Job의 기존 정책 FK를 찾는다. 이 변경은 정책 행을 활성화하지 않는다. 대상 블로그의 `active` 및 `auto_publish_allowed` 값은 바꾸지 않았다.
- Migration 056은 append-only `manual_publication_approval_events`를 추가하고 수동 사전 보완 검토가 정확한 승인 Job에 연결되도록 한다.
- Windows Worker 스크립트는 중복 실행을 거부하고 정상 종료·heartbeat를 확인한다.

## 운영 데이터와 실행 확인

- 운영 DB 백업을 수행하고 백업 카탈로그를 검증했다. 복구 리허설은 프로젝트 소유 격리 DB에서 수행 후 제거했다.
- Migration 056을 로컬 운영 DB에 적용했다. 기존 원고, Blogger OAuth, 게시 원장과 감사 이력은 삭제·초기화하지 않았다.
- 테스트 대상 Import `c3e35c4f-4d79-4772-879f-0232d8bf400a`의 생성 경로는 `manual_codex_import`; 최신 Content Version은 `56a64419-c9c2-43fd-8217-747d89b64bb7`이다. 제목: “영국 공공부문 순부채 3조 파운드 첫 돌파…9월 재정통계 읽는 법”. 대상은 `trend-ko.blogspot.com`이다.
- 브라우저가 확인한 본문 SHA-256: `a66b913af38c796c35c36f15d421f642a7e0aa69bd82efd834ed92e9eb36d891`; 정제 Blogger HTML SHA-256: `2c37245ec98695d1e418bb312b89637f07bd24bdf07d084f5377e96f3a21d279`.
- Blogger 기존 연결의 쓰기 scope 및 프로젝트의 기존 zero-cost Blogger 검토 기록을 읽기 전용으로 확인했다. 토큰이나 계정 비밀값을 출력하지 않았다.
- API `127.0.0.1:8100/health`와 Dashboard `127.0.0.1:3100`은 200 응답. 최신 API/Dashboard/Publication Worker 코드를 프로젝트의 안전한 stop/start 스크립트로 적용했고 Research Worker는 유지했다. Publication Worker heartbeat 정상이며 모드는 `scheduled-auto-manual`, global mode는 `manual`, scheduled Auto는 비활성이다. 대기 중 live Job은 0건이다.
- Worker 실행 레인 변경은 `publication.worker.manual_confirmed_lane_started` append-only 감사 이벤트에 남겼다. 이벤트에는 실행 모드/PID와 예약 Auto 설정 불변 및 Blogger 쓰기 미실행 사실만 기록했다.
- 실제 UI `/imports?open_import_id=c3e35c4f-4d79-4772-879f-0232d8bf400a`의 `다국어·발행` 탭에서 해당 원고와 수동 게시 영역을 확인했다. UI 상태는 `게시 가능 · 품질·출처·SEO 등 미완료 항목은 게시 후 보완 목록에 연결됩니다.`이며 보완 예정 항목 6건이 표시된다. 사용자 승인 체크는 하지 않았고, `Blogger에 공개 게시` 버튼을 누르지 않았다.
- 데스크톱, 모바일, 다크 테마 화면을 확인했다. 390px 목표 모바일 뷰포트에서 document 폭과 viewport 폭이 일치했고 브라우저 콘솔 오류/경고는 0건이었다. 스크린샷은 `.playwright-mcp/` 아래에만 저장되어 커밋하지 않는다.

## 검증

- API 변경 범위 pytest: **60 passed** (`test_post_publication_reviews.py`, `test_migration_runner_guard.py`, `test_publications.py`, `test_blogger_live_policy.py`)
- Ruff: 통과
- Python `compileall`: 통과
- Dashboard ESLint: 통과
- Dashboard TypeScript: 통과
- Dashboard Production Build: 통과
- 실제 브라우저 GET: imports, 상세 import, scheduled first-post 상태 API 각각 200
- 실제 Blogger 공개 게시 및 POST: **실행하지 않음**

## 남은 사용자 작업과 제한

운영자는 위 URL을 열고 원고의 전체 본문과 Blogger 대상/해시를 직접 확인한 뒤 승인자·사유를 입력하고 세 확인 항목을 실제로 체크해야 한다. 그 다음 `Blogger에 공개 게시`를 누르면 정확한 수동 Job/감사 이벤트가 생성된다. 그 후 Worker가 draft 생성과 검증을 진행하고, 대기 간격 이후 공개로 전환한 뒤 원격 상태를 확인한다. 이번 개발 검증에서 이 실제 승인은 대신 수행하지 않았으므로 Publishing Job, postId, 공개 URL은 생성되지 않았다.

## 수정 파일

- `apps/dashboard/app/api/publications/[[...path]]/route.ts`
- `apps/dashboard/app/imports/external-import-workspace.tsx`
- `scripts/056_manual_publication_approval.sql`
- `scripts/migrate.py`
- `scripts/provision-test-database.py`
- `scripts/publication-worker.py`
- `scripts/server-common.ps1`
- `scripts/start-publication-worker.ps1`
- `scripts/start.ps1`
- `scripts/status.ps1`
- `services/api/tests/test_blogger_live_policy.py`
- `services/api/tests/test_post_publication_reviews.py`
- `services/api/tests/test_publications.py`
- `services/api/woori/external_policy.py`
- `services/api/woori/publication_worker.py`
- `services/api/woori/publications.py`
- `docs/development/P5-CODEX-057.md`
