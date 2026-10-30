# P5-CODEX-067 — Windows desktop service shortcuts and background lifecycle

## Work record

- Work ID: P5-CODEX-067
- Work date: 2026-10-30 (Asia/Seoul)
- Branch: `develop`
- Reason: provide desktop entry points for the four local services and safely manage them without keeping a PowerShell console open.
- Before: the login task and service scripts existed, but the publication startup lane used scheduled-auto only; no desktop shortcuts or single-action stop/restart entry points existed. API and Dashboard children did not have a verified cooperative shutdown channel.
- After: the existing login task is preserved; eight current-user desktop shortcuts call the project lifecycle scripts through a hidden PowerShell launcher. API and Dashboard launchers expose a per-process, nonce-bound stop request; workers keep their existing cooperative shutdown. Whole stop processes publication worker, research worker, Dashboard, then API, and stops before HTTP dependencies if a worker remains active. Whole restart starts only after full graceful stop succeeds.

## Behavior and safety

- Publication startup uses the verified `scheduled-auto-and-manual` mode. Startup is idempotent only when an exact-checkout process and fresh matching heartbeat are found.
- API and Dashboard stop requests are bound to the recorded PID, checkout, service name, and random process instance ID. A stale, mismatched, reparse-point, or oversized request is rejected. No force termination is used by the whole-stop or whole-restart shortcut.
- Port owners and worker identities are checked against this checkout. Other project processes are left untouched.
- The service identity check handles Windows' venv launcher shim, where the process image is the base `python.exe` while the command line explicitly names this checkout's `.venv\Scripts\python.exe`.
- Shortcut actions and lifecycle transitions append sanitized records to `.runtime/logs/service-lifecycle.log`.
- The existing `WooriBlogAgent-Worker` logon task is not duplicated or removed.

## Files

- Updated `scripts/start-services.ps1`, `scripts/start.ps1`, `scripts/start-publication-worker.ps1`, `scripts/server-common.ps1`, `scripts/run-api.ps1`, `scripts/run-dashboard.ps1`, and `scripts/stop.ps1`.
- Added `scripts/api-service.py`, `scripts/dashboard-service.js`, `scripts/stop-services.ps1`, `scripts/restart-services.ps1`, `scripts/shortcut-action.ps1`, and `scripts/create-desktop-shortcuts.ps1`.
- Added lifecycle regression coverage in `scripts/tests/service-lifecycle.Tests.ps1`.
- Updated `scripts/tests/stop.Tests.ps1` so test lifecycle calls cannot append fixture PID events to the operational lifecycle log.
- Added this development record.

## Verification

- PowerShell parser, Node syntax check, Python compilation, 27 Pester lifecycle tests, `git diff --check`, isolated Python wheel verification, and isolated Production Build passed. Runtime source validation recorded the current commit, then the explicit restart prompt was declined. No current service process was changed.
- A hidden whole-start shortcut invocation against already healthy services verified exact process ownership, HTTP health, fresh Worker heartbeats, and idempotent no-duplicate behavior.
- All four individual start shortcuts were launched hidden; each returned successfully and the service PIDs remained unchanged.
- Whole-stop/restart are validated by tests and ownership-aware code inspection, not run against live services during this task.
- Test fixtures previously emitted four synthetic API PID events into the local lifecycle log. They are preserved; a later `test_log_fixture_correction` event identifies them as test-only records. New test runs leave that log unchanged.
- The existing login task's name, enabled state, logon trigger, and project action are checked after changes. One manual trigger while services were already running failed closed at API port ownership (`port_conflict`, Task Scheduler result `1`) because the limited task context could not prove the active API listener belonged to this checkout. No service was changed. A real reboot with free ports was not performed.
- Runtime state, shortcut paths, actual service PIDs/mode, and logs are recorded in the completion report.

## Audit and outcome

- Lifecycle attempts use append-only local JSONL audit in `.runtime/logs/service-lifecycle.log`; no operational database, OAuth, Blogger, or content records are changed by shortcut management.
- Commit hash: recorded by `git log` after commit.
- Related runtime marker: `.runtime/validated-source.json` is written only after committed-source validation succeeds.
- Remaining limitation: service instances already running before this change keep their current process image until normally stopped. No live service is forcibly replaced. Stop-all and restart-all links were not executed against live services to avoid interrupting active work.
