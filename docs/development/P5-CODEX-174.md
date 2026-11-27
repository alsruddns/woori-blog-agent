# P5-CODEX-174: Console-free service and worker startup

- Date: 2026-11-27 (Asia/Seoul).
- Reason and prior state: Windows service and worker launch used hidden console processes, which can briefly display a window. Backup subprocesses did not explicitly suppress console creation.
- Change: A `pythonw` helper starts API, Dashboard, Research Worker, Publication Worker and coordinator child processes with `CREATE_NO_WINDOW`, preserving output logs and existing identity, health and heartbeat checks. Scheduled backup subprocesses also request no console. Existing schedules and publication settings are unchanged.
- Files: `scripts/launch-no-console.py`, `scripts/server-common.ps1`, `scripts/start.ps1`, `scripts/start-services.ps1`, `scripts/start-research-worker.ps1`, `scripts/start-publication-worker.ps1`, `scripts/maintenance.py`, `scripts/backup.py`, and `scripts/tests/service-lifecycle.Tests.ps1`.
- Verification: An actual Windows child reported `GetConsoleWindow() == 0` and redirected output successfully; lifecycle/stop suite passed 36 tests and Ruff passed. Startup coordinator tests passed 8 and failed 3; the same 3 failures were reproduced against the unchanged prior coordinator, so they remain unresolved rather than counted as passing.
- Commit: See Git history. Remaining: confirm real user login and subsequent task execution without a visible console; inspect the pre-existing coordinator test failures separately.
