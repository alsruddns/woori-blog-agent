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
- Change files: `scripts/server-common.ps1`, `scripts/stop.ps1`, `scripts/stop-services.ps1`, `scripts/start-services.ps1`, `scripts/restart-services.ps1`, `scripts/shortcut-action.ps1`, `scripts/apply-verified-changes.ps1`, `scripts/tests/service-lifecycle.Tests.ps1`.
- Validation: PowerShell parser and `git diff --check` passed. Pester lifecycle + stop suites passed (29/29). Repository verification passed its PowerShell tests, Python checks and pytest (87 passed), wheel build, and isolated Dashboard production build. Its reflection phase then safely aborted at the old individual API stop path; it did not stop the service. The new whole-stop path was subsequently run through the existing Desktop link and succeeded.
- Runtime before actual shutdown: Dashboard listener PID 956 (runner 40092; wrapper tree 51592, 51240, 55904), API listener PID 53792 (runner 18012, launcher 36044), Research Worker PID 43420, Publication Worker PID 40220 (launcher 56580). Every tree process was owned by the current Windows user and matched the checkout paths and commands. External established connections and due publication queues were zero.
- Actual Desktop stop result: `Agent 전체 종료.lnk` launched the repository shortcut runner. Both Workers stopped cooperatively. After the legacy grace period, the verified listener PIDs 956 and 53792 exited and their wrappers exited. Request `f5037527fdca491c8422ce17b80b8d80` logged `shutdown_complete`; ports 3100/8100 were free, and no matching Worker processes remained. The success dialog appeared as a `Woori Blog Agent` window and was closed after verification.
- Login suppression check: while the intentional-stop marker was present, running `start-services.ps1` without explicit-user intent printed `Startup skipped` and left all four services stopped. The scheduled task remains enabled/Ready with its user-logon trigger.
- Existing logon task: `WooriBlogAgent-Worker`, enabled, user-logon trigger, task state Ready; the task was not altered.
- Data safety: no database, OAuth, Blogger content, or publication state was modified. No Blogger write was issued. PostgreSQL and unrelated processes are excluded from lifecycle actions.
- Completion: whole start and whole restart shortcut verification remain pending; append their PID, port, HTTP, heartbeat, task, and final commit results after execution.
- Commit hash: see the follow-up development-record commit and `git log -- docs/development/P5-CODEX-068.md` (self-reference is recorded by Git history).
- Related operational evidence: `.runtime/logs/service-lifecycle.log` (local, ignored runtime file).
- Remaining issues: fix the observed dot-source timeout-variable overwrite, make source reflection respect an intentional stop, then complete whole-start and whole-restart shortcut verification.
