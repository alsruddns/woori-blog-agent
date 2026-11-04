# P5-CODEX-125 — Blogger 연결 목록과 블로그 발행 정책 관리

- 작업 일시: 2026-11-04 Asia/Seoul
- 브랜치: `develop`
- 시작 HEAD: `dae49a3960f92d6f2433b73c680cb2cad3f63891`
- 변경 사유: Blogger 연결 화면에 과거 OAuth 레코드가 기본 표시되고, `publishing_policies.active`를 변경할 진입점이 발행 차단 메시지에서 분명하지 않았다.

## 변경 전후

- 기본 OAuth 카드에는 저장된 연결 레코드 전체가 표시됐다. 변경 후 실제 연결·블로그 매핑·진행 중 인증만 표시한다. 이전 연결 기록은 DB와 감사 이력에 보존한다.
- 블로그 발행 정책은 기존 언어·정책 화면의 스케줄 폼에서만 저장할 수 있었다. 변경 후 Blogger 연결 관리의 블로그별 기존 정책에 ON/OFF 버튼과 변경 사유 입력을 제공한다.
- 정책 전환 API는 해당 기존 정책의 `active` 값만 변경하고 같은 트랜잭션에 이전값·새값·변경자·사유를 감사 기록으로 추가한다. 비활성 블로그의 정책 ON은 거부한다. 기존 스케줄·언어 매핑·Job은 변경하지 않는다.
- 정책 ON은 콘텐츠 검증을 통과시키지 않는다. OAuth·출처·주장 근거·품질·SEO·사람 검토·정확한 버전의 발행 승인·전역 발행 제한은 계속 적용한다.

## 변경 파일

- `services/api/woori/blogger_routes.py`: 현재 블로그 정책 조회와 정책 ON/OFF API.
- `apps/dashboard/app/api/blogger/[...path]/route.ts`: 새 정책 API의 정확한 경로만 프록시 허용.
- `apps/dashboard/app/blogger/manager.tsx`: 사용 중 연결만 기본 표시, 블로그별 정책 상태·변경 버튼·사유·확인 절차.
- `services/api/tests/test_blogger_policy_controls.py`: 기존 정책만 수정·감사하고 비활성 블로그를 차단하는 검사.
- `docs/development/P5-CODEX-125.md`: 개발 기록.

## 발행 안전 경계

사용자는 품질·출처 검사를 건너뛰고 수동·자동 원고를 바로 게시하도록 요청했다. `AGENTS.md`의 발행 안전 규칙은 사실·근거·권리·품질 미검증 원고의 게시를 금지한다. 따라서 이 부분은 구현하지 않았다. 부족한 각 항목은 기존 적격성 차단 사유와 감사 이력으로 남으며, 실제 검토·수정을 거쳐야 한다. 이 작업에서 실제 Blogger 쓰기·운영 정책 ON 전환은 수행하지 않았다.

## 검증 및 남은 문제

- Backend 정책 전환 단위 검사: 2건 통과. pytest 캐시 쓰기 권한 경고 1건.
- Dashboard lint, typecheck, Backend ruff: 통과.
- DB Migration: 없음.
- 실제 OAuth/발행 정책 값 변경: 없음.
- 실제 Blogger API 쓰기: 0건.
- 실제 게시가 되려면 현재 원고의 품질·출처·검토·발행 승인 조건을 충족해야 한다. 정책 스위치만으로 이 조건을 통과하지 않는다.
- 구현 커밋 및 운영 적용 결과는 후속 Git 로그와 서비스 상태에서 확인한다.

관련 문서: `AGENTS.md`, `docs/development/P5-CODEX-124.md`, `docs/operations/runbook.md`.

## Follow-up: Google Trends volume-priority authoring (2026-11-04)

- Work ID: P5-CODEX-125 follow-up; branch: develop; start HEAD: a8ef505c9242de8303c511bcf5122818b6d817c6. This ID is already used by the Blogger policy-controls entry above; this follow-up is appended to preserve that record.
- Reason: the existing minimum-volume rule rejected observations below the threshold and did not reliably guarantee authoring requests for high-volume observations.
- Change: current-slot observations at or above the persisted threshold (default 5,000) now enter a distinct authoring-priority path after explicit active region/blog mapping and duplicate/idempotency checks. This path does not require editorial score, general-news ranking, or source-count selection to create the research request. It records publication_authorized=false; existing Codex research, evidence, quality, Import, and publication controls remain independent.
- Below-threshold and null-volume observations are passed to the existing general editorial selection; volume alone no longer rejects them. Unknown volume is not coerced to a number. Only current collection slots are considered.
- Dashboard wording now describes the setting as Trends search-volume authoring threshold and explains the two paths and that authoring does not grant publication approval. The existing ON/OFF semantics and 5,000 default are unchanged.
- Migration 088 adds the neutral general-news research category for high-volume topics that have no narrower deterministic taxonomy. The migration is additive and idempotent.
- Changed files: services/api/woori/trend_editorial.py, services/api/woori/research_stages.py, services/api/woori/editorial_taxonomy.py, services/api/tests/test_trend_editorial.py, services/api/tests/test_research_stages.py, apps/dashboard/app/operations/automation/controls.tsx, scripts/088_trends_general_news_category.sql, scripts/migrate.py, this record.
- Verification: focused pytest suite 70 passed; Ruff passed; mypy passed for the three changed backend modules; Dashboard typecheck, lint, and production build passed; git diff --check passed. Blogger writes: 0.
- Read-only operating DB check: current authoring threshold is 5,000 and schema version is 87. Migration 088 was not applied; service/runtime reflection is therefore pending. No historical collection slot was reprocessed.
- Existing Trends schedules, 14-region configuration, publication queue, publication limits, and publication approval were not changed. Reservation/manual authoring flows are unaffected.
- Commit: to be linked by the following Git history after commit. Remaining: apply the additive migration through the approved backup procedure and reflect the code in the local operating services; verify that the live Research Worker loads the new code/settings.
