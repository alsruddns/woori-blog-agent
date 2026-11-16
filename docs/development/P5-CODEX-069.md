# P5-CODEX-069 — Manual Blogger eligibility read-model repair

- Work ID: P5-CODEX-069
- Date: 2026-10-30 (Asia/Seoul)
- Branch: `develop`
- Reason: the imported FOMC manuscript showed that manual Blogger eligibility could not be confirmed; distinguish a missing read-model field from a database failure and restore the existing manual publish path.

## Diagnosis

- Target import: `b4c45d23-0c74-4b12-92fd-382633093afa`; origin `manual_codex_import`; latest import version 7 is `ed85a5c4-a387-40ad-84c7-8299cddee46f`; linked content version `65133867-88d3-427a-bc24-b6994625eb38`.
- The live Dashboard detail request and publication-state request both returned HTTP 200. The publication response omitted `manual_publication` (it was `{}`), while `auto_publication_failure=false`. The API computed manual eligibility only when the latest auto-failure audit event existed. Consequently the Dashboard fell back to “server cannot confirm manual eligibility”; this was not a malformed legacy FOMC row or a failed eligibility SQL query.
- The operations database reports schema 58. Runtime API and Dashboard were both applied at commit `477c77bf98ca2db591bf0b8c638aed2194220fc8`. The Korean blog record is active, connection-verified, connected with exact Blogger write scope, emergency stop is off, and the Publication Worker heartbeat is fresh in `scheduled-auto-and-manual` mode.
- The existing API stderr also contains a prior `POST /admin/publications/manual-live-requests` log with SQLSTATE `P0001`. It has no PostgreSQL diagnostic constraint/table/message, and PostgreSQL logs contain no matching detailed entry. This prior POST failure is distinct from the reproduced HTTP 200 eligibility-read defect. The POST was not retried: it creates an approval event and a live Publishing Job and must only follow a new user click. No cause was invented for that historical P0001 entry.

## Change

- Compute and return the manual publication eligibility read model for every linked content version, independently of scheduled-auto failure history.
- Include an explicit `status` (`eligible` or `blocked`) alongside the existing boolean and blocker list. Existing hard gates remain in `_manual_publication_blockers`; quality, source, and editorial gaps remain follow-ups. No approval, publication, OAuth, or database state was changed.
- When the state request fails, the Dashboard now displays the actual safe HTTP status and API error code rather than a generic “eligibility unavailable” message.

## Files

- `services/api/woori/publications.py`
- `services/api/tests/test_publications.py`
- `apps/dashboard/app/imports/external-import-workspace.tsx`
- `docs/development/P5-CODEX-069.md`

## Validation and runtime

- `services/api/tests/test_publications.py`: 32 passed against the isolated test database.
- Ruff: passed. mypy on `services/api/woori/publications.py`: passed.
- Dashboard ESLint and TypeScript: passed.
- Before fix, actual Dashboard proxy responses: detail HTTP 200; publication-state HTTP 200 with the manual field empty. No Blogger POST was issued.
- `apply-verified-changes.ps1 -Apply -Confirm:$false`: change-scoped API tests (32 passed), Ruff, mypy, Dashboard ESLint/typecheck, wheel build, and isolated Production Build passed. It safely reflected commit `cea08cf87f9930ab3c45ad6a2735f86838aa452a` to API, Dashboard, and Publication Worker; no Research Worker restart was needed.
- Post-reflection requests through the actual Dashboard proxy: manuscript detail HTTP 200; `/api/publications/scheduled-auto-state?import_id=b4c45d23-0c74-4b12-92fd-382633093afa` HTTP 200. The exact current version remains v7 / `65133867-88d3-427a-bc24-b6994625eb38`. Manual status is `eligible=true`, blockers 0, follow-ups 6, manual jobs 0, auto failure false, emergency stop false, OAuth write scope true, and Blogger connection verified. This eligibility response did not create an approval, Job, or Blogger request.
- Runtime: API 8100 and Dashboard 3100 return HTTP 200 and report applied commit `cea08cf87f9930ab3c45ad6a2735f86838aa452a`; Publication Worker PID 13872 is fresh in `scheduled-auto-and-manual` mode; Research Worker PID 56792 remains fresh and was not restarted. Queue and live-job counts remain 0.
- Browser limitation: the Windows Computer Use bridge reported its native pipe unavailable; a separate Playwright browser launch was rejected by the command execution policy. Therefore this run verified the live API/proxy data and the button's source-level disabled calculation, but did not claim screenshot-backed visual browser validation. With the returned eligible status, `admin`/`확인완료`, and the three attestations checked, the component's disabled predicate is false. No publish button was clicked.
- Git commit and push are recorded by subsequent Git history. `.playwright-mcp/` remains ignored/untracked and is excluded.

## Remaining

- Do not call the manual-live-requests POST or Blogger API until the user clicks the exact-content publish confirmation. A prior POST SQLSTATE `P0001` was logged without enough PostgreSQL detail to attribute it to a specific trigger; it is not reproduced by the current read request. This task confirms manual eligibility only; it does not complete Blogger publication.
- Actual public post ID/URL: none created in this task.
