# P5-CODEX-046 — Scheduled manuscript intake and publication blocker

- Work date: 2026-10-29 (KST)
- Branch: `develop`
- Scope: repair the scheduled Import Worker path and report the remaining gates to public Blogger publication.

## Problem and before state

The Research Worker was running and repeatedly claimed the Japanese scheduled manuscript file, but every attempt stopped after the idempotent Content Import call. The following scheduled-origin audit request returned HTTP 503 (`Database operation unavailable`), so the inbox returned the file to `ready/` and retried it on the next poll. The API's shared database-error handler hid the SQLSTATE, making the failure hard to operate safely. The import row existed, but its scheduled file name/hash and origin audit event were absent. The publication queue had no scheduled-auto job; the publication worker was alive but idle.

The API publication worker status showed the scheduled policy enabled for the four registered blogs with a one-per-day cap. The separate first-publication approval was absent, global mode was `manual`, public publication was disabled, and real Blogger writes were disabled. No live Blogger call was made.

## Changes

- Removed `FOR SHARE` locks from the scheduled-origin read-only import/blog lookups. The inbox's PostgreSQL advisory transaction lock remains the serialization mechanism for an occurrence; the read path no longer requires row-update privileges from the least-privilege application role.
- Kept the origin audit append-only and idempotent. Added a bounded SQLSTATE-to-category 503 message for this endpoint without returning database messages, values, or credentials.
- Corrected Japanese grounding normalization so yearless month/day references match a source date with a year, while different days remain distinct. Excluded the `1 litre` denominator in a per-litre price expression from the factual quantity set while preserving the price itself.
- Added a `scheduled-auto` launcher mode with read-only worker-policy preflight, retained the mock-only default, and made `status.ps1` report the mode from the actual process command line. No Worker was restarted during this work.

## Actual operational result

- Scheduled JSON file: `.local/gpt-scheduled-import/processed/politics-jp-2026-10-29-ja-politics-jp-20261029-ja-ed65328b-28a5-4bfe-a1c4-391b598db11c.processing.json`
- File SHA-256: `38427a341a629317a66d56d1e91ea996789a4687299307811c842c66d156ed8a`
- Import ID: `9bd1706b-5e0a-4cb4-a7fd-d4949b9ecad7`
- Content version: `b6abf4f0-4bf8-4ddc-b01e-fdc183f2a9f6`; imported version: `45d52e29-b6d7-40be-b79b-97d91f339069`
- Imported version body SHA-256: `8a47ebcea8e6472b4f528abb0bfc66c8cfc680d1e12115fa1c907eaccb05f2fa`
- Result: 1 scheduled file moved to `processed/`; 1 DB Import; 1 scheduled-origin event; machine assessment passed. The assessment remains `generation_ready=false` and `publish_ready=false`, with independent source verification and human editorial/rights review outstanding.
- The original import file was received at `2026-10-29 21:08 KST`; scheduled-origin retries returned HTTP 503 13 times before the fix. After API restart, the unchanged Research Worker completed the inbox flow on its normal poll.
- Publishing jobs for this manuscript: 0. Scheduled-auto queue: 0. Public Blogger posts: 0. Public URLs: none.
- Verified reservation-run claims: 0; verified GPT runs: 0. The local JSON was automatically consumed by the Import Worker, but this does not independently verify the identity or unattended execution of the Codex schedule.

## Runtime and safety

- API was stopped and started gracefully through `scripts/stop.ps1` and `scripts/start.ps1` to apply the endpoint change; health returned HTTP 200. Dashboard stayed running on port 3100.
- The Dashboard stop script refused to stop the existing process because its process-tree check found an unrelated `vgtray.exe` descendant. It was not force-stopped.
- Research Worker and Publication Worker were not stopped or restarted. Publication heartbeat remained fresh; its process command line reports `--operations-scheduled-auto --continuous`, but it remains idle with no eligible job.
- Auto policy and first-post approval were not changed. No review, approval, publication job, Blogger draft, or Blogger public write was fabricated or submitted.
- The Japanese manuscript is titled “ガソリン補助金はどう変わる？政府の検討と自民党案を整理” and targets blog ID `7562596540375659150`. Review and any first-publication approval must apply to the exact immutable version and body SHA-256 above.

## Files

- `services/api/woori/content_imports.py`
- `services/api/woori/grounding.py`
- `services/api/tests/test_content_imports.py`
- `services/api/tests/test_live_research.py`
- `scripts/server-common.ps1`
- `scripts/start-publication-worker.ps1`
- `scripts/start.ps1`
- `scripts/status.ps1`
- `docs/development/P5-CODEX-046.md`

## Verification

- Ruff on the changed Python modules/tests: passed.
- Focused pytest selection across content import, grounding and inbox tests: 17 passed, 72 deselected.
- `git diff --check`: passed.
- Live API health: HTTP 200. Live operations dashboard confirmed the import, inbox receipt metadata, machine result, queue counts, mode, and worker heartbeat.
- No Blogger API write was made; no public posting success is claimed.

## Remaining gates

1. Independent source verification and a human review of the Japanese manuscript's factual meaning, rights/use conditions, and editorial quality.
2. First-publication approval through the existing approval API, bound to the exact import/version/body hash and target blog, after that review.
3. The current global mode and write-dispatch flags are still fail-closed; scheduled policy alone does not enable actual publication.
4. A live Blogger public post and URL have not been verified. Therefore continuous unattended public posting is not yet demonstrated.

The implementation commit is recorded in `git log`; the final documentation commit is the subsequent `origin/develop` commit.
