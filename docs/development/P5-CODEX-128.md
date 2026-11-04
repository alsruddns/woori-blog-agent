# P5-CODEX-128 — Unified publication policy

- Work ID: P5-CODEX-128
- Date: 2026-11-04 (Asia/Seoul)
- Branch: develop
- Start HEAD: `c61986f30facfa92b6f180b841c29b2e4bd48254`
- Start worktree: tracked files clean; existing untracked test artifacts and `stash@{0}` preserved.
- Related records: P5-CODEX-126 and P5-CODEX-127.
- Reason: manual, scheduled, and Trends publication classified incomplete source/review checks differently.

## Before and after

Before, the manual route recorded some evidence gaps as follow-ups, scheduled publication treated most evidence evaluator reasons as blockers, and Trends publication blocked unverified claim/review states directly. Each lane therefore made a different decision for the same kind of review gap.

After, all three paths use `woori.publication_policy.evaluate_publication_content`. General source, claim, research, SEO, quality, and editorial review gaps become deduplicated remediation items only when the lane's evidence-aware sanitizer and Blogger HTML sanitizer leave a usable supported body. The original verification values are not promoted. Unresolved facts, unsafe/empty body, rights blockers, OAuth/target/policy failures, duplicates, and publication limits remain blockers.

Scheduled and Trends content use the existing immutable import/content-version sanitizer path. Trends authoring-job version pointer changes are accompanied by an append-only audit event; old versions remain. Manual publication continues to bind the user's request to the displayed exact version and audited sanitized preview hash, with remediation items stored in the existing review tables in the same transaction as queue insertion.

## Files changed

- `services/api/woori/publication_policy.py`: new shared content decision/remediation evaluator; separates remediation, safety holds, and operational policy blockers.
- `services/api/woori/publications.py`: manual route/snapshot uses the shared evaluator and stores follow-ups with the existing queue transaction.
- `services/api/woori/publication_worker.py`: scheduled eligibility uses the shared evaluator after evidence-aware sanitization; operational gates remain.
- `services/api/woori/trends_publication.py`: Trends validation/enqueue uses the shared evaluator and stores follow-ups with queue creation.
- `services/api/woori/content_imports.py`: reuses the immutable sanitizer for Trends as well as scheduled content, with active target/policy checks and append-only lineage audit.
- `services/api/tests/test_publication_policy.py`: common policy tests for all three lanes, safety/policy blockers, and deduplication.
- `services/api/tests/test_trends_publication.py`, `services/api/tests/test_trends_post_edit.py`, `services/api/tests/test_post_publication_reviews.py`: updated policy and isolated integration regression coverage.

No database migration was added. Existing `post_publication_reviews`, review item, content version, audit, approval, and publishing queue structures are reused. No Blogger API POST/PATCH/DELETE was issued.

## Verification

- Focused publication/regression suite: 133 passed.
- Full API suite before final test assertion refresh: 837 passed, 9 failed. One failure was an obsolete source assertion updated in this change and later passed in the focused suite; 8 unrelated existing failures remain in taxonomy/schema expectations, a localized fixture, worker return-shape, readiness expectations, and readiness history tests. The full suite was not rerun after the source assertion update.
- Ruff on all `services/api/woori`: passed.
- Mypy on changed API modules: passed (5 modules).
- Dashboard `npm run lint`: passed.
- Dashboard `npm run typecheck`: passed.
- Dashboard `npm run build`: passed.
- `scripts/build-wheel.py`: passed.
- `git diff --check`: passed.
- Operational DB schema: 89; no migration required.
- Before reflection, no non-simulation publication jobs were running/uncertain and no Blogger write operations were pending. Existing historical rows were not changed.
- No Blogger write calls were made by tests or this work.

## Runtime baseline and remaining limits

At inspection, Dashboard PID 19452 was on `fdc2add590bbbd9164dd4b3172f86d2549048f69`; API PID 26600 and Publication Worker PID 36012 were on `b77ace192d38937bcd437819a59070ab98982437`; Research Worker heartbeat was fresh on `fdc2add590bbbd9164dd4b3172f86d2549048f69`. The runtime reported `AutoMode=manual` and automatic policy inactive. These operator settings were not changed. Code reflection can update the services but cannot enable automatic publishing.

The existing `scripts/apply-verified-changes.ps1 -Apply -Confirm:$false` procedure passed its changed-file Ruff/mypy/tests, wheel build, and isolated Dashboard production build. It gracefully stopped the old API and both Workers after confirming no active/uncertain non-simulation publication jobs and no pending Blogger writes, then started the new API and Workers. API health and Dashboard root both returned HTTP 200. Research and Publication Worker heartbeats are fresh.

Applied service revisions: API, Research Worker heartbeat, and Publication Worker run commit `9e683b3324c2404c8f2c9462c2cbc0d18350df19`. Dashboard remains PID 19452 on `fdc2add590bbbd9164dd4b3172f86d2549048f69`; no Dashboard files changed in P128, and it returned HTTP 200. PostgreSQL schema remains 89. No DB backup was required because no schema/data mutation was performed other than the append-only agent audit event.

The live operator setting currently reports `AutoMode=manual` and `AutoPolicyActive=False`; this work deliberately preserved it. The implementation is reflected in the runtime, but automatic public publishing is not operationally enabled under the current policy state.

Known limitation: the evaluator does not turn unknown evidence into verified evidence. If supported content cannot be produced, or the HTML/body/rights/OAuth/target/policy checks fail, publication remains held. Manual sanitation is represented by the exact original version plus sanitized preview hashes and review/audit lineage; it does not overwrite an existing content version.

## Final record

- End code HEAD: `9e683b3324c2404c8f2c9462c2cbc0d18350df19`.
- Commit: `9e683b3324c2404c8f2c9462c2cbc0d18350df19` (`Fix : [Publication] Unify publication policy evaluation`).
- Remote push: pending.
- Reflection: API, Research Worker, and Publication Worker applied; Dashboard unchanged and healthy.
- Remaining issue: 8 unrelated full-suite failures listed above; automatic operation remains governed by current DB policy (manual mode/off).
