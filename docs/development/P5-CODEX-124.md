# P5-CODEX-124 — 수동 발행 버튼 및 발행 적격성 조회 오류 수정

- 작업 일시: 2026-11-03 (Asia/Seoul)
- 브랜치: `develop`
- 작업 ID: `P5-CODEX-124`
- 시작 HEAD: `2bb778151671b27fb07ca52931997c013b008043`

## 변경 사유 및 기존 문제

발행 관리 그리드의 `수동 발행` 버튼은 상세 확인 모달을 열었다. 모달의 최신 적격성 조회는 `GET /api/research/content-imports/{id}`를 사용하면서 응답에 존재하지 않는 `publication.targets`를 읽고 있어, 정상 대상 Blogger가 있어도 “발행 검사 결과가 없습니다. Blogger 매핑을 확인하세요.”로 잘못 표시될 수 있었다.

실제 발행 적격성 결과는 `GET /api/publications/scheduled-auto-first-post?import_id=...`가 반환하는 대상별 `manual_publication`에 있다. 운영 상태를 읽기 전용으로 조회한 결과 EN 블로그의 대상 매핑은 확인되었으나, 연결된 OAuth는 없고 수동 발행 차단 사유가 여러 개 남아 있었다. 안전·품질·승인 검사를 우회하지 않았다.

## 변경 목적 및 결과

- 그리드의 수동 발행 버튼 클릭 시 상세 확인 모달 없이 선택한 Content Version을 확인하고 공통 수동 발행 큐 요청을 직접 전송한다.
- 확인용 읽기 API에서 Import와 정확한 Blog ID의 결과를 찾지 못한 경우 구체적인 Blogger 매핑 오류를 표시한다.
- 적격성 차단 항목은 한국어로 표시하고, 차단 상태에서는 POST와 Job 생성을 하지 않는다.
- 적격성 검사를 통과할 때만 버전 해시를 포함한 멱등 수동 LIVE 요청을 전송한다. API/Worker의 기존 정책·OAuth·중복·간격·발행 상한 검사는 유지된다.
- 큐 등록과 실제 Blogger 게시 완료를 별도 상태로 알린다.

## 변경 전 / 변경 후

| 구분 | 변경 전 | 변경 후 |
|---|---|---|
| 수동 발행 UI | 확인 상세 모달 후 요청 | 버튼에서 직접 요청, 상세 모달 미노출 |
| 적격성 조회 | Import 상세 응답에서 없는 `publication.targets` 참조 | 발행 적격성 API의 `targets[].manual_publication` 사용 |
| 매핑 누락 안내 | 검사 결과 없음으로 뭉뚱그림 | 활성 Blogger 대상 미발견 또는 서버 검사 상태 누락을 구분 |
| 부적격 원고 | 모달 안에서만 차단 설명 | 화면 알림으로 이유 표시, 발행 POST 없음 |
| 성공 알림 | 확인 모달의 큐 등록 중심 | 큐 등록 알림과 Worker 최종 상태를 분리 |

## 운영 상태 진단

2026-11-03 읽기 전용 API 조회 기준:

- 활성 Blogger: 6개
- 연결 레코드: `pending=1`, `disconnected=7`
- 활성 Blogger에 연결·검증된 Blogger OAuth: 0개
- 쓰기 Scope가 매핑된 활성 Blogger: 0개
- 진행 중 OAuth 승인 시도: 0개
- Blogger 사용자 신원 확인: 미확인
- 대상 EN 블로그는 등록·활성 상태이며, 오류 원인은 이 블로그 자체가 목록에서 누락된 것이 아니었다.
- 해당 EN Import의 실제 수동 적격성 차단: `blog_connection_unverified`, `blogger_write_oauth_not_verified`, `publication_policy_inactive`, `machine_quality_not_passed`, `reviewed_source_missing`, `evidence_fact_verification_missing`, `research_package_not_reviewed`, `seo_check_not_passed`, `sanitized_blogger_html_missing`, `human_review_pending`, `publication_approval_missing_or_stale`, `publish_ready_disabled`, `write_oauth_not_mapped_to_blog`.

따라서 이 UI 수정만으로 운영 발행을 강행하거나 OAuth 연결 완료로 간주하지 않는다. Blogger 연결 관리에서 앱의 Google OAuth 완료, Blogger ID 읽기 검증, 대상 블로그에 대한 연결 할당을 완료해야 한다. 원고 품질·출처·사람 검토·발행 승인도 각각 충족되어야 한다. 자동 발행과 Codex 예약 발행은 이번 변경에서 수정하지 않았으며 기존 운영 정책을 보존했다.

## 수정 파일

- `apps/dashboard/app/publishing/publication-manager.tsx` — 모달 없는 명시적 행 요청, 올바른 대상별 적격성 API 사용, 원인 번역 및 큐/최종 결과 표시.
- `apps/dashboard/e2e/P5-CODEX-110-grid-publish.spec.ts` — 직접 요청, 차단, HTTP 오류, 매핑 불일치 및 데스크톱/모바일 동작 검증.
- `docs/development/P5-CODEX-124.md` — 작업 기록.

## 테스트

- Dashboard ESLint: 통과.
- Dashboard TypeScript typecheck: 통과.
- Playwright 대상 테스트(데스크톱 1440px + 모바일 390px): 12 통과, 0 실패.
- 테스트 중 Blogger API 쓰기: 0건 (mock된 요청만 사용).
- 초기 Playwright 4개 실패는 변경된 소스가 아닌 기존 3100 운영 서버를 대상으로 실행해 이전 모달이 렌더된 결과였다. 별도 격리 개발 서버 `127.0.0.1:13100`에서 재실행해 위 12개 테스트를 통과했다.
- 운영 DB/설정 변경, OAuth 조작, 실제 Blogger 쓰기: 없음.

## 관련 문서

- `AGENTS.md`
- `docs/development/P5-CODEX-120.md`
- `docs/development/P5-CODEX-118.md`
- `docs/operations/runbook.md`

## 남은 문제

- 현재 앱의 쓰기 OAuth 연결 및 Blogger 매핑이 운영 상태 조회에서 확인되지 않아 어떤 실제 발행도 검증되지 않았다.
- 자동·예약 발행의 기존 승인/품질/출처 차단은 그대로 남아 있다.
- 실제 게시 결과와 OAuth 재연결은 사용자의 앱 OAuth 동의·연결 검증/할당 완료 후 확인 가능하다. 이 작업에서는 OAuth나 게시 권한을 우회하지 않았다.
- 이 작업의 소스는 커밋 후 기존 `scripts/apply-verified-changes.ps1` 절차로 검증·안전 반영한다. 최종 커밋 해시는 저장소 `git log`에서 확인한다.
