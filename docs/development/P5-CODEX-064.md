# P5-CODEX-064 — Blogger write capability and automatic-publication recovery

- Work date: 2026-10-30 (Asia/Seoul)
- Branch: `develop`
- Reason: the live-write status was hard-coded false, the publication worker heartbeat did not expose its lane, and automatic holds/failures were not traceable from manuscript and publication lists.
- Before: operations schema 57; Publication Worker heartbeat had no execution mode; the worker process was running but the diagnostic could not establish its live lane. There were zero live and scheduled jobs and no verified Blogger public post.
- After: additive schema 58 records the worker lane; capability status is derived from a fresh heartbeat, the enabled scoped scheduled policy, approved blog/OAuth mapping, emergency-stop state and the existing zero-cost owner policy. Manual confirmed dispatch remains a separate lane. No global Auto setting was changed.

## Changes

- Added additive migration 058 for `worker_heartbeats.execution_mode`; historical heartbeats and audit rows remain intact.
- Connected the Publication Worker mode to heartbeat and worker-status output. The scheduled Auto and exact user-confirmed manual lanes remain separate.
- Added append-only `publication.auto_failure.recorded` and `.cleared` transition events for scheduled eligibility holds, duplicate uncertainty, policy holds, queueing, worker eligibility failures, Blogger write failures, and verified publication. Events carry the import/version/blog/job, stage, reason codes, retry count, timestamp, and manual-recovery availability without secret values.
- Exposed the active failure state in import detail and import lists; added the `자동발행실패` publication view with stage/reason, retry count, direct manuscript navigation, and manual recovery entry point. Original generation provenance is unchanged. A manual request is still created only through the user's explicit confirmation flow.
- Allowed the existing manual publishing request path to recover an imported scheduled/Trends item without rewriting its origin. It still checks the latest version, sanitized body, target blog, OAuth scope, duplicate state, emergency stop, and user-bound title/body/HTML hashes.
- Updated operational diagnostics to report the scoped live capability and removed the obsolete claim that a separate first-post event is required for the scheduled lane. General quality/rights/evidence values were not changed.
- Updated the verified-reflection script to restart the Publication Worker in `scheduled-auto-manual` mode so the explicitly confirmed manual recovery lane remains available alongside scoped scheduled Auto.

## Data, runtime, and verification

- Created and validated a project backup with `scripts/backup.py` before migration.
- Applied migration 058 through the existing migration runner; operations schema is now 58. The dedicated isolated test DB was provisioned through schema 58.
- Publication Worker PID 53164 was stopped through `scripts/stop.ps1` after its cycle completed; PID 47840 was started through `scripts/start-publication-worker.ps1 -Mode scheduled-auto-manual`. No other worker was stopped.
- Focused API tests: 40 passed. Python compile check passed. Dashboard lint and typecheck passed after the final UI typing adjustment.
- Follow-up changed-file verification: publication/import/worker API regressions passed (61 tests); MyPy and Ruff passed for the changed API modules. Nullable DB reads now fail with explicit service errors rather than unchecked indexing, and the worker restores signal handlers with the correct signal type.
- Live Blogger queue at the verified snapshot: 0 jobs; no Blogger public POST was made and no public URL/postId was created. No eligible publication was fabricated. The worker now reports its execution lane; actual dispatch remains gated by the existing Blogger operation/owner policy and eligible jobs.
- Manual publishing remains an explicit user click; this development task did not submit a public-post request.

## Files

- `scripts/058_publication_worker_mode.sql`
- `scripts/migrate.py`
- `scripts/provision-test-database.py`
- `scripts/apply-verified-changes.ps1`
- `services/api/woori/worker.py`
- `services/api/woori/publication_worker.py`
- `services/api/woori/publications.py`
- `services/api/woori/content_imports.py`
- `services/api/woori/research_routes.py`
- `services/api/tests/test_publications.py`
- `services/api/tests/test_post_publication_reviews.py`
- `apps/dashboard/app/publishing/publication-manager.tsx`
- `apps/dashboard/app/imports/external-import-workspace.tsx`

Commit hash is recorded in the subsequent Git history entry for this document. No operating content, OAuth credential, quarantine/rejected file, or audit event was deleted or rewritten.

## Remaining

- No eligible automated manuscript/job existed during this run; therefore there is no actual Blogger post URL or remote post ID to report.
- A scheduled manuscript held by evidence/eligibility checks remains held until its evidence qualifies. A manual recovery request must be explicitly confirmed in the manuscript detail and may still be blocked by hard safety/connection checks.
- Long-running repeated unattended publication has not been demonstrated by this one maintenance run.
