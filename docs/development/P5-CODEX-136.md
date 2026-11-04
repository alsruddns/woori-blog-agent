# P5-CODEX-136 — Blogger 자동 발행 모드 AUTO 활성화 점검

- 작업 일시: 2026-11-04 (Asia/Seoul)
- 브랜치: `develop`
- 시작 HEAD: `cce75cecf4a14333d4b67c4a10dd21afa531dd64`
- 작업 시작 감사: PostgreSQL `agent.work.started`, ID `353127`
- 결과: **활성화 미실행**. 현재 운영 상태가 요청서의 “AutoPolicyActive=true / 기존 공개 발행 승인 ON”과 일치하지 않고, 외부 공개 쓰기 승인이 없으며, 기존 mode API가 `auto` 저장을 거부한다. fail-closed 상태를 유지했다.

## P5-CODEX-134 및 현재 설정

- P5-CODEX-134에서 확인한 schema 90은 authenticated `/admin/operations/dashboard`에서도 확인했다. `automation_controls` revision은 22이다.
- `automation_controls`: `auto_publishing_enabled=true`, `manual_publishing_enabled=true`, `auto_mode=publish`, `automatic_publication_operator_approved=true`, Trends/Scheduled route flags=true, emergency stop=false, global interval 15분, global KST LIVE cap 100건, 승인 Blog IDs 6개. 이 승인 플래그 자체는 ON이다.
- 동일 revision의 현재 worker 정책 응답은 `automatic_publication_approval.effective=false`, `AutoPolicyActive=false`이다. 구체적 차단 사유: `external_blogger_public_write_approval_missing`, `blogger_write_mode_not_public_write_approved`, `legacy_publication_operations_approval_unavailable`.
- `publication_mode_settings` 글로벌 row: `configured_mode=manual`, daily limit 100, minimum interval 15분, emergency stop=false, `operations_auto_approved=false`, `blogger_write_mode=manual_only`, Blogger API restriction=false. 전역 mode row만 있으며 블로그별 override는 없다. 유효 mode 우선순위는 blog → language → global이다.
- 기존 Scheduled Auto append-only event ID 4는 enabled, daily limit 100, 기존 활성 Blogger 6개 승인이다. 이는 예약 경로의 scoped approval이며 일반 자동 공개 쓰기 승인으로 간주하지 않는다.
- `AutoMode`는 Publication Worker status상 `manual`; 목표 `auto`로 바꾸지 않았다. automation-control의 `auto_mode=publish` 값은 이미 켜져 있으나, legacy publication mode와 외부 승인 게이트가 차단한다.

## OAuth, Blogger 범위 및 비용/공개 승인

- 기존 활성 Blogger는 6개 (EN, KO, JA, DE, pt-BR, VI)이며 각 등록 Blog ID와 `blogger_blogs.oauth_connection_id` 연결을 유지한다. 현재 OAuth connection은 `connected`이고 scope에 `https://www.googleapis.com/auth/blogger`가 있다. `zh-CN`은 활성 Blogger가 아니다.
- 현재 DB `automatic_publication_operator_approved=true`와 OAuth write scope는 각각 운영 승인 플래그와 토큰 scope만 보여준다. 외부 공개 발행 전용 `external.blogger.public_publish.approved` attestation은 현재 없다. 기존 zero-cost attestation은 공개 게시 권한을 포함하지 않는다.
- `docs/operations/zero-cost-policy.md`는 Google Cloud Billing 연결과 해당 프로젝트 Blogger API quota/usage를 확인하지 못했다고 기록한다. OAuth/Blogger GET 성공은 Billing 상태, 할당량 여유 또는 공개 쓰기 성공 증거가 아니다. 이 작업에서 Cloud Console이나 Blogger 외부 쓰기 요청은 하지 않았다.

## 관리 경로 및 안전 확인

- 기존 인증 관리 경로 `PUT /admin/publications/mode-settings`를 확인했다. 구현은 `authoring_only`와 `manual`만 허용하고, `auto`는 `409 authoring_only: new operations approval and safety review required`로 거부한다. 따라서 기존 경로로 요청한 `AutoMode=auto`를 저장·적용할 수 없다.
- 기존 유효 자동 승인 경로도 공개 발행 attestation, `public_write_approved` mode 및 legacy operations approval이 빠져 있어 현재 AutoPolicyActive를 만들 수 없다. 이러한 값이나 공개 승인 이벤트를 임의로 작성하지 않았다.
- 전체 worker API snapshot은 publication worker revision 22 적용을 확인했다. Publication Worker PID 22980 heartbeat fresh, execution mode `scheduled-auto-manual-trends`. 재기동하지 않았다.
- 큐: queued/due LIVE 0, 전체 queued publication job 0. Historical jobs는 succeeded 30, failed 19, blocked 3이며 기존 결과를 복원·재등록하지 않았다. `publishing_records` 27건을 보존했다.
- 예약 원고: `chatgpt_scheduled_export` Import 24건 모두 `awaiting_human_review`, `generation_ready=false`, `publish_ready=false`; 기존 큐에 들어 있지 않다. 대량 재발행하지 않았다.
- 기존 common policy와 worker lane 우선순위 scheduled → manual → Trends, 중복 방지, Blogger API 제한·간격 정책을 바꾸지 않았다.

