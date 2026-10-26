# Audit contract

Audit events include bigint event ID, optional run UUID, event_type, object payload and database timestamp. Runtime role receives SELECT/INSERT only. UPDATE/DELETE/TRUNCATE are additionally blocked by triggers, including for ordinary table-owner operations. Superusers and schema owners can bypass/drop triggers; this is not protection against a privileged database administrator.

Current emitted events: run.queued, run.started, run.completed, run.failed and run.queued on lease recovery with a reason payload. API creation and audit insertion share a transaction. Duplicate idempotency keys return the existing run without another queued event. Worker lease claim/start and completion/final status each share a transaction.

Reserved future event families: keyword, research, content, localization, seo, approval, schedule, publish, settings, performance. Implement their producers before claiming these operations are audited. Corrections append a new event referencing the corrected event ID; never mutate the original. Payloads must use allowlisted fields and never include raw prompts, OAuth tokens, passwords or HTTP authorization headers. Current producers write no user payload.

Permanent retention; no automatic purge. Backups and size monitoring are required. Hash chains/external integrity checkpoints remain future work.

## Multilingual configuration

Migration 002 adds nullable language_code and blog_id foreign keys, preserving old audit rows. Successful inserts/updates on languages, language_profiles, language_capabilities, blogger_blogs, publishing_policies, glossary_entries and category_localizations emit config.<table>.<operation>. Common category registration emits config.categories.insert. Seed languages receive config.languages.seeded events; schema changes emit schema.*.migrated. The API sets transaction-local actor=local_admin; direct DB changes record the role. Trigger errors roll back both settings and events.

Payloads contain entity ID, actor, before/after row fingerprints. They intentionally omit raw policy/glossary text and credentials. Fingerprints support detecting changed configuration but do not reconstruct previous policy values or prove integrity against privileged administrators. No delete endpoint or runtime DELETE privilege exists. General capability verification updates are also unavailable to the runtime API. External verification and publishing producers remain future work.
