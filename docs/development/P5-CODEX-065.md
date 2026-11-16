# P5-CODEX-065 — Scheduled occurrence fallback and article taxonomy

- Work date: 2026-10-30 (Asia/Seoul)
- Branch: `develop`
- Status: occurrence support and taxonomy correction implemented; scheduled article handoff/import not completed
- Commit: resolve this record through `git log -- docs/development/P5-CODEX-065.md` after commit

## Problem and before state

Codex Desktop's scheduled prompt reported that it did not receive a
scheduler-issued `occurrence_id`; the import envelope required one, so the
crypto task stopped before creating an article envelope. Its saved prompt also
classified source-led crypto work as `trends_major_issue`, despite the saved
research snapshot containing no Google Trends observation. The schema,
Pydantic model, duplicate-origin audit, and inbox idempotency already used the
occurrence ID as the stable import identity.

The snapshot at
`.local/gpt-scheduled-import/research/crypto-issue-2026-10-30-en-20261030T102627KST.json`
records task code `crypto-issue`, source access at 2026-10-30 10:26:27 KST,
daily 10:30 KST schedule context, no scheduler-issued ID, no Trends source,
and an earlier duplicate preflight of `not_found` with complete Blogger read.
The current read-only preflight for CFTC event `9307-26` also returned
`not_found`, `blogger_read_complete=true`, and no DB import match.

## Changes

- Added deterministic occurrence identities derived from the actual active
  Automation ID and its configured minute-precision KST slot. Derived IDs
  are explicitly marked `project_derived_kst_slot`; the scheduler-issued ID
  field remains null. A derived ID is an idempotency key, not evidence of
  scheduler attestation.
- Added a read-only CLI that verifies the saved active Automation, project
  checkout, and RRULE slot before returning occurrence metadata.
- Extended the scheduled envelope model, schema, and append-only import audit
  payload to retain the identity source, scheduler ID (when actually supplied),
  Automation ID, slot, and timezone. Legacy envelopes with no new metadata
  remain accepted. Derived metadata must match the deterministic ID.
- Enforced alignment between `trends_major_issue` and
  `google_trends_based=true`; non-Trends scheduled articles use
  `scheduled_article`.
- Updated the common scheduled instructions and added
  `docs/operations/SCHEDULE-CODEX-004-occurrence-and-task-type-correction.md`.
  The latter records the read-only review of 15 active task definitions and
  the task-type corrections without modifying their saved prompts, schedules,
  model, project, or blog settings.

## After state and verification

- Crypto task: `automation-3`, daily 10:30 KST.
- Verified derived identity: `codex-slot:automation-3:20261030T1030KST`;
  `scheduler_occurrence_id=null`.
- Duplicate preflight: `not_found`, complete Blogger read, no DB match.
- Task taxonomy: `scheduled_article`, `google_trends_based=false`.
- Focused tests: 38 passed across occurrence identity, envelope validation,
  inbox idempotency, and scheduled-origin audit tests.
- Ruff: all checks passed for changed Python files.
- `git diff --check`: passed.
- Existing Codex Desktop task definitions were not changed.

## Handoff limitation

No new article envelope, `ready/*.ready.json`, Import Worker receipt, import
ID, or Publishing Job was created in this change. The existing scheduled
snapshot records only source-access time and file-write time; those are not a
reliable exact `executed_at` receipt for the article export. The scheduled
Desktop run also did not produce the article envelope. Creating one from this
interactive follow-up and labeling it `chatgpt_scheduled_export` would claim a
generation origin that did not produce the file. Therefore no file was placed
in the Import Worker queue. No Blogger write was attempted.

To complete the export, apply the task-type and occurrence procedure in
`SCHEDULE-CODEX-004-occurrence-and-task-type-correction.md` to the saved
`automation-3` prompt in Codex Desktop and verify that exact prompt was saved.
The next actual scheduled execution should record its actual execution time,
derive the ID for its own configured KST slot, and use the common Pydantic
validator before handoff. Do not replay the 2026-10-30 slot as though a new
scheduled execution had occurred. The existing Research Worker remains the
required intake path.

## Files

- `AGENTS.md`
- `docs/development/P5-CODEX-065.md`
- `docs/operations/SCHEDULE-CODEX-003-common-instructions.md`
- `docs/operations/SCHEDULE-CODEX-004-occurrence-and-task-type-correction.md`
- `docs/schemas/woori-scheduled-content-import-1.0.schema.json`
- `scripts/derive-scheduled-occurrence-id.py`
- `services/api/woori/content_imports.py`
- `services/api/woori/scheduled_occurrence.py`
- `services/api/tests/test_content_imports.py`
- `services/api/tests/test_scheduled_import_inbox.py`
- `services/api/tests/test_scheduled_occurrence.py`

No database migration, operational row edit, Blogger write, OAuth change, or
live Automation definition change was performed. Commit SHA is available in
the repository log for this document; push result is reported in the work
summary.
