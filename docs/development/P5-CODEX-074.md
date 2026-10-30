# P5-CODEX-074 — Scheduled claim scope and abbreviated evidence recovery

Date: 2026-10-30 KST; branch develop. Reused P5-CODEX-073 inventory; no new full survey.

## Common defects and corrections

- Abbreviated excerpts containing ellipses were treated as contiguous literal quotations. Added ordered exact-fragment traceability: every fragment must appear in source order with sufficient anchors. This is not similarity scoring or proof of semantic entailment; numerical checks and independent-source requirements remain. Changed words, reversed order and changed numbers fail regression tests.
- Sanitization ran before applying a version's trusted retained-claim manifest. An unsupported sibling claim sharing the same source removed all paragraphs, even after a narrow recovery version excluded that claim. Both version preparation and Worker eligibility now apply the exact-version/body-hash manifest before paragraph sanitization/evaluation.
- Scheduled queue chose any policy for the blog, ignoring manuscript country. It now selects exact language/country profiles, retaining the DB guard. Registered en/US policy through the existing audited configuration API for the same already-approved English Blogger, with active=false and no Auto permission expansion.
- Changed source modules: scheduled_auto_verification.py, scheduled_source_evidence.py (capture policy v4), content_imports.py, publication_worker.py. Tests: test_scheduled_auto_verification.py, test_publications.py. No UI, OAuth, manual publication API, migration, schedule or prompt changes.

## Representative recovery

- Scheduled Import 7bcc3d86-d0aa-4d6c-bef4-e47726b7f818 (en; Blogger 5240203250707821039). Existing Fed source fetched again under the reviewed provider: HTTP 200; SHA256 370f64dac1d2e733306fccde44bb1cae123149072427383e49e15f049ea22871. Exact-fragment capture found two traceable excerpts; full claim/quantity evaluation retained C3 only. Other composite claims and unsupported implications were excluded.
- C3 states that Lisa D. Cook and Beth M. Hammack dissented and preferred a quarter-point increase. Both subfacts were checked against the actual release. Three original paragraphs explain those subfacts and explicitly distinguish the preferred alternative from an adopted decision. No new numerical forecast or rate outcome was added.
- Created immutable import version 2: 4e7d0dba-ab46-4250-9568-4bd255193ff7; Content Version a7530606-dafe-4217-bc22-dff67af86ea3. Title: Cook and Hammack's FOMC dissent: a preference for a higher rate.
- Append-only reconstruction manifest records input/output versions, output body SHA256, retained claim C3, paragraph hashes/claim relations, source ID and interactive Codex reconstruction method. It does not create a human review or change original verification flags. Assessment remains machine_passed=false/generation_ready=false/publish_ready=false; minor warnings are follow-ups under existing policy.
- Actual operational eligibility with the new code: evidence passed, reasons [], three substantive paragraphs retained. Existing provenance remains chatgpt_scheduled_export; no new import or manual-publish request.

## Validation / runtime

- Focused pytest 84 passed, Ruff/mypy passed; isolated Python wheel built. Two fixture failures encountered during validation were corrected (copy-protection fixture contained an exact excerpt; enqueue mock expected the old SQL spelling). No Dashboard checks/build requested or performed.
- Runtime reflection uses existing server-common validation marker and individual stop/start scripts after successful backend validation. The generic apply script always builds Dashboard, conflicting with this task's explicit minimum-build requirement; it was not used. Only API and affected Research/Publication Workers are restarted gracefully. Existing Dashboard build remains running.
- Final publication, remaining failures, runtime identity and Git outcomes follow below.
