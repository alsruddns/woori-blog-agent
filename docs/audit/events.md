# Audit contract

Audit events include bigint event ID, optional run UUID, event_type, object payload and database timestamp. Runtime role receives SELECT/INSERT only. UPDATE/DELETE/TRUNCATE are additionally blocked by triggers, including for ordinary table-owner operations. Superusers and schema owners can bypass/drop triggers; this is not protection against a privileged database administrator.

Current emitted events: run.queued, run.started, run.completed, run.failed and run.queued on lease recovery with a reason payload. API creation and audit insertion share a transaction. Duplicate idempotency keys return the existing run without another queued event. Worker lease claim/start and completion/final status each share a transaction.

Reserved future event families: keyword, research, content, localization, seo, approval, schedule, publish, settings, performance. Implement their producers before claiming these operations are audited. Corrections append a new event referencing the corrected event ID; never mutate the original. Payloads must use allowlisted fields and never include raw prompts, OAuth tokens, passwords or HTTP authorization headers. Current producers write no user payload.

Permanent retention; no automatic purge. Backups and size monitoring are required. Hash chains/external integrity checkpoints remain future work.
