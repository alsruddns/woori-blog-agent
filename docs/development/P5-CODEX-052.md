# P5-CODEX-052 — 예약 원고 publish-first 정책

## 작업 기록

- 작업 ID: P5-CODEX-052
- 작업 시각: 2026-10-30 00:42 KST
- 브랜치: `develop`
- 변경 사유: 예약 원고의 사소한 편집·SEO 문제와 검토 상태가 게시 경로를 일괄 차단하는 문제를 줄이고, 게시 후 보완 정책을 기존 검토 기능에 연결한다.
- 변경 목적: 예약 원고만 제한된 자동 보정·적격성 평가·사전 보완 항목 생성 경로를 사용하게 한다. 일반 수동 및 Trends 정책은 유지한다.

## 변경 전후

- 변경 전: 예약 원고에는 사람의 의미 검토와 출처 재사용 조건의 기계적 `allowed` 판정이 일률적으로 요구됐다. 검증 불가 단락을 걷어내 별도 버전으로 구성하는 경로가 없었다.
- 변경 후: 예약 원고 전용 경로가 현재 원문 증거와 claim 연결을 확인하고, 근거를 만족하지 않는 단락·직접 인용·이미지를 새 불변 버전에서 제거한다. 게시 가능한 잔여 본문이 충분하지 않으면 작업을 보류한다. 사람 검토 기록, 일반 `publish_ready`, 일반 Auto 정책은 바꾸지 않는다.
- 사소한 SEO·표현·추가 확인 항목은 기존 schema 53/54의 사후 검토 구조에 작업 연결 사전 행으로 준비한다. 실제 원격 LIVE GET 이후에만 Blogger 게시 기록과 postId에 연결하여 게시 목록에 노출한다.
- 최초 공개 게시의 정확한 원고/버전/hash/blog 승인, 예약 Auto 범위, 인증·대상·중복·한도·비상 정지는 계속 필수다.

## 실제 원고 판정

- 대상 Import: `9bd1706b-5e0a-4cb4-a7fd-d4949b9ecad7` (일본어 예약 원고)
- 읽기 전용 확인: S1–S4는 현재 검토된 출처 카탈로그에 없고, S5만 원문 캡처가 있다. S5에도 주장 연결 가능한 검증 excerpt가 없으며 재사용 조건은 미확인 상태다.
- 원고의 주장 및 출처 연결을 확인할 수 없어 안전하게 유지할 실질 본문이 충분하지 않았다. Worker는 `insufficient_supported_body_after_sanitization` 사유로 보류했다.
- 새 원고 버전, 보완 행, Publishing Job, 게시 승인을 만들지 않았다. 기존 버전·실패 이력은 보존했다.
- 현재 첫 공개 승인 수: 0. 게시 적격 원고: 0. Job: 0. 실제 공개 게시: 0. postId/URL: 없음.

## DB와 운영 상태

- 새 순차 마이그레이션 `055_scheduled_prepublication_reviews.sql`을 추가하고 운영 스키마 55까지 적용했다. 기존 원고·OAuth·감사 행은 수정·삭제하지 않았다.
- 적용 전 프로젝트 백업 스크립트로 백업을 만들고 무결성을 확인했다. 격리 테스트 DB에도 schema 55를 적용했고 운영 DB 접속 격리를 확인했다.
- 예약 Auto 이벤트의 승인 블로그 범위는 기존 4개이며 일일 제한은 현재 1이다. 이 설정은 변경하지 않았다. 일반 운영 모드는 `manual`이다.
- API 8100과 Dashboard 3100은 응답 중이다. `/publishing`은 HTTP 200이며 `예약 Auto` 텍스트를 반환한다.
- Publication Worker는 `--operations-scheduled-auto --continuous`로 실행 중이고 heartbeat가 최신이다. `LiveQueued=0`, `LiveDue=0`, 마지막 작업은 `quality_held`다.
- API의 graceful stop은 활성 loopback 연결이 있어 `scripts/stop.ps1`이 거부했다. 강제 종료나 API 재시작은 하지 않았다. 이번 변경은 API 라우트가 아니라 Worker 경로와 정책이어서 최신 Publication Worker를 정상 재시작해 코드를 적용했다.

## 변경 파일

- `AGENTS.md`
- `docs/operations/content-import.md`
- `docs/operations/scheduled-auto-publish-first-policy.md`
- `scripts/055_scheduled_prepublication_reviews.sql`
- `scripts/migrate.py`
- `scripts/provision-test-database.py`
- `services/api/woori/scheduled_auto_verification.py`
- `services/api/woori/content_imports.py`
- `services/api/woori/publication_worker.py`
- `services/api/tests/test_scheduled_publish_first.py`
- `services/api/tests/test_post_publication_reviews.py`
- 본 개발 기록

## 검증

- 변경 범위 pytest: 69 passed
- Ruff: 통과
- Python compileall: 통과
- `git diff --check`: 통과
- 테스트는 격리된 `woori_blog_agent_test` DB 정책에 따라 실행했다.
- 실제 Blogger 쓰기 호출은 실행하지 않았다.

## 남은 문제

- 이 일본어 원고는 현재 근거로 게시할 수 없다. 검토된 출처 캡처와 핵심 주장별 excerpt/수치 연결, 그리고 본문을 구성할 충분한 검증 가능 근거가 필요하다.
- 첫 공개 게시용 exact-version 승인도 아직 없다. 다만 이 원고는 승인 대상을 만들 수 있는 적격 상태가 아니다.
- API는 실행 중 연결 때문에 안전 종료 스크립트가 중지 요청을 거부하여 재시작하지 않았다. API 프로세스 재시작이 꼭 필요하면 사용자가 API 클라이언트를 정상 종료한 뒤 프로젝트 스크립트로 graceful stop/start 해야 한다.
- Commit SHA와 원격 push 결과는 이 문서 작성 후 Git 기록으로 확인한다.
