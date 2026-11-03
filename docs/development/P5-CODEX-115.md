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
- Age at initial inspection: 52 were older than 24 hours; 6 older than 72 hours. The final recount later showed 53 older than 24 hours. Age alone does not discard content.
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
- `apps/dashboard/e2e/P5-CODEX-115-operational.spec.ts`: desktop/mobile read-only browser check that confirms the failure-history view and blocks all API mutations.
- `services/api/tests/test_publication_monitor.py`: isolated tests for soft-discard separation, read-only recheck, append-only history archive/restore, root cause vs current safety, and current worker-state behavior.

No database migration was required. Audit events remain append-only. Existing 15-minute global publishing interval, KST daily LIVE cap of 100, six active Blogger mappings, China inactive state, OAuth, scheduled automations, and existing Jobs/publication history were not changed. No actual Blogger API write was performed.

## Validation

- Focused API tests: 10 passed.
- Ruff on changed API modules/tests: passed.
- Mypy on changed API modules: passed.
- Dashboard ESLint: passed.
- Dashboard TypeScript typecheck: passed.
- Isolated production build and guarded service reflection: passed.
- Desktop/mobile read-only Playwright rendering: passed (1440px and 390px).

## Runtime checkpoint before reflection

Read-only service status showed Dashboard PID 4200, API PID 27000, Research Worker PID 31708, Publication Worker PID 8824; both worker heartbeats were fresh. Publication queue showed 0 live queued and 0 live due jobs. API/Dashboard/Publication Worker were running source revisions older than the current checkout. The latest Worker job status was `publication_failed` with `destination_or_method_not_allowlisted`; this is not one of the 96 pre-job records. A guarded service-reflection step is required to apply the new API and Dashboard code; the Worker is included because publication modules changed. No forced termination is permitted.

## Initial Git and runtime checkpoint

- Migration: none.
- Operational settings: unchanged.
- At this checkpoint the implementation commit and push had not yet occurred. See final completion state below.

## Final verification and operational reflection

- Final read-only recount through both the repository monitor and live API: 96 distinct Import IDs, manuscript groups, and Content Versions; 0 repeated failure events. Root-cause distribution: 89 `reevaluation_possible` (all recorded as `global_publication_mode_mismatch`), 6 historical-policy records (`collection_predates_policy_activation`), 1 source/manuscript review required (`claim_source_verification_unavailable`). Two secondary evidence codes are retained on the corresponding record(s): `no_supported_body_after_sanitization` and `source_live_verification_missing`.
- Current safety distribution: 95 blocked because the manuscript is soft-discarded; 1 blocked because the ZH-CN target is inactive. All 96 are in archived/discarded history, 0 active pre-job failures, and 0 currently eligible for publication. Each has 0 linked Publishing Jobs, 0 retries, no Blogger postId or verified remote publication state, and no quality evaluation with `publish_ready=true`. The 96 must not be mass restored or retried.
- Read-only settings snapshot remained unchanged at automation Revision 18: Trends ON / 30 minutes, auto manuscript ON, global auto ON, Trends auto ON, scheduled auto ON, manual publishing ON, global Blogger interval 15 minutes, daily LIVE cap 100, emergency stop OFF. The separate automatic-publication operator approval remains OFF and configured mode remains `manual`; this feature does not override it.
- Guarded `scripts/apply-verified-changes.ps1 -Apply -Confirm:$false` completed successfully. Ruff, mypy, 10 focused API tests, wheel build, Dashboard lint/typecheck, and isolated Next production build passed before service stops. The API, Dashboard, and Publication Worker stopped gracefully; the Publication Worker finished its synchronous cycle before exit. No forced termination occurred. The Research Worker remained running because its code was not affected.
- Post-reflection: API health HTTP 200, Dashboard `/publishing` HTTP 200. API and Dashboard report source commit `e39972fa2406c6252c9b1cfebe881dc7f5d46e40`; Publication Worker PID 17108 has a fresh heartbeat and the same applied commit. Automation Revision 18 is acknowledged by both Research Worker PID 31708 and Publication Worker PID 17108 (`policy_applied=true`, engine `automation-controls/3`). The live publication queue remains 0 queued / 0 due.
- Read-only Playwright operational check passed at 1440px desktop and 390px mobile (2/2). It loaded the 96-record archived-failure view, checked no horizontal overflow or browser page errors, and blocked all non-GET `/api/` requests. No Blogger write occurred. Screenshots were saved under ignored `.runtime/` paths.
- Test caveats: the first direct pytest invocation lacked a temporary `ADMIN_TOKEN` and failed during test fixture setup before any test body. Re-run with an ephemeral test-only token passed 10/10. Pytest emitted one cache-directory permission warning unrelated to the tests. Full repository test suite was not run.
- No migration was added. Backup remains `backups/20261103T044716Z.dump` (42,553,086 bytes). Runtime data counts after reflection: 512 Content Versions, 45 Publishing Jobs, 20 publication records, 3 Draft receipts, 123 manuscript discard records. No manuscript, Job, publication record, Blogger connection, OAuth record, or automation setting was changed by P115. Only the required execution-start audit and normal service-lifecycle audit records were appended; failure history stayed intact.
- UI test added: `apps/dashboard/e2e/P5-CODEX-115-operational.spec.ts`. Its read-only guard blocked mutation requests during operational browser verification.
- Completion audit appended as event `315487`, linked to start event `314978`.

## Completion

- Implementation, API and Dashboard operational reflection: complete.
- Existing 96-failure records remain safely archived/discarded; current manual publication preflight still requires an administrator to restore the manuscript using the existing workflow and explicitly request the exact version. Recheck by itself creates no Job and makes no Blogger call.
- Implementation commit: `e39972fa2406c6252c9b1cfebe881dc7f5d46e40`; final documentation/UI-check record commit will be linked by the follow-up Git record.
- Completion audit event: `315487` (start event `314978`).
- Push and remote HEAD verification: pending final documentation commit.