## 작업 결과와 남은 조건

- 설정 변경: 0. AutoMode `manual` 유지, operator approval flag 기존 `true` 유지, `AutoPolicyActive=false` 유지, revision 22 유지.
- Worker 재기동: 없음. heartbeat 정상, 적용 revision `9ff7158d685a93842cbe13a478c6f825d4a99761`.
- 실제 Blogger POST/PATCH/DELETE 및 초안 생성: 0건. 게시 기록 초기화/변경: 0건. 테스트 게시·초안: 0건.
- 유지값: minimum interval 15분, global KST LIVE cap 100건, ScheduledDailyLimit 100건/6개 승인 블로그, zh-CN 제외, existing worker priority and publication records.
- 이번 작업은 fail-closed preflight이며 코드 수정·schema migration·runtime setting 변경은 없다. 테스트는 운영 데이터에 쓰지 않는 조회만 수행했다.
- Append-only audit: `agent.work.started` ID `353127`; `agent.work.completed` ID `353136` records `activation_not_applied_preconditions_blocked` and the exact effective blockers.
- Auto 활성화를 계속하려면 프로젝트 소유자가 Cloud Console에서 Blogger API quota/Billing 상태를 확인하고, 공개 LIVE 자동 발행의 별도 승인과 mode 관리 경로를 확정해야 한다. 이후 해당 승인·모드가 기존 시스템의 지원된 관리 경로로 기록될 때만 진행할 수 있다.
- 최종 Git 상태/commit은 이번 기록을 커밋한 뒤 아래에 연결한다.


## User-authorized follow-up (2026-11-04, Asia/Seoul)

- Follow-up start HEAD: `8e5a2a160fffde233ba9967f32f46ff4cb52fe44`; branch `develop`. Start audit event: `agent.work.started` ID `354235`.
- The effective blockers were the append-only Blogger public-publish approval lookup requiring an event that did not exist; schema 42 fixed `operations_auto_approved` to false and its identity trigger protected that field; schema 75 fixed `blogger_write_mode` to `manual_only`; and `PUT /admin/publications/mode-settings` rejected every `auto` request before checking for a valid scoped approval.
- Added `POST /admin/automation-controls/approve-public-live` and the authenticated same-origin Dashboard control. It requires actor, reason, exact six active OAuth-connected Blog IDs, explicit LIVE confirmation, explicit Billing/quota-reviewed confirmation, current revision, unchanged policy limits, an empty live queue/in-flight operation set, and all 24 scheduled Imports still `awaiting_human_review`. It appends the public-write approval and operator/mode audit events in the existing immutable `audit_events` ledger.
- The user confirmed Blogger API Billing, quota and cost review is complete and approved public LIVE automatic publishing for EN, KO, JA, DE, pt-BR and VI. The recorded scope explicitly denies zh-CN and does not require an additional Cloud Console public-publishing approval. Paid AI APIs remain blocked.
- Scope-bound checks now compare the public approval Blog IDs with the current six automatic Blog IDs at the mode-settings API, automation snapshot, Worker status, Trends capability and automatic Blogger wire admission. Existing quality, rights, duplicate, source and exact-version manual gates remain active. Activation rotates the current auto, scheduled and Trends epochs/cutoffs; it does not reauthorize old Jobs or Import records.
- `AutoPolicyActive` now reports true only after global auto mode, legacy/write gates, the current 15-minute/100-per-KST-day limits, scheduled daily limit 100, exact six connected OAuth mappings, clear emergency/API restriction gates, approval scopes, and matching fresh Publication Worker heartbeat/revision acknowledgement all agree.
- Read-only operations preflight at schema 90/revision 22 found 0 queued/running/uncertain LIVE Jobs, 0 pending Blogger write operations, 0 requested LIVE attempts, 24/24 scheduled export Imports awaiting human review, and exactly six active connected Bloggers with Blogger OAuth scope. Existing Jobs were terminal only; last publication record and queues were not reset. Research and Publication Workers were healthy and untouched during code preparation.
- Operations backup archive catalog validation passed. `scripts/restore-rehearsal.py` restored schema-90 snapshot counts into its owned temporary database, verified audit immutability, and removed only that temporary restore database. Migration 091 then applied to the operations DB; it changes only allowed policy values/identity protection and appends a schema audit event. Operational approval settings have not yet been applied at this point in the record.
- Isolated test database `woori_blog_agent_test` advanced to schema 91. API validation: 142 targeted tests passed; Ruff and mypy passed. Dashboard ESLint and TypeScript typecheck passed. Pytest emitted one pre-existing cache-directory permission warning; it did not fail tests. No test post, draft or Blogger write was made.
- Code/runtime reflection and the audited approval API call are pending. Final Worker status, revision, unchanged 24 Import states, Blogger write count, final commit and push result will be appended after deployment and runtime verification.
- Service reflection classification narrows these publication-control modules to API and Publication Worker; Research Worker is not restarted because its collection/authoring code path is unchanged. No process is force-stopped.
