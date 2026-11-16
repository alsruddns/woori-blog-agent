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
- Local Codex automation registry at `C:\Users\achie\.codex\automations` contained exactly 15 definitions: 14 ACTIVE and `automation-10` PAUSED (the Chinese task). No DE/PT-BR/VI task definitions or the operator-reported six new task IDs were present in this checkout's Local registry. Current `rrule` values are shown below; timezone and next-run data are not stored in these TOMLs and were not independently verified in the Scheduled UI. No Codex automation was created, deleted, or edited; the requested count of 21 and actual article generation/Import cannot be claimed complete.

| Existing Local task ID | Status | Stored RRULE |
|---|---|---|
| `ai` | ACTIVE | `FREQ=WEEKLY;BYDAY=FR;BYHOUR=16;BYMINUTE=30` |
| `automation` | ACTIVE | `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=18;BYMINUTE=30` |
| `automation-10` | PAUSED | `FREQ=WEEKLY;BYDAY=TU,WE,TH,FR,SA;BYHOUR=17;BYMINUTE=0` |
| `automation-2` | ACTIVE | `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=17;BYMINUTE=30` |
| `automation-3` | ACTIVE | `FREQ=DAILY;BYHOUR=10;BYMINUTE=30` |
| `automation-4` | ACTIVE | `FREQ=WEEKLY;BYDAY=MO,TH;BYHOUR=16;BYMINUTE=30` |
| `automation-5` | ACTIVE | `FREQ=WEEKLY;BYDAY=SA;BYHOUR=12;BYMINUTE=0` |
| `automation-6` | ACTIVE | `FREQ=WEEKLY;BYDAY=TU,WE,TH,FR,SA;BYHOUR=7;BYMINUTE=0` |
| `automation-7` | ACTIVE | `FREQ=WEEKLY;BYDAY=TU,WE,TH,FR,SA;BYHOUR=9;BYMINUTE=0` |
| `automation-8` | ACTIVE | `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=20;BYMINUTE=0` |
| `automation-9` | ACTIVE | `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=16;BYMINUTE=0` |
| `fed-sec` | ACTIVE | `FREQ=WEEKLY;BYDAY=TU,WE,TH,FR,SA;BYHOUR=11;BYMINUTE=0` |
| `it-ai` | ACTIVE | `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=12;BYMINUTE=0` |
| `k-beauty` | ACTIVE | `FREQ=WEEKLY;BYDAY=TU,FR;BYHOUR=13;BYMINUTE=30` |
| `k-pop` | ACTIVE | `FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=15;BYMINUTE=0` |
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
- `apps/dashboard/app/blogger/manager.tsx`
- `apps/dashboard/app/config/manager.tsx`
- `apps/dashboard/app/imports/external-import-workspace.tsx`
- `apps/dashboard/app/manuscripts/workspace.tsx`
- `apps/dashboard/app/publishing/publication-manager.tsx`
- `apps/dashboard/app/sources/legacy-workspace.tsx`
- `docs/development/P5-CODEX-113.md`

## Verification and service state

- Focused API tests: 80 passed (`test_language_codes`, `test_content_imports`, `test_multilingual`, `test_editorial_intelligence`).
- Ruff: passed for changed Python modules and tests.
- Dashboard ESLint and TypeScript typecheck: passed.
- Full safe-reflection validation: API suite 64 passed, Ruff passed, mypy passed, wheel build passed, Dashboard ESLint/typecheck/production build passed. The script gracefully stopped only project-owned API, Dashboard, Research Worker, and Publication Worker; no force-kill was used. PostgreSQL and other projects remained untouched.
- After reflection: API PID 27000, Dashboard PID 31636, Research Worker PID 31708, Publication Worker PID 8824. API `/health` and Dashboard `/research` returned HTTP 200; both Worker heartbeats are fresh and applied commit `18f32b8217918ff5abe12fa5942debe73c29528a`.
- Chromium read-only UI verification visited `/config`, `/blogger`, and `/imports` at 1440×1000 and 390×844. Both sizes had no horizontal overflow or page errors; all new language codes and Blogger URLs were visible, and `/api/config/languages` returned 200. No Blogger write was sent.
- Publication Worker remained in `automatic_publication_suspended` / manual mode with no live queued or due jobs; operator approval remains OFF. No active Research authoring job existed at restart.

## Remaining work / blockers

1. The six operator-reported DE/PT-BR/VI Codex Desktop schedules were not in the actual Local automation registry. The owner must make those already-created tasks visible in the current Local project/account, after which their true IDs, schedules, timezone, enabled state, and next runs can be verified. No task was synthesized to fill the gap.
2. No scheduled article was generated or imported for DE/PT-BR/VI. No content-generation provider was enabled by language registration.
3. Blogger write permission was not tested; no publication approval or write gate was changed. New blogs remain non-publishable until the separate existing eligibility and approval gates pass.

## Commit

- Implementation commit: `18f32b8217918ff5abe12fa5942debe73c29528a`.
- Dashboard follow-up commit: `fe840a83de6e397940ff84eba765fb625602ee0e`.
- Reflection/documentation commit: recorded in the subsequent Git history entry for this file.

## Follow-up UI state and final reflection

- Follow-up UI commit: `fe840a83de6e397940ff84eba765fb625602ee0e`; the Blogger/language manager explicitly labels inactive ZH-CN as `운영 중단` while preserving historical records.
- Before this follow-up is reflected, API PID 27000, Dashboard PID 31636, Research Worker PID 31708, and Publication Worker PID 8824 were still healthy. API and both worker heartbeats reported applied source `18f32b8217918ff5abe12fa5942debe73c29528a`; Dashboard also served the prior build. No active authoring or publication work was found, and no process was force-stopped.
- Dashboard-only reflection completed by `scripts/apply-verified-changes.ps1 -Apply -Confirm:$false`: the Dashboard stopped gracefully and restarted as PID 4200, serving the committed build `02b823c8dfcee9736807550de63361e52d83ecea`; API and both Workers remained running. API PID 27000, Research Worker PID 31708, and Publication Worker PID 8824 retained fresh health/heartbeats and revision 16. No active authoring job or live-due publication job was observed.
- Post-reflection browser verification: `/blogger`, `/config`, and `/imports` returned HTTP 200 at 1440×1000 and 390×844. No horizontal overflow or page errors. `/blogger` and `/config` visibly showed ZH-CN and `운영 중단`; inactive ZH-CN was absent from the active Import language selector.
- Full safe-reflection checks passed: API suite 64 passed, Ruff, mypy, wheel build, Dashboard ESLint, TypeScript typecheck, and production build. Earlier focused suite: 80 passed. Blogger writes remained 0.
- Append-only audit events: start ID 313359; runtime reflection ID 313859; completion ID 313878. No schema migration was required. Existing untracked artifacts and `stash@{0}` were preserved.
