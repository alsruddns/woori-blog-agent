# P5-CODEX-032 follow-up — per-item human approval-free Auto eligibility

- Work ID: P5-CODEX-032 follow-up
- Date: 2026-10-29 (Asia/Seoul)
- Branch: `develop`
- Reason: The requested Auto policy must not depend on per-article human approval records, while Auto activation and live writes remain separately disabled until the operator's initial transition confirmation.

## Change

- Added an Auto eligibility contract independent of `editorial_review_approved`, publication approval events, and `publish_ready`.
- Eligibility requires verified source access/body, key facts, semantic claim-to-evidence match, sufficient independent verification, rights clearance, language quality, topic relevance, SEO, safe HTML, freshness, duplicate clearance, valid blog mapping, and non-evaluation status. Missing or unknown evidence fails closed.
- Separated `auto_eligible` (content and policy gates) from `dispatchable` (Auto configured, emergency stop clear, policy explicitly activated, and live writes enabled). The API continues to report policy inactive and real writes disabled. No human approval record is created or inferred.
- Auto policy preferences can be saved with an explicit category allowlist. Saving settings does not activate dispatch or Blogger writes. The default operating mode remains Manual.
- The publication dashboard shows the separate eligibility and dispatch status and keeps Auto configuration available as inactive policy configuration.

## Runtime facts and limits

- No Auto activation was performed, no Publisher Worker was started, and no Blogger write was attempted.
- Current operational mode remains `manual`; prior observed limits were 1 publication/day and a 1,440-minute minimum interval. This change does not alter those values.
- GPT unattended generation provider remains unattached; scheduled generation is disabled. Verifiable GPT scheduled runs and unattended local file deliveries remain 0.
- Current stored candidate rows do not contain machine-verifiable semantic entailment, source rights, language naturalness, freshness-at-decision, and blog-wide duplicate evidence. Those gates remain false/unknown, so this change does not make any current row auto eligible.
- `publish_ready` and human editorial/publication approval remain separate historical/manual concepts and are not forged or modified.

## Before/after

- Before: Auto eligibility always failed due to mandatory human review/approval and `publish_ready`; Auto mode preferences were rejected.
- After: the eligibility calculation excludes human approval and `publish_ready`; inactive Auto preferences may be saved; actual dispatch still fails closed on missing evidence and inactive live policy.

## Files

- `services/api/woori/publication_modes.py`
- `services/api/woori/publications.py`
- `services/api/tests/test_publications.py`
- `apps/dashboard/app/publishing/publication-manager.tsx`
- `docs/operations/publishing-modes.md`
- `docs/development/P5-CODEX-032-auto-policy-followup.md`

## Validation

Focused isolated pytest: 22 passed (`test_publications.py`, `test_publication_modes.py`). Ruff passed for changed Python files; Dashboard ESLint and typecheck passed. Dashboard HTTP 200 and API `/health` status ok were read-only verified. Existing services were not restarted. A read-only publications response still showed Manual, Auto OFF, and 0 actual posts; its old response shape confirms the running API process has not loaded this checkout change. The operational database and Blogger API were not used for tests.

## Commit and related documents

- Commit: recorded in the subsequent commit; see `git log` for the immutable hash.
- Related: `docs/development/P5-CODEX-032.md`, `docs/operations/publishing-modes.md`.

## Remaining blockers

- No attached unattended generation provider or verified official GPT scheduled file-delivery run.
- Semantic fact verification, automated rights/use-limit assessment, language naturalness, topic relevance, and blog-wide duplication are not established by current stored checks. Auto candidates remain held until those checks exist and produce trusted results.
- Initial Auto policy activation and live Blogger publication remain disabled pending the separately requested operator transition confirmation and applicable Blogger write authorization.
