# P5-CODEX-049 - Scheduled source evidence and publication readiness

- Work date: 2026-10-29 (Asia/Seoul)
- Branch: develop
- Status: implementation and operational evidence capture complete; publication remains held
- Commit: recorded by the following Git history entry (Rule 1 self-reference)
- Related policy: `docs/operations/zero-cost-policy.md`

## Reason and before state

The scheduled Japanese manuscript import `9bd1706b-5e0a-4cb4-a7fd-d4949b9ecad7` had no source-bound live retrieval proof. The scheduled auto worker therefore held it. Worker process discovery in `scripts/stop.ps1` matched the project venv launcher rather than the actual heartbeat child on Windows, preventing a cooperative restart.

## Changes

- Added `scheduled_source_evidence` with an exact URL catalog containing only the public Japanese fuel-support campaign root page. Requests use the shared `external_policy` allowlist, bounded response/time limits, a persistent 12-per-hour cap, 30-second minimum spacing, and append-only audit events.
- Captured title, HTTP status, retrieval time, source body and visible-text SHA-256, visible dates/numbers, exact imported excerpt matches, and reuse-rights status. Rights remain `unknown` when a reuse notice is absent or not bound to the exact host. The collector does not convert URL reachability into factual, semantic, or rights approval.
- Restricted claim date/number checks to exact linked paragraph spans. Bumped the capture policy to v2 so a corrected capture appends a new event rather than reusing the earlier extractor result.
- Added an authenticated import evidence endpoint and connected scheduled Inbox processing to capture evidence after origin provenance is recorded. Capture failure does not erase or falsely approve an imported item.
- Tightened the stop process identity checks to recognize the exact venv-launched Python child for both Publication and Research Workers; the heartbeat process receives the cooperative stop marker, while only its verified checkout launcher is tracked for exit.

## Operational evidence

- API: project-managed restart completed; `GET http://127.0.0.1:8100/health` returned `ok`. The new evidence route returned 401 without the admin credential, confirming the authentication gate is active.
- Research Worker: original heartbeat PID 35824 was cooperatively stopped after correcting launcher/child identification, then `scripts/run-worker.ps1` started a fresh worker. Current process/heartbeat was verified through `scripts/status.ps1` and the operations database.
- Publication Worker: previous PID 26768 was cooperatively stopped through `scripts/stop.ps1`; `scripts/start-publication-worker.ps1 -Mode scheduled-auto` started PID 41992 and its heartbeat is fresh. It reports scheduled policy enabled for four registered blogs, but global mode remains manual, general Auto remains off, and live public writes remain disabled.
- Existing manuscript inspected: import `9bd1706b-5e0a-4cb4-a7fd-d4949b9ecad7`, version `45d52e29-b6d7-40be-b79b-97d91f339069`, content version `b6abf4f0-4bf8-4ddc-b01e-fdc183f2a9f6`, SHA-256 `8a47ebcea8e6472b4f528abb0bfc66c8cfc680d1e12115fa1c907eaccb05f2fa`.
- One exact allowlisted GET to the Agency for Natural Resources and Energy campaign page returned HTTP 200. The v2 proof is stored in `research.source.live_document_verified`; body SHA-256 `a7e93e29829215a9328fbf3eec895eadda2c2f4f7c755047028b42d78728f021`. The page title was captured, but its publication date metadata was absent. The imported C1-C6 excerpts had zero exact matches on this S5 page. The four other URLs were not fetched because they are outside the reviewed allowlist. Reuse terms for the microsite remain unknown.
- Automatic assessment remains `held`: `source_rights_not_cleared`, `source_live_verification_missing`, `source_evidence_spans_missing`, `claim_span_not_found_in_live_source_evidence`, and `source_rights_not_machine_verified`. No new Research Package or manuscript version was fabricated.
- Actual queue counts remain zero for scheduled jobs; no Blogger create, publish, update, or delete request occurred. The exact first-publication approval remains absent. No public post ID or URL was created.

## Changed files

- `services/api/woori/scheduled_source_evidence.py`
- `services/api/woori/external_policy.py`
- `services/api/woori/content_imports.py`
- `services/api/woori/scheduled_import_inbox.py`
- `services/api/tests/test_scheduled_source_evidence.py`
- `services/api/tests/test_scheduled_import_inbox.py`
- `scripts/server-common.ps1`
- `scripts/stop.ps1`
- `scripts/tests/stop.Tests.ps1`
- `docs/operations/zero-cost-policy.md`
- `docs/development/P5-CODEX-049.md`

## Verification

- Ruff on changed Python source and tests: passed.
- Pytest source evidence, scheduled Inbox, and scheduled evidence assessment tests: 23 passed.
- PowerShell parser for `server-common.ps1` and `stop.ps1`: passed.
- Pester `scripts/tests/stop.Tests.ps1`: 13 passed, 0 failed.
- Python compileall on changed runtime modules: passed.
- `git diff --check`: passed (only Windows CRLF normalization warnings).
- Live evidence capture was read-only to the source provider and append-only to audit records; Blogger writes were not attempted.

## Remaining blockers

- The existing Japanese manuscript has no exact claim spans on S5, four other sources have no live proof from the reviewed catalog, its cited package has no demonstrated reuse permission for this microsite, and its claim review is still absent.
- Therefore it is not auto-eligible; no scheduled Publishing Job is created and the exact first-publication approval cannot yet be requested for a publication-ready version.
- A future original scheduled manuscript must cite reviewed source URLs and exact excerpts. The source catalog must be expanded only after each source/rights path is reviewed; no broad fetching is enabled.
- Auto/public writes remain disabled at the live adapter. No public URL exists from this work.
