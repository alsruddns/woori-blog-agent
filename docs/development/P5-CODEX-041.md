# P5-CODEX-041 — Scheduled import identity and revision reference repair

- Work ID: `P5-CODEX-041`
- Work time: 2026-10-29 17:13 KST (08:13 UTC)
- Branch: `develop`
- Reason: the first 2026-10-29 Korean market-close envelope was quarantined, and its corrected file was rejected as a revision even though the parent had never been imported.
- Before: local Pydantic validation returned only `invalid_envelope`; API rejection stored HTTP status but omitted a safe API detail from the Worker audit. The shared authoring instructions did not define pre-import corrections or the taxonomy allowlist.
- After: the exact validation error and sanitized API detail are attached to each file outcome and copied into `scheduled_import.file_outcome`; the Codex local validator and inbox Worker now call one Pydantic validation entry point. Shared prompts define original/revision, occurrence, and allowed-label rules.

## Read-only incident findings

Files were read but not edited, moved, or deleted. Their SHA-256 values at inspection:

| File | Content ID | Relation / parent | Result |
|---|---|---|---|
| `.local/gpt-scheduled-import/quarantine/market-close-kr-2026-10-29-ko-fc317cfb-ce64-46b8-874e-1897840bb77d.processing.json` | `fc317cfb-ce64-46b8-874e-1897840bb77d` | original / none | SHA-256 `266965669c2e869180957c824aab079a54030e1f5d692445db9c33fe9c915216`; Pydantic validation fails with `unrecognized_or_unreviewed_blogger_label`. This is a local validation failure, before any HTTP request. |
| `.local/gpt-scheduled-import/rejected/market-close-kr-2026-10-29-ko-4b54bb1a-c630-405b-82d4-96bd72761062.processing.json` | `4b54bb1a-c630-405b-82d4-96bd72761062` | revision / `fc317cfb-ce64-46b8-874e-1897840bb77d` | SHA-256 `fbfa52f8128dfe05e4a962ec417a7f23b453a63b601284e738c0668389137e73`; Pydantic-valid, but its parent is absent from `external_content_imports`. |

Read-only operations DB inspection found no import row for either content ID and no matching audit event. The historical API response body/status for the rejected file was not retained in the local API logs or audit payload, so the exact past HTTP status cannot be independently proven. The current API code queries `external_content_imports` and returns HTTP 409, `The referenced parent import does not exist`; the new isolated-DB E2E regression confirms that response. The initial file never reached the API.

Taxonomy-derived allowed labels for `stocks`/`ko` are `주식`, and `이슈`, `주식` when Trends-based. Values come from `suggested_labels`; free-form labels remain rejected.

## Changes

- `services/api/woori/scheduled_import_inbox.py`: shared `validate_envelope`, safe bounded Pydantic/API error details, and explicit status/reason/HTTP status in outcomes.
- `services/api/woori/worker.py`: append safe validation and API error details to the existing file outcome audit event.
- `scripts/validate-scheduled-import.py`: read-only local file validator backed by the exact same Pydantic entry point as the Worker, restricted to the scheduled-import `incoming` directory.
- `services/api/tests/test_scheduled_import_inbox.py`: taxonomy rejection, shared-validator parity, safe error detail, duplicate content import, duplicate occurrence, missing parent, and full isolated-DB import/assessment regressions.
- `docs/operations/P5-CODEX-024-gpt-work-prompts.md`, `docs/operations/P5-CODEX-038-scheduled-task-catalog.md`: common authoring instructions for original versus revision, unique occurrence behavior, taxonomy labels, and validator use.

No migration was required. Existing operational OAuth, content, files, and audit rows were not changed. The two incident files remain untouched. No Blogger API call, live import/reprocessing, Auto change, or publication job was performed. The Codex Scheduled task objects live outside this repository; the common instructions were updated for future use, but existing task IDs/models/schedules/prompts could not be inspected or edited from this checkout.

## Verification

- `pytest services/api/tests/test_scheduled_import_inbox.py services/api/tests/test_content_imports.py -q`: **24 passed**. The integration path uses the dedicated `woori_blog_agent_test` DB and a forced rollback; it performed a test import, immutable content-version creation, scheduled-origin recording, and machine assessment. No operations DB rows were created.
- Regression verifies same content ID + same content is idempotent; a reused occurrence with a different imported manuscript is rejected; a revision with a nonexistent parent receives HTTP 409; unsupported taxonomy label is quarantined before HTTP.
- `scripts/validate-scheduled-import.py --help`: passed; the command is read-only and uses `validate_envelope`, also called by the Worker.
- Ruff on all changed Python files: passed. `git diff --check`: passed.
- Test outcome count: one test-imported original followed by duplicate delivery; machine assessment remains non-passing/review-held and `publish_ready=false`. No actual manuscript was imported into operations DB.

## Remaining

- Operator can resubmit a corrected pre-import manuscript as `original`, with a new unique `content_id`, only after checking that no successful operations import already exists. Keep the same `occurrence_id` only for that same scheduled execution if it was never accepted/audited; an already accepted occurrence must be retried byte-for-byte with the same envelope.
- The historical rejected API response status is unavailable; current behavior is proven by code and isolated integration test, not reconstructed from a missing log.
- Codex desktop Scheduled task objects are outside this repository. Shared instructions are ready, but task prompt propagation was not independently verified.
- Content remains review-held. Blogger write and Auto stay disabled; publication still requires the separate existing operations approval and all safety gates.
- Commit SHA and push result are recorded in the follow-up section below.

## Commit / follow-up

Final commit SHA and origin/develop push status are recorded in the completion report and `git log`.
