# Audit contract

Audit events include bigint event ID, optional run UUID, event_type, object payload and database timestamp. Runtime role receives SELECT/INSERT only. UPDATE/DELETE/TRUNCATE are additionally blocked by triggers, including for ordinary table-owner operations. Superusers and schema owners can bypass/drop triggers; this is not protection against a privileged database administrator.

Current emitted events: run.queued, run.started, run.completed, run.failed and run.queued on lease recovery with a reason payload. API creation and audit insertion share a transaction. Duplicate idempotency keys return the existing run without another queued event. Worker lease claim/start and completion/final status each share a transaction.

Migration 033 adds append-only `publication_approval_events`. The authenticated research API emits `article.publication_approval.recorded` with approval event, content/evaluation/editorial version IDs, actor, exact body hash, action, and explicit `live_blogger_write=false` / `publish_ready=false`. A revocation is a new event referencing the approval it cancels. The actor label is supplied by the local administrator; the database records user intent, not an independently verified identity.

Reserved future event families: keyword, research, content, localization, seo, approval, schedule, publish, settings, performance. Implement their producers before claiming these operations are audited. Corrections append a new event referencing the corrected event ID; never mutate the original. Payloads must use allowlisted fields and never include raw prompts, OAuth tokens, passwords or HTTP authorization headers. Current producers write no user payload.

Permanent retention; no automatic purge. Backups and size monitoring are required. Hash chains/external integrity checkpoints remain future work.

## Multilingual configuration

Migration 002 adds nullable language_code and blog_id foreign keys, preserving old audit rows. Successful inserts/updates on languages, language_profiles, language_capabilities, blogger_blogs, publishing_policies, glossary_entries and category_localizations emit config.<table>.<operation>. Common category registration emits config.categories.insert. Seed languages receive config.languages.seeded events; schema changes emit schema.*.migrated. The API sets transaction-local actor=local_admin; direct DB changes record the role. Trigger errors roll back both settings and events.

Payloads contain entity ID, actor, before/after row fingerprints. They intentionally omit raw policy/glossary text and credentials. Fingerprints support detecting changed configuration but do not reconstruct previous policy values or prove integrity against privileged administrators. No delete endpoint or runtime DELETE privilege exists. General capability verification updates are also unavailable to the runtime API. External verification and publishing producers remain future work.

## Phase 2 이벤트
- oauth.started / connected / state.rejected / refreshed / refresh.failed / failed / disconnected / cancelled.
- blogger.id.verified / disconnected, blogger.api.requested / succeeded / failed / retry / blocked.
- blogger.write.requested / succeeded / failed / duplicate_blocked는 mode=mock만 기록한다.
- config.language_execution_limits.insert/update, content.version.created, operations.backup.completed/warning.

API 호출 로그 blogger_api_calls도 append-only다. OAuth payload는 내부 연결 UUID와 안전한 오류 분류만 보관한다. 토큰·verifier·state 원문·인증 코드·원문 외부 오류는 넣지 않는다. 연결 해제는 설정 변경과 동일 트랜잭션으로 감사한다. 토큰 갱신 실패는 상태 변경을 커밋한 후 안전한 오류를 반환한다. 외부 요청과 감사 사이의 프로세스 중단은 요청 기록만 남을 수 있으며 성공을 추정하지 않는다.
