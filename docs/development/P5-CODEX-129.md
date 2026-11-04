# P5-CODEX-129 — Blogger manual publication block fix

- Work ID: P5-CODEX-129
- Date: 2026-11-04 (Asia/Seoul)
- Branch: `develop`
- Start HEAD: `70140a7faf85d47cd992e93747cd18c9c809d764`
- Reason: a manual request reported that a verified body could not be built and that source rights needed review, even though the manuscript had a substantive article body.
- Related record: `docs/development/P5-CODEX-128.md`
- Audit: append-only `agent.work.started` event 341815; completion event is recorded after service reflection.

## Runtime and operating state before changes

- Dashboard PID 7656, API PID 32532, Research Worker PID 21272, and Publication Worker PID 15948 were running. API, Dashboard, and Publication Worker reported applied code `6e7541524c421c23d2fcdd1011a32660474cb83b`; the Research Worker heartbeat was fresh and matched that revision.
- API and Dashboard responded HTTP 200 on the last status check. No service was restarted before the cause was identified.
- PostgreSQL operations schema was 89. No migration or settings change was required.
- Publication Worker heartbeat was fresh and idle (`LiveQueued=0`, `LiveDue=0`). `publishing_jobs` contained no running status; `blogger_write_operations` had no in-flight status. The worker's current user settings were left unchanged.

## Cause and behavior change

The scheduled/manual/Trends sanitizer treated missing verification records and uncited paragraphs as proof that the text was unsafe. It removed the whole paragraph, and on the affected import all usable paragraphs were removed. The recorded pre-change body had 4,216 characters across 15 paragraphs; the sanitizer output was empty (the empty SHA-256). The source rights state was a review-needed state, not a confirmed rights denial.

The sanitizer now distinguishes missing review evidence from confirmed false or explicitly restricted material. Missing evidence and incomplete rights review are retained as remediation warnings. It removes content only when a claim is explicitly false/contradicted/rejected, a source is explicitly restricted, or a stored source excerpt/quotation or embedded image needs removal. For a restricted source, unrelated editorial context is retained. Japanese and typographic quotation delimiters are recognized without changing ordinary prose.

Manual, scheduled, and Trends paths pass source rights into the same sanitizer, assess the resulting body, and keep the original claim-verification status. Remediation reasons remain recorded by the existing policy/review mechanism; they are not promoted to verified. Empty input, invalid Blogger HTML, confirmed false claims, explicit rights restrictions, OAuth/target/policy failures, duplicate publication, and limits remain fail-closed.

## Actual failed-manuscript dry run

Read-only against the local operations database, using the failed import recorded in the publication audit:

| Measure | Before | After |
|---|---:|---:|
| Source body | 4,216 chars / 15 paragraphs | 4,216 chars / 15 paragraphs |
| Sanitized Blogger HTML | Empty output | 4,086 chars |
| Content decision | Blocked as no supported body | `READY_WITH_REMEDIATION` |
| Content-policy blockers | Body/sanitization block | None |
| Follow-up items | — | 17 |
| Full manual operational blockers | — | `manuscript_discarded` |

The failed manuscript is already marked discarded. This policy was preserved; the dry run does not restore it, enqueue it, or publish it. A new explicit restoration action would be needed before any manual request can proceed. No content, queue, posting record, OAuth, or operating setting was changed by the dry run.

## Files changed

- `services/api/woori/scheduled_auto_verification.py`: preserve review-incomplete prose, remove only confirmed unsafe material, and return remediation/removal metadata.
- `services/api/woori/publication_policy.py`: classify missing source/claim/rights review as remediation; retain actual safety and operational blockers.
- `services/api/woori/publications.py`: build manual evidence assessment from sanitized body and propagate remediation warnings.
- `services/api/woori/publication_worker.py`: apply the same rights-aware sanitization to scheduled work.
- `services/api/woori/trends_publication.py`: apply the same rights-aware sanitization to Trends work.
- `services/api/woori/content_imports.py`: preserve claims still represented in the sanitized version without marking them verified; include removal and retained-warning metadata in the existing audit lineage.
- `services/api/tests/test_publication_policy.py`, `test_publications.py`, `test_scheduled_auto_verification.py`, `test_scheduled_publish_first.py`: cover incomplete review, explicit risks, quotes, empty body, and manual/scheduled policy regressions.

No migration was added. No Blogger API write, draft creation, or external Blogger request was made.

## Validation

- Focused publication regression suite: 150 passed, 0 failed. One pytest cache permission warning was emitted; it did not affect test results.
- Additional Import/Trends suite: 37 passed, 2 failed in existing category/schema registry assertions (`general-news` mismatch). Those assertions are outside the sanitizer/policy diff and match the unrelated taxonomy/schema failures noted in P128; no category/schema files were changed.
- Ruff on six changed API modules: passed.
- Mypy on six changed API modules: passed.
- Python compile on changed modules: passed.
- `git diff --check`: passed.
- Actual-operation-database dry run: body and sanitized HTML remained present; content-policy result was `READY_WITH_REMEDIATION`; the existing discard record remains the sole full manual blocker.
- Blogger API write calls: 0.

## Reflection and remaining limits

The code is implemented and tests pass. Service reflection is pending the approved `scripts/apply-verified-changes.ps1` procedure after this change is committed. The existing discarded manuscript remains blocked. No actual publication was tested or performed. Automatic posting still follows the current database-controlled approval and per-blog policy state; this work does not activate or bypass it.

## Final record

- End code HEAD: filled after commit.
- Service reflection: filled after the verified reflection procedure.
- Push: filled after verifying `origin/develop`.
- Remaining issue: the actual failed manuscript is discarded and requires an explicit, separate restore decision; no automatic restore or publish was performed.
