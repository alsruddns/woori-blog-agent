# P5-CODEX-110-OPS — 15-minute publication interval and global LIVE ceiling

## Work record

- Work ID: `P5-CODEX-110-OPS`
- Started: 2026-11-03 10:17 KST
- Branch: `develop`
- Starting HEAD: `ffb42d6904a486fa0920e9123fb8be929096fbdb`
- Reason: apply the requested global Blogger write interval of 15 minutes and a shared 100 LIVE posts per KST day, while reflecting the P110 queue ordering in the running Publication Worker and restarting only this checkout's application services gracefully.
- Prior issue: persisted interval was 30 minutes, the schema/API rejected values below 30, and daily limit reporting used a hard-coded 50. LIVE decisions had no database-backed configurable 100-post global ceiling.
- Before: Trends collection ON at 30 minutes; Codex authoring ON; global/Trends/scheduled auto controls ON; manual publishing ON; emergency stop OFF; interval 30; schema 81; settings revision 15.
- Target after: preserve all existing route toggles and emergency-stop state; Trends remains 30 minutes; shared Blogger write interval becomes 15 minutes; shared KST-day LIVE ceiling becomes 100.

## Operational pre-change evidence

Read-only inspection on the operations database `woori_blog_agent` found:

- The four active Blogger targets are EN, KO, JA and ZH.
- No due/running/uncertain LIVE Publishing Job and no pending/uncertain LIVE write operation existed before shutdown. There was one historical queued Trends Draft Job without an origin grant; it is retained and is not made eligible by this work.
- Worker heartbeats were fresh: Research Worker PID 8848 and Publication Worker PID 33016. The Publication Worker reported no live queue items, `AutoPolicyActive=False`, and `automatic_publication_suspended`.
- The global publication mode remained `manual`; `operations_auto_approved=false`, emergency stop was false, and no active external Blogger write was in progress. This work does not create or alter Blogger write approval.
- Pre-change data counts: Content Groups 275; Content Versions 505; Publishing Jobs 43; verified LIVE records 20; verified Draft records 0; discarded manuscripts 2; audit events 137,824 before this execution's start event.
- Existing 15 Desktop reservation automations were not changed.

## Database backup

- Backup created before the operations migration: `backups/20261103T011627Z.dump` (41,561,828 bytes).
- `scripts/backup.py` verified the archive catalog. A restore rehearsal was not run.
- Migration 082 is additive. It sets the global interval default/current value to 15, permits 15–1440, adds `global_daily_live_publish_limit` default/current 100, increments the automation settings revision, and appends configuration/schema audit events. It does not change Trends interval or route toggles.

## Implementation

- The LIVE/Draft-aware Blogger write gate reads the current database interval immediately before each write. All write modes continue to share the same advisory lock and interval. The daily LIVE ceiling is enforced inside that lock for `create_live` and `publish_draft`; Draft creation is excluded from the LIVE count but still uses the shared write interval.
- The daily count is a distinct Blog ID + Blogger post ID union of verified local LIVE records and successful, verified write audit records, bounded by explicit `Asia/Seoul` day start/end. Pending or uncertain LIVE write operations block subsequent LIVE writes pending reconciliation.
- Publication Worker prechecks read the configured global cap and count only verified LIVE records. At a reached global or existing per-language daily cap, a job stays queued and is deferred to the next KST midnight with an audit event; it is not deleted or replayed. Draft jobs do not consume the LIVE ceiling.
- The operations and publication APIs expose the persisted daily cap and minimum interval. Dashboard shows the dynamic `today/100` count and remaining capacity; the automation control keeps operator-editable interval input with a 15-minute lower bound. The 30-minute Trends cadence remains independent.
- P110's existing dynamic queue order remains scheduled Codex → explicit manual → Google Trends; Trends ties remain EN → KO → JA → ZH. This change does not re-create, delete, or reprioritize already claimed work.
- Fixed a shutdown-script ordering defect: `stop-services.ps1` previously stopped the API before checking all service ownership/external connections. It now performs both HTTP-service preflights before writing the stop marker or stopping any service.
- No Blogger POST/PATCH/PUT/DELETE was performed. Existing publication approvals and external policy gates remain unchanged.

## Files changed

- `scripts/082_global_daily_live_limit_and_15m_interval.sql`
- `scripts/migrate.py`, `scripts/provision-test-database.py`
- `scripts/stop-services.ps1`, `scripts/tests/service-lifecycle.Tests.ps1`
- `services/api/woori/automation_controls.py`, `blogger_writes.py`, `publication_daily.py`, `publication_worker.py`, `operations_dashboard.py`, `publications.py`
- `services/api/tests/test_automation_controls.py`, `test_blogger_live_policy.py`, `test_dashboard_read_models.py`, `test_publication_daily.py`, `test_publication_interval.py`
- `apps/dashboard/app/operations/automation/controls.tsx`, `apps/dashboard/app/page.tsx`
- `apps/dashboard/e2e/P5-CODEX-103-controls.spec.ts`, `P5-CODEX-106-controls.spec.ts`, `P5-CODEX-110-controls.spec.ts`
- `docs/development/P5-CODEX-110-OPS.md`

## Verification completed before operations migration

- Isolated test database provisioned and verified at schema 82; its interval is 15, its global LIVE limit is 100, and Trends remains 30 minutes.
- Focused API tests: 76 passed.
- PowerShell lifecycle tests: 17 passed, 0 failed.
- Ruff: passed.
- Mypy on the five changed API modules: passed.
- Dashboard typecheck: passed.
- Dashboard ESLint: passed.
- A pytest cache permission warning appeared; it did not affect test results.

## Live operation status

The following is intentionally left for the post-migration restart checkpoint and will be completed with observed results before finalization:

- Graceful stop outcome and stopped PIDs
- Operations migration result and final revision
- Startup source validation and full application restart outcome
- New API/Dashboard/Research Worker/Publication Worker PIDs and health/heartbeat revisions
- Final operation-data counts and KST LIVE usage
- Browser check at 1440px and 390px
- Final test summary and Git commit/push hashes

No LIVE publication is being exercised as part of the restart. Actual Blogger write authorization remains separately gated; restarting services does not grant that authority.

## Shutdown preflight correction checkpoint

- The first shutdown attempt exited before writing the intentional-stop marker or stopping any service. `stop-services.ps1` called `Get-ManagedRunner` and `Get-ManagedTree`, but those functions were scoped only inside `stop.ps1` and were not available to the orchestration script.
- Moved the existing process-tree verification helpers into shared `server-common.ps1`; both scripts dot-source that file. Added a lifecycle regression assertion. No service PID, task scheduler setting, or database state changed during the failed attempt.
- Verification: `Invoke-Pester -Script scripts/tests/service-lifecycle.Tests.ps1` passed 17/17 after the correction.
- Next checkpoint: retry graceful preflight and shutdown, then apply Migration 082 and start from the validated committed checkout.
