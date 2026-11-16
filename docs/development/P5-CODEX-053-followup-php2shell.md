# P5-CODEX-053 follow-up — PHP2Shell scheduled import quarantine

- Work ID: P5-CODEX-053 follow-up
- Time: 2026-10-30 (Asia/Seoul)
- Branch: `develop`
- Reason: A scheduled PHP2Shell English export passed the current local envelope validator but Research Worker quarantined it.

## Diagnosis

The immutable quarantine file is `global-it-ai-2026-10-30-en-3d10f8d2-b4d8-454b-afc2-bab153a4013f.processing.json` with SHA-256 `6ebe4f8ac1a879a20d52ca70e78f9b25ef137d8dc2d000bb58473c5bce095639`.

Operational audit event `178105` (`scheduled_import.file_outcome`, 2026-10-30 00:51:32 KST) recorded `status=quarantined`, `reason=invalid_envelope`, and a Pydantic `literal_error` at `scheduled_origin.task_type`. The running Research Worker had been started before the current contract added `scheduled_article`, so it was using stale in-memory code. The current shared Pydantic validator accepts the file. The failure happened before an Import API request: there is no HTTP status or API error in that outcome. Label, duplicate, scheduled-origin DB validation and DB write permission checks were never reached.

Read-only operations DB checks found no `external_content_imports` row for the content UUID and no `content.import.scheduled_origin_recorded` event for the occurrence. The original file and its hash are preserved.

## Change

Added a formal `--retry-quarantined <exact-filename>` operation to `scripts/import-scheduled-content.py`. It requires a matching prior quarantine audit by file key and SHA, validates the envelope with the shared Pydantic contract, refuses if the content or scheduled occurrence already exists, appends `scheduled_import.quarantine_retry_requested`, then atomically moves the unchanged file from `quarantine/` to `ready/`. The normal Research Worker remains responsible for Import; Blogger writes are not performed by retry.

Files changed:

- `services/api/woori/scheduled_import_inbox.py`
- `services/api/tests/test_scheduled_import_inbox.py`
- `docs/development/P5-CODEX-053-followup-php2shell.md`

## Before / after and verification

- Before: valid under current schema, but the older running Worker rejected `scheduled_article` and quarantined it.
- After: an explicit, audit-checked retry path is available; duplicate import/origin records stop the retry without moving the file.
- Targeted tests: `pytest services/api/tests/test_scheduled_import_inbox.py -q` — 16 passed; Ruff on the changed Python files — passed.
- Retry request audit: event `178142`, 2026-10-30 01:06:10 KST. The original file was atomically moved unchanged to `ready/`; its SHA remained the original SHA.
- Runtime import: import ID `9a6d4636-3156-4eb6-907b-33deb4940c17`, content UUID `3d10f8d2-b4d8-454b-afc2-bab153a4013f`, method `chatgpt_scheduled_export`, occurrence `global-it-ai-2026-10-30-01`, task type `scheduled_article`. The original `scheduled_import.file_outcome` now records imported, `duplicate=false` (event `178147`). Scheduled-origin event `178144` recorded the expected blog ID `5240203250707821039` and English language. Source-capture event `178145` ran, but captured 0/8 sources because none were in the reviewed catalog.
- P5-052 publish-first evaluation ran. Assessment `dcce3e19-5e04-41db-bd24-27f306599b0e` is held: `machine_passed=false`, `generation_ready=false`, `publish_ready=false`; rights and semantic review remain human review items. The sanitizer audit (`publication.scheduled_auto.sanitization_held`, event `178148`) removed unsupported paragraphs and held because no supported article body remained. Scheduled evidence assessment `178149` reports missing live source retrieval/hash and claim spans. No publishing job exists; no Blogger post or URL exists; no post-publication follow-up row is expected before a verified remote post exists.
- Operational policy status remains manual / Auto policy inactive; Blogger writes were not performed. The publication worker heartbeat remained healthy and was not restarted.
- Commit hash: to be recorded after commit; see `git log` for the self-reference.

## Remaining

The quarantine defect is resolved and the file imported exactly once. To reach publication eligibility, the eight declared sources still need reviewed-catalog registration and live retrieval/evidence spans, followed by the applicable source/rights/factual checks. This task did not weaken those checks or execute Blogger writes.
