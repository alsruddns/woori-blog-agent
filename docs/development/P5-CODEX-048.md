# P5-CODEX-048 — Scheduled manuscript auto-evidence gate

- Work date: 2026-10-29 (KST)
- Branch: `develop`
- Goal: separate scheduled-export machine evidence assessment from general human review records while retaining first-publication approval and all Blogger write gates.

## Before

- Scheduled queue eligibility required claim and rights flags from `external_content_import_review_events`.
- The scheduled lane already checked deterministic assessment, live source excerpts, source rights labels, target mapping, remote duplicates, daily limits, scheduled policy, and exact first-post approval.
- Missing eligibility evidence was not durably recorded as a version-bound auto-assessment.

## Changes

- Added `scheduled_auto_verification.evaluate_scheduled_evidence` for scheduled imports only. It checks source retrieval status/URL/import identity/source-body hash, exact claim excerpt presence, numeric consistency, independent organization count for claims marked corroborated, and explicit reuse-terms proof bound to an unexpired reviewed policy version.
- A human review event remains a separate evidence route. The new machine path does not create or modify editorial review, publication approval, or `publish_ready` state.
- Scheduled queue assessment now emits an append-only `publication.scheduled_auto.evidence_assessed` event bound to import/version/content IDs and immutable version hash. It records check results, source/claim references, source evidence hashes, result, and hold reasons; unchanged results are deduplicated.
- Eligibility assessment now runs before the exact first-post approval check. A candidate can be durably assessed while the first-post approval is absent, but it cannot enter the publishing queue.
- The `scheduled-auto` launcher no longer refuses to start the observation/assessment Worker just because the first-post approval is absent; the enabled scoped policy and emergency stop are still checked at startup, while actual queue dispatch continues to enforce exact first-post approval.
- Updated `AGENTS.md` with the narrow scheduled-auto exception and conditions; ordinary/manual/Trends publication remains under the existing human-review policy.

## Tests

- `.venv\Scripts\ruff.exe check services/api/woori/publication_worker.py services/api/woori/scheduled_auto_verification.py services/api/tests/test_scheduled_auto_verification.py` — passed.
- `.venv\Scripts\pytest.exe services/api/tests/test_scheduled_auto_verification.py services/api/tests/test_publications.py -q` — 29 passed.
- `.venv\Scripts\python.exe -m compileall -q services/api/woori/publication_worker.py services/api/woori/scheduled_auto_verification.py` — passed.
- `.venv\Scripts\mypy.exe services/api/woori/scheduled_auto_verification.py` — passed. Running strict mypy on the existing `publication_worker.py` still reports 11 DB-row Optional/signal typing errors outside the new verifier; this check is not reported as passing.
- PowerShell parser validation for `scripts/start-publication-worker.ps1` — passed.
- `git diff --check` — passed before the final documentation edit; rerun before commit.

## Operational result

- Ran the scheduled enqueue assessment once through the modified code: `created=0`, `held=1`, `first_post_confirmed=false`.
- The current Japanese import `9bd1706b-5e0a-4cb4-a7fd-d4949b9ecad7` recorded a held assessment for version `45d52e29-b6d7-40be-b79b-97d91f339069`, content version `b6abf4f0-4bf8-4ddc-b01e-fdc183f2a9f6`, hash `8a47ebcea8e6472b4f528abb0bfc66c8cfc680d1e12115fa1c907eaccb05f2fa`.
- Hold reasons: `source_rights_not_cleared`, `source_live_verification_missing`, `claim_span_not_found_in_live_source_evidence`, and `source_rights_not_machine_verified`.
- Scheduled publishing jobs for this import remain 0. No Blogger write or publication request was made. First exact-post approval remains absent; global mode is manual and live-write flags remain disabled.
- A normal restart was attempted with `scripts/stop.ps1 -Service publication_worker -TimeoutSeconds 60 -Confirm:$false`, but the safety check refused to stop it because heartbeat PID 26768 did not match the script's exact-path process identity. No process was stopped or force-terminated. PID 26768 remains a fresh scheduled-auto heartbeat (21:53 KST), but the running process has not loaded this commit.
- Process inspection showed PID 26768 is a child of repo-venv launcher PID 42560, itself a child of interactive VS Code PowerShell PID 47600. Both command lines contain the relative `.\scripts\publication-worker.py` path, and `.runtime/server-processes.json` is absent. The stop script's exact absolute-script check therefore remains unverified; the current Worker was left running.

## Changed files

- `AGENTS.md`
- `services/api/woori/publication_worker.py`
- `scripts/start-publication-worker.ps1`
- `services/api/woori/scheduled_auto_verification.py`
- `services/api/tests/test_scheduled_auto_verification.py`
- `docs/development/P5-CODEX-048.md`

## Remaining

- The current Japanese sources have no project-side live verification/reuse-terms proofs; their imported rights labels do not establish rights. The new path correctly holds them.
- The source proof producer for this Japanese source set is not connected. No article version, source audit, or rights status was fabricated.
- First public post requires the existing approval event for one exact manuscript version/body hash/blog. No approval was created.
- Actual Blogger public URL: none; published count remains 0.
- Applying the committed Worker code still requires a safe normal stop/restart from its owning VS Code terminal or a later process-ownership verification fix. Do not start a duplicate Worker while PID 26768 remains active.
- Commit hash: recorded in the follow-up commit entry in `git log`.
