# P5-CODEX-173: Hide scheduled task consoles

- Date: 2026-11-25 (Asia/Seoul).
- Reason: Startup and recurring project tasks could show Windows console windows.
- Before: The project login and backup tasks launched PowerShell directly with a hidden window option; scheduled research subprocesses did not explicitly request no console.
- After: Project login and backup tasks can launch through a restricted WScript wrapper, which runs only the selected fixed project script hidden and waits for its exit code. Scheduled research, invocation resolution and duplicate broker subprocesses use `CREATE_NO_WINDOW` on Windows. Existing schedules, triggers, enabled states and publication controls remain unchanged.
- Files: `scripts/hidden-task-launcher.vbs`, `scripts/manage-autostart.ps1`, `scripts/register-maintenance.ps1`, `scripts/status.ps1`, `scripts/automation-research-stage.py`, `scripts/resolve-codex-automation-run.py`, `scripts/scheduled_duplicate_check.py`, related tests and this record.
- Validation: Research-stage tests, lifecycle tests, Ruff and an invalid-mode launcher check. Task action verification and service reflection are recorded in the operational audit and Git history.
- Commit: See Git history for this record. Remaining: observe the next actual login and backup trigger to confirm end-to-end behavior; other projects' scheduled tasks are outside this change.
