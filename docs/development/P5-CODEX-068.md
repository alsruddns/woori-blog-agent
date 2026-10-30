# P5-CODEX-068 — Windows whole-stop and restart repair

## Work record

- Work ID: P5-CODEX-068
- Date: 2026-10-30 (Asia/Seoul)
- Branch: `develop`
- Reason: Desktop whole-stop and whole-restart shortcuts left all four services running because legacy API/Dashboard processes did not implement the newer stop-file protocol.
- Before: the lifecycle log recorded `listener_owner_not_verified_for_this_checkout`, `legacy_process_has_no_identity_bound_stop_channel`, and `restart_aborted_on_stop`. Logon startup also recorded a port conflict against the already-running API.
- After (implementation): whole-stop verifies the actual listener, exact checkout command/path, manifest runner, process tree, process owner, start identity, and active connections. It requests cooperative stop where available; legacy API/Dashboard trees get a bounded, PID/start-time/owner-rechecked fallback after the grace period. Workers remain cooperative-only.
- Session recovery: an intentional-stop marker is bound to checkout, Windows user, and logon session. Logon startup skips in that same session; explicit Start/Restart shortcuts clear the marker. The registered `WooriBlogAgent-Worker` logon task is preserved.
- Restart: records old service PIDs, requires verified shutdown and free ports, checks the project PostgreSQL database, starts all services, then verifies HTTP 200, fresh Worker heartbeats, combined Publication mode, and changed PIDs.
- Shortcut feedback: hidden PowerShell remains; stop/restart success or failure opens a visible result dialog and writes details to `.runtime/logs/service-lifecycle.log`.
- Change files: `scripts/server-common.ps1`, `scripts/stop.ps1`, `scripts/stop-services.ps1`, `scripts/start-services.ps1`, `scripts/restart-services.ps1`, `scripts/shortcut-action.ps1`, `scripts/tests/service-lifecycle.Tests.ps1`.
- Tests so far: PowerShell parser passed for all changed scripts; Pester service lifecycle + stop suites passed (29/29); `git diff --check` passed. Full `apply-verified-changes.ps1 -Apply` and live shortcut run are pending.
- Runtime baseline before change: Dashboard listener PID 956, API PID 53792, Research Worker heartbeat PID 43420, Publication Worker PID 40220. Dashboard and API manifest runner PIDs were 40092 and 18012. All were owned by the current Windows user, exact checkout command paths matched, and external established connections/queued publication jobs were zero.
- Existing logon task: `WooriBlogAgent-Worker`, enabled, user-logon trigger, task state Ready; the task was not altered.
- Data safety: no database, OAuth, Blogger content, or publication state was modified. No Blogger write was issued. PostgreSQL and unrelated processes are excluded from lifecycle actions.
- Completion: update this record with actual before/after PIDs, ports, health, heartbeat, task state, and final commit after live verification.
- Commit hash: see the follow-up development-record commit and `git log -- docs/development/P5-CODEX-068.md` (self-reference is recorded by Git history).
- Related operational evidence: `.runtime/logs/service-lifecycle.log` (local, ignored runtime file).
- Remaining issues: live process shutdown/restart verification is pending.
