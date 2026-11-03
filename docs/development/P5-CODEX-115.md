# P5-CODEX-115 — Pre-job publication failure diagnosis and review controls

- Work ID: P5-CODEX-115
- Work date: 2026-11-03 (Asia/Seoul)
- Branch / base HEAD: `develop` / `22c0011e269fbf72847a5259a68ac057bc2f6790`
- Reason: clarify the 96 pre-Publishing-Job failure records and separate non-writing re-evaluation from explicit publication requests.
- Starting worktree: no tracked user changes; preserved the existing stash and all untracked files.

## Before and after

Before, `publication_monitor.snapshot` listed soft-discarded failure manuscripts as current pre-job failures. It omitted the associated assessment, target, discard, event, and remote-publication evidence. The monitor showed technical reason codes without a safe way to re-evaluate a single record. Reusing the manuscript-discard endpoint to archive a failure would have changed the manuscript's publication eligibility, so history archive/restore now uses separate append-only audit events.

After, the monitor separates active failures from archived failure history, exposes per-record provenance and evidence, and provides bounded individual/bulk re-evaluation that creates no Publishing Job and makes no Blogger request. Failure-history archive/restore appends audit events and does not discard or restore manuscript content. A recheck that has no local blockers only routes an administrator to the existing exact-version publication preflight; it does not enqueue or publish anything.

## Read-only production diagnosis

Database backup was verified before the investigation: `backups/20261103T044716Z.dump` (42,553,086 bytes). Investigation queries ran in a PostgreSQL read-only transaction. No manuscript, Content Version, Publishing Job, publication record, queue, or operational setting was changed.

- Current failure records: 96.
- Unique Import IDs / manuscript groups / Content Versions: 96 / 96 / 96.
- Repeated failure events for those identities: 0.
- Primary recorded causes: `global_publication_mode_mismatch` 89; `collection_predates_policy_activation` 6; `claim_source_verification_unavailable` 1.
- Secondary reason codes also present: `no_supported_body_after_sanitization` 1 and `source_live_verification_missing` 1.
- Classification by recorded cause: re-evaluation may be appropriate after explicit restore and fresh checks 89; historical policy record 6; manuscript/source review required 1. A separate inactive ZH-CN target is also a current publication blocker.
- Current safety: all 96 have manuscript soft-discard status; 0 are active/unarchived. No Publishing Job, retry, Blogger postId, or recorded remote publication state is linked to the 96.
- Latest quality evaluations / `publish_ready=true`: 0 / 0.
- Age: 52 are older than 24 hours; 6 older than 72 hours. Age alone does not discard content.
- Provenance/language: Trends 95, scheduled 1; EN 53, KO 12, JA 30, ZH-CN 1.
- Failure-event time range: 2026-10-31 12:06 to 2026-11-03 13:31 KST.

The 96 records are not a retry queue. All remain publication-prohibited while discarded. The monitor does not automatically restore them or create jobs. Remote Blogger verification is not inferred from the absence of a local record and remains part of the existing publication preflight.

## Changes

- `services/api/woori/publication_monitor.py`: linked current Content Version, quality assessment, Blog/language state, discard history, Publishing Jobs, remote publication evidence, event counts, timestamps, and reason codes. Added root-cause and current-safety classifications plus summary aggregates. The existing failure audit rows are retained.
- `services/api/woori/publication_failure_review.py`: read-only eligibility recheck; checks the exact failure event, import/version link, current version, quality, Blog/language state, discard, existing job, known remote state, current operation settings, scheduled policy scope, and KST daily cap. Writes only an append-only review audit event; no Job and no Blogger write.
- `services/api/woori/publications.py`: bounded administrator endpoints for recheck and failure-history archive/restore; added the archived monitor view.
- `apps/dashboard/app/api/publications/[[...path]]/route.ts`: allowed the two administrator review routes through the same-origin proxy.
- `apps/dashboard/app/publishing/publication-worker-panel.tsx`: summary counts, cause explanations plus technical codes, item provenance/version/assessment/remote state, per-item recheck, bulk recheck, and failure-history archive/restore controls. It does not offer bulk publication.
- `apps/dashboard/app/publishing/publication-manager.tsx`: a locally clear recheck result opens the existing exact-version publication preflight; it does not bypass it.
- `services/api/tests/test_publication_monitor.py`: isolated tests for soft-discard separation, read-only recheck, append-only history archive/restore, root cause vs current safety, and current worker-state behavior.

No database migration was required. Audit events remain append-only. Existing 15-minute global publishing interval, KST daily LIVE cap of 100, six active Blogger mappings, China inactive state, OAuth, scheduled automations, and existing Jobs/publication history were not changed. No actual Blogger API write was performed.

## Validation

- Focused API tests: 10 passed.
- Ruff on changed API modules/tests: passed.
- Mypy on changed API modules: passed.
- Dashboard ESLint: passed.
- Dashboard TypeScript typecheck: passed.
- Isolated production build / service reflection: pending commit and guarded apply step.
- Desktop/mobile browser rendering: pending post-reflection verification.

## Runtime checkpoint before reflection

Read-only service status showed Dashboard PID 4200, API PID 27000, Research Worker PID 31708, Publication Worker PID 8824; both worker heartbeats were fresh. Publication queue showed 0 live queued and 0 live due jobs. API/Dashboard/Publication Worker were running source revisions older than the current checkout. The latest Worker job status was `publication_failed` with `destination_or_method_not_allowlisted`; this is not one of the 96 pre-job records. A guarded service-reflection step is required to apply the new API and Dashboard code; the Worker is included because publication modules changed. No forced termination is permitted.

## Git / remaining work

- Migration: none.
- Operational settings: unchanged.
- Commit: pending.
- Push: pending.
- Remaining: run guarded isolated build and safe service reflection; verify API/Dashboard HTTP, Publication Worker heartbeat/revision and queue; perform desktop/mobile rendering check; append completion audit; finalize this record and push.
