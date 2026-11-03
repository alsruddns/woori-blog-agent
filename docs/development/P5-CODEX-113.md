# P5-CODEX-113 — New Blogger and scheduled-language integration

## Change record

- Task: P5-CODEX-113
- Date: 2026-11-03 (Asia/Seoul)
- Branch and starting HEAD: `develop`, `f8b89657905b8feae611586a594a5fe741b749d3`
- Reason: connect the operator-created DE, PT-BR, and VI Blogger blogs; stop new ZH-CN operations; allow those BCP 47 languages through the existing safe Import and Dashboard configuration paths.
- Existing issue: the language DTOs and Import/SEO validation used a fixed four-language list, the Import workspace also used a fixed language list, and the DB contained only EN/KO/JA/ZH-CN Blogger mappings.
- Before: four active languages and four active Blogger mappings; ZH-CN was active. Local Codex automation registry showed 15 entries, not 21.
- After: six active languages and six active Blogger mappings; ZH-CN language/blog inactive, with their previous records retained. New languages are valid Import targets but no generation, translation, quality, or auto-publication adapter was enabled by this change.

## Findings and operations

- New operator-created Blogs were read-verified using the existing connected Blogger OAuth connection `4839f8b9-69c8-4ce4-b1c1-5b71e96d5896`. The verification uses Blogger reads (blog lookup by URL and an author-view posts listing) and does not prove or test write permission.
- Added mappings:

| Language | Blog ID | URL | Result |
|---|---:|---|---|
| DE | `5857406989226346280` | `https://trend-journal-de.blogspot.com` | Connected and read-verified |
| PT-BR | `2780805325207451782` | `https://trend-journal-br.blogspot.com` | Connected and read-verified |
| VI | `2392412558893856604` | `https://trend-journal-vn.blogspot.com` | Connected and read-verified |

- Existing EN, KO, JA mappings were retained. The existing ZH-CN blog ID `1931836538202286191`, URL, OAuth mapping, and content history were retained while its language and blog `active` flags were turned off in one DB transaction. No queued or publishing Chinese job existed at the time of change.
- Chinese historical records remain: 3 external imports, 3 import versions, 4 content versions, 2 completed publishing jobs, and 2 publication records. No records were deleted.
- Local Codex automation registry at `C:\Users\achie\.codex\automations` contained exactly 15 definitions: 14 ACTIVE and `automation-10` PAUSED (the Chinese task). No DE/PT-BR/VI task definitions or the operator-reported six new task IDs were present in this checkout's Local registry. Their IDs, RRULEs, next runs, and executions therefore remain unverified. No Codex automation was created, deleted, or edited; the requested count of 21 and actual article generation/Import cannot be claimed complete.
- Existing active operational settings were preserved at revision 16: Trends collection and writing ON; overall, Trends, and scheduled auto-publication ON; manual publication ON; emergency stop OFF; global publish interval 15 minutes; global KST LIVE cap 100. Operator publication approval remains OFF. No operational publication setting was changed.
- Backup verified before DB changes: `backups/20261103T031936Z.dump` (42,112,486 bytes). No schema migration was needed.
- Blogger external calls: 7 read requests in total for this phase (one account blog listing already recorded during preflight, plus two reads per new blog mapping). Blogger POST/PATCH/DELETE/write requests: 0.
- Append-only DB audit: `agent.p5_codex_113.started`, event ID 313359. Blogger connection verification and language/blog state changes were also recorded by the existing DB audit path and explicit status-change events.

## Code changes

- Introduced shared BCP 47 validation/canonicalization and removed fixed language allowlists from Import, duplicate-check, localization, preview, and SEO metadata DTOs.
- New Imports require every declared audience language to be registered and active. Scheduled-origin validation also requires an active language and active matching Blogger, so new ZH-CN Imports/origins are rejected while old imports remain readable.
- Added DB-backed `/admin/config/languages` and `/admin/config/blogs` listing routes and enabled the same-origin Dashboard proxy to return GET data, rather than a synthetic save response.
- Import lists use DB display names; localization targets are fetched from active languages only. Manuscript, source, and publication views gained DE/PT-BR/VI display names. Existing language records remain visible for historical content.
- Added reviewed labels for DE/PT-BR/VI to the existing taxonomy and extended country-to-language suggestions for DE/BR/VN. This did not add Google Trends collection regions or enable automatic publication.
- Kept generation/translation/quality adapter registries empty and `automatic_publishing_allowed` fail-closed.

## Files

- `services/api/woori/language_codes.py`
- `services/api/woori/multilingual.py`
- `services/api/woori/content_imports.py`
- `services/api/woori/editorial_html.py`
- `services/api/woori/editorial_seo.py`
- `services/api/woori/editorial_taxonomy.py`
- `services/api/woori/localized_publications.py`
- `services/api/woori/research_routes.py`
- `services/api/woori/automation_auto.py`
- `services/api/woori/publication_worker.py`
- `services/api/tests/test_language_codes.py`
- `services/api/tests/test_multilingual.py`
- `apps/dashboard/app/api/config/[...path]/route.ts`
- `apps/dashboard/app/imports/external-import-workspace.tsx`
- `apps/dashboard/app/manuscripts/workspace.tsx`
- `apps/dashboard/app/publishing/publication-manager.tsx`
- `apps/dashboard/app/sources/legacy-workspace.tsx`
- `docs/development/P5-CODEX-113.md`

## Verification and service state

- Focused API tests: 80 passed (`test_language_codes`, `test_content_imports`, `test_multilingual`, `test_editorial_intelligence`).
- Ruff: passed for changed Python modules and tests.
- Dashboard ESLint and TypeScript typecheck: passed.
- UI/browser and full end-to-end schedule execution were not verified. The running Dashboard/API still report the previously applied commit until a safe committed-source reflection is performed.
- At inspection: Dashboard PID 32344, API PID 35896, Research Worker PID 14128 (fresh heartbeat, applied commit `12aa235c4eccf7094414ee9eb4eb2d41f2ff43a1`), Publication Worker PID 20084 (fresh heartbeat, applied P112 commit). No active Research authoring job and no queued/live-due Publishing Job existed. These project-owned services were not force-stopped.
- No API or Worker restart was performed before the documented safe-reflection procedure. Latest code is not yet active in existing processes; production runtime application remains incomplete until verified restart.

## Remaining work / blockers

1. The six operator-reported DE/PT-BR/VI Codex Desktop schedules were not in the actual Local automation registry. The owner must make those already-created tasks visible in the current Local project/account, after which their true IDs, schedules, timezone, enabled state, and next runs can be verified. No task was synthesized to fill the gap.
2. No scheduled article was generated or imported for DE/PT-BR/VI. No content-generation provider was enabled by language registration.
3. Blogger write permission was not tested; no publication approval or write gate was changed. New blogs remain non-publishable until the separate existing eligibility and approval gates pass.
4. Safe service reflection, browser validation at 1440/390px, and the remote Git commit/push are pending final verification.

## Commit

- Commit hash: to be recorded from `git log` after commit; no self-referential hash is fabricated.
