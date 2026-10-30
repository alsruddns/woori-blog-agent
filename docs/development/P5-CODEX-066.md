# P5-CODEX-066 — Duplicate lookup outage and scheduled draft handoff

- Work date: 2026-10-30 (Asia/Seoul)
- Branch: `develop`
- Status: implementation and focused tests complete; scheduled export/import and publication not yet runtime-verified
- Commit: resolve with `git log -- docs/development/P5-CODEX-066.md` after commit

## Cause and prior behavior

The Fed/SEC scheduled snapshot at
`.local/gpt-scheduled-import/research/fed-sec-official-2026-10-30-en-20261030T1104KST-sec2026-110.research.json`
records the 2026-10-30 11:00 KST `fed-sec` slot and derived occurrence
`codex-slot:fed-sec:20261030T1100KST`. Its duplicate preflight passed the full
SEC release URL as `event_group_id`. The API rejected it with HTTP 422 because
the field is limited to 128 characters. The request failed validation before
any Blogger read or OAuth request; `duplicate_preflight_unavailable` obscured
that request-validation error.

Using the stable short event key `SEC-2026-110`, the complete read-only
preflight found no local/imported match and completed the Blogger read with
`not_found`. A subsequent generation-stage request to the currently running
API returned HTTP 422 for the new `stage` field, confirming that this runtime
has not yet loaded the P5-CODEX-066 API contract. No article JSON was created
or imported in this work. The scheduled snapshot is research evidence only;
it does not contain an article export, and this interactive session did not
claim to be the original Scheduled task.

The existing snapshot records that the SEC release describes allegations in a
complaint. Any later article must retain that distinction and must not describe
the allegations as a final court finding. Its source notes also say source-
specific reuse terms were not separately reviewed; that remains a publication
review item.

## Changes

- Added `generation` versus `publication` stages to the read-only duplicate
  preflight. Generation checks local imports, publication records, and Inbox
  history only. A locally clear `not_found` or `failed_only` result allows a
  draft while explicitly returning overall `unknown`, remote `not_checked`,
  and a required publication-time recheck. Local matches and ambiguous pending
  files still stop generation.
- Added separate local/remote duplicate status, failure code, draft allowance,
  recheck requirement, and retry state to scheduled-origin validation and its
  append-only audit payload. The fields remain optional for legacy envelopes;
  when present, Pydantic validates the complete state combination. The JSON
  Schema advertises the same fields.
- Improved the read-only CLI to enforce concise event keys and report HTTP
  status plus sanitized Pydantic validation locations/messages. It never emits
  echoed inputs, response bodies, credentials, or tokens. `--stage generation`
  exits successfully only when `draft_import_allowed=true`; the result remains
  explicitly unknown about Blogger.
- Changed the live publication path so a remote duplicate match blocks the
  write, and an unknown remote state schedules bounded exponential retry
  (capped at 15 minutes and by the job's `max_retries`). Exhaustion fails the
  job. Neither path calls Blogger's write adapter. The same pre-write check is
  shared by scheduled and manual live lanes.
- Updated the common Scheduled task instructions and operating policy to
  separate draft/import eligibility from publication-time remote verification.

## Verification

- Focused tests: 65 passed across scheduled duplicate scan, CLI diagnostics,
  scheduled envelope/Inbox, and publication worker tests.
- Ruff: passed for all changed Python files.
- `git diff --check`: passed.
- Mypy initially identified a return-type issue in the new bounded-delay
  helper, which was corrected. Rerun mypy after the correction.
- Operational Blogger writes: none.
- Import JSON / ready handoff / Import Worker receipt / Publishing Job / public
  URL: none. The saved snapshot is not a generated article. Do not reuse its
  11:00 slot as a new Scheduled execution; the next genuine task run must
  produce the export and derive its own slot identity.
- Current API runtime: stale; it rejects `stage` with HTTP 422. Reflecting the
  committed API/Worker source through the repository's guarded service
  reflection script is still required before the new preflight is available
  locally. No Worker was stopped or started during this change.

## Files

- `AGENTS.md`
- `docs/development/P5-CODEX-066.md`
- `docs/operations/P5-CODEX-038-scheduled-task-catalog.md`
- `docs/operations/SCHEDULE-CODEX-003-common-instructions.md`
- `docs/operations/content-import.md`
- `docs/schemas/woori-scheduled-content-import-1.0.schema.json`
- `scripts/scheduled_duplicate_check.py`
- `services/api/tests/test_publications.py`
- `services/api/tests/test_scheduled_duplicate_cli.py`
- `services/api/tests/test_scheduled_duplicates.py`
- `services/api/tests/test_scheduled_import_inbox.py`
- `services/api/woori/content_imports.py`
- `services/api/woori/publication_worker.py`

No operational data, failed Inbox file, OAuth record, schedule, or Blogger
post was modified. Commit hash and remote push result are reported after Git
completion.
