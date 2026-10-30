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
- Initial live DB status: schema 58; manual Import/version/content IDs above. Runtime application of the fix and post-fix eligibility blockers are to be recorded after the committed-code validation/reflection step.
- Git commit and push are recorded by subsequent Git history. `.playwright-mcp/` remains ignored/untracked and is excluded.

## Remaining

- Do not call the manual-live-requests POST or Blogger API until the user clicks the exact-content publish confirmation. A prior POST SQLSTATE `P0001` was logged without enough PostgreSQL detail to attribute it to a specific trigger; it is not reproduced by the current read request.
- Actual public post ID/URL: none created in this task.
