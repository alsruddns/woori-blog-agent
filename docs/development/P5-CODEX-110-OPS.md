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

## Live operation result

- Operations backup remained available at `backups/20261103T011627Z.dump` (41,561,828 bytes; archive catalog verified before migration).
- Migration 082 applied successfully while application services were down. Schema is 82; `automation_controls.revision=16`; global Blogger write interval is 15 minutes; global KST LIVE ceiling is 100; Trends is still ON at 30 minutes. Existing automation controls remain ON (auto manuscript, global auto, Trends auto, scheduled auto, manual publishing); emergency stop remains OFF.
- Graceful stop completed for Publication Worker PID 33016, Research Worker PID 8848, Dashboard PID 24972, and API PID 25944. Both workers finished their current synchronous cycle. Dashboard/API process trees exited; ports 3100/8100 were verified free. PostgreSQL 16, the Crypto cluster, unrelated projects, and the enabled `WooriBlogAgent-Worker` task were not stopped or changed. The task stayed Ready with `LastTaskResult=0`.
- The first two stop attempts safely aborted before any service stop because the orchestrator could not see helpers scoped inside `stop.ps1`. The functions were moved to `server-common.ps1`, and regression assertions were added. A later `-WhatIf` validation propagated ShouldProcess into the nested Pester run and caused 3 mock-only failures; validation was rerun without `-WhatIf`, after services were already stopped and with the intentional-stop marker still set. It did not request a second shutdown.
- Latest committed source passed validation at `69f0e8061df174e1bcf6d9a1377fd7549ba78cce`. PowerShell shutdown tests passed 31/31; change-scope API tests passed 150/150 (one pytest cache permission warning); Ruff, Mypy (8 source files), Dashboard lint/typecheck, isolated production build and Python wheel verification passed. Playwright P110 settings/grid checks passed on both projects (4/4). Operational discard-default checks passed on desktop and mobile (2/2) with non-GET API requests blocked.
- Services restarted from the validated develop checkout. New PIDs: API 1884, Dashboard 18464, Research Worker 36300, Publication Worker 29224. API `/health` and Dashboard `/` returned HTTP 200. Worker heartbeats are fresh. All four services report applied source commit `69f0e8061df174e1bcf6d9a1377fd7549ba78cce`; worker runtime acknowledgements both report policy revision 16 and fresh heartbeat. The task remains Ready and enabled.
- An unauthenticated read of the admin settings endpoint returned 401 and the same-origin proxy returned 403; no authentication boundary was bypassed. Settings were verified from the operations DB and both Worker acknowledgements. Dashboard code is running the same validated commit; its authenticated live settings revision could not be independently read in this session.
- Completion audit was appended as `agent.execution.completed`, audit event ID `311370`, linked to execution ID `3e8b8793-44eb-452c-bb10-27decc987041`; no prior audit event was modified.
- Before/after operating counts are unchanged: Content Groups 275, Content Versions 505, Publishing Jobs 43, verified LIVE records 20, verified Draft records 0, discarded manuscripts 2. There are 0 running/uncertain LIVE jobs and 0 unresolved LIVE write operations. Today's observed KST LIVE count is 0/100 (100 remaining). The existing 15 scheduled automations remain unchanged. No Blogger write API request was made; no test post was created.
- Publication Worker starts with the route priority implementation present in the applied commit, but remains fail-closed at `automatic_publication_suspended`: publication mode is `manual` and `operations_auto_approved=false`. This work did not grant external Blogger write approval or enable production writes. The 15-minute spacing and 100/day limits are persisted and tested; actual publication is not claimed.

## Commits and remaining checks

- `41a56e4` — interval/cap implementation.
- `1952f51` and `5b83725` — graceful shutdown helper scope corrections.
- `69f0e80` — remove redundant test-fixture return that blocked Ruff validation.
- A final documentation-only commit and push will record the final Git state after the operational checkpoint. Browser operational UI checks were made against the local running Dashboard; the automated settings and grid E2E checks use mock API routes, not Blogger writes.

## Shutdown preflight correction checkpoint

- The first shutdown attempt exited before writing the intentional-stop marker or stopping any service. `stop-services.ps1` called `Get-ManagedRunner` and `Get-ManagedTree`, but those functions were scoped only inside `stop.ps1` and were not available to the orchestration script.
- Moved the existing process-tree verification helpers into shared `server-common.ps1`; both scripts dot-source that file. Added a lifecycle regression assertion. No service PID, task scheduler setting, or database state changed during the failed attempt.
- Verification: `Invoke-Pester -Script scripts/tests/service-lifecycle.Tests.ps1` passed 17/17 after the correction.
- The next preflight attempt exposed one more helper (`Get-EstablishedConnectionCount`) that was also local to `stop.ps1`. It exited before stop marker/service mutation for the same scope reason. That helper is now shared as well; the regression assertion covers all three shared preflight functions.
- First committed-source validation completed 31 PowerShell tests and API type/lint checks until Ruff found a pre-existing explicit `return None` in the queue-priority test fixture. Removed the redundant return; this is test-only and does not change queue behavior. The `-WhatIf` run had leaked WhatIf behavior into nested tests, so actual validation is run without `-WhatIf` while the intentional-stop marker remains set; the script validates source but will not restart services in this session.
- Next checkpoint: retry graceful preflight and shutdown, then apply Migration 082 and start from the validated committed checkout.
