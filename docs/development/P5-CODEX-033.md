# P5-CODEX-033 — Publication Worker continuous runtime

- Work ID: P5-CODEX-033
- Date: 2026-10-29 (Asia/Seoul)
- Branch: `develop`
- Reason: The one-shot publication command returned `processed=false` without distinguishing queue state from policy-disabled lanes, and no continuous Publication Worker service entry point existed.

## Diagnosis (read-only operational DB)

- `--operations-mock-only` polls only due jobs with `simulation_only=true` and `adapter_type='fake'`. It does not inspect or dispatch the real Blogger lane.
- At inspection: fake jobs: 1 `blocked/quality_held`, 0 queued/due; live Blogger jobs: 0 queued/due, 0 blocked, 0 uncertain. Therefore `processed=false, result=null` meant there was no queued job in the enabled Mock lane; it was not a Publisher/API failure.
- The latest Publication Worker heartbeat was stopped/stale (prior PID 48000); no continuous Publication Worker process was detected.
- Global policy remained `manual`, daily limit 1, minimum interval 1,440 minutes, `operations_auto_approved=false`, Auto inactive, and real writes disabled.
- No AI generation provider or auto-eligible candidate was connected. No job was auto-enqueued, no external Blogger call was made, and no public post was created.

## Changes

- Added a continuous polling entry point with a PostgreSQL session advisory singleton lock, 15-second default polling, a live 15-second heartbeat thread, bounded error backoff, graceful signal handling, and the existing PID/start-time-bound stop marker.
- Preserved existing one-shot options. Added `--continuous`, `--poll-seconds`, and read-only `--status`; `--operations-mock-only --continuous` cannot issue Blogger writes. Private draft and live flags remain explicit CLI choices and still pass the existing policy checks.
- Expanded the status read model to show fake/live queue counts, due counts, blocked/uncertain counts, latest job, stale/fresh heartbeat, current Manual/Auto mode, and an exact idle reason.
- Added `scripts/start-publication-worker.ps1` for a hidden, duplicate-checked, mock-only continuous process with logs and fresh DB heartbeat verification. Integrated it with `scripts/start.ps1 -Service publication_worker`, `scripts/status.ps1`, `scripts/stop.ps1 -Service publication_worker`, and foreground `scripts/run-worker.ps1 -Service publication-mock`.
- `stop.ps1` now uses the existing identity-bound graceful stop marker for Publication Worker; it does not force-kill the process. `stop.ps1 -Service worker` remains scoped to Research/Evaluation Workers; Publication Worker has its own service selector.

## Before / after

- Before: one-shot invocation set a transient heartbeat, checked only the selected lane, returned `processed=false` for an empty/due-less lane, and stopped. There was no always-on Publication Worker launcher.
- After: a continuous mock-only runtime can remain online, report fresh heartbeat and queue state, prevent duplicate service instances through a PostgreSQL advisory lock, and stop cooperatively. The normal launcher does not enable private draft or live Blogger writes.

## Validation

- Focused isolated tests: `test_publications.py`, `test_worker_runtime.py`, `test_worker_stop_request.py` — 27 passed. Database-backed tests used the dedicated `woori_blog_agent_test` identity and rollback isolation.
- Ruff passed for changed Python files.
- PowerShell parser passed for `start.ps1`, `status.ps1`, `stop.ps1`, `run-worker.ps1`, `start-publication-worker.ps1`, and `server-common.ps1`. Existing stop Pester suite: 12 passed.
- `scripts/publication-worker.py --status` used read-only operational queries; observed state and counts are recorded above.
- Runtime service: the mock-only continuous worker is running; OS process PID 20652 (Python 3.13 child of verified venv launcher PID 38644), and the PostgreSQL heartbeat is fresh/running for PID 20652. The live queue and mock due queue are both 0; latest job remains blocked/quality_held. A first startup verification compared the heartbeat to the launcher PID and reported a false negative; the process was not stopped. The startup verifier now checks the exact descendant process, and the running worker was verified through the read-only status command. Reinvoking start was safely rejected as a duplicate. No real stop was performed so the requested idle mock-only service remains running. `scripts/stop.ps1 -Service publication_worker -WhatIf` targeted only PID 20652 and did not stop it.

## Files

- `services/api/woori/publication_worker.py`
- `services/api/woori/publications.py`
- `services/api/woori/worker.py`
- `services/api/tests/test_publications.py`
- `services/api/tests/test_worker_runtime.py`
- `scripts/publication-worker.py`
- `scripts/start-publication-worker.ps1`
- `scripts/start.ps1`
- `scripts/status.ps1`
- `scripts/stop.ps1`
- `scripts/run-worker.ps1`
- `scripts/server-common.ps1`
- `docs/development/P5-CODEX-033.md`

## Limits and remaining blockers

- The continuous launcher is deliberately mock-only. It does not auto-create publication jobs and cannot publish Blogger content.
- There are no auto-eligible articles; semantic claim/evidence verification, machine-validated rights, language quality, topic relevance, duplicate checks and trusted current-source proofs are not available together in the current candidate flow.
- Per-item manual live-publication checks remain in the existing live queue. A separate Auto policy authorization basis and its queue/Worker path are not yet connected.
- Auto stays OFF. GPT scheduled generation and unattended local delivery remain unverified. Blogger public posts remain 0.

## Commit and related documents

- Commit hash: see the subsequent `git log` entry for this development record.
- Related: `docs/development/P5-CODEX-032-auto-policy-followup.md`, `docs/operations/publishing-modes.md`.
