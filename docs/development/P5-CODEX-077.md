# P5-CODEX-077: K-POP category compatibility

Date: 2026-10-30 KST. Branch: develop. Scope: category contract and research artifact persistence only.

## Before and cause

- JSON Schema item.category enumerated eight editorial slugs. Pydantic ContentImport validates against editorial_taxonomy. Scheduled schema references the same item and Research Worker validate_envelope uses ScheduledImportEnvelope. All lacked entertainment/music. DB categories has only id/slug (no hierarchy); external_content_imports.category references slug. Legacy `k-pop` exists from migration 007 but is not an accepted editorial Import slug.
- Valid snapshot: `.local/gpt-scheduled-import/research/kpop-issue-2026-10-30-ko-20261030T150022KST-7f4c2f.research.json`, 3052 bytes. It records original k-pop slot `2026-10-30T15:00:00+09:00`, occurrence `codex-slot:k-pop:20261030T1500KST`, source-led scheduled_article context and category blocker. TXT/BIGHIT and TWS/PLEDIS Weverse URLs and evidence are retained. These historical observations were not reasserted as freshly checked facts in this development session.
- Empty artifacts in that same directory: `kpop-issue-2026-10-30-ko-20261030T150022KST-7f4c2d.research.json` (created 15:01:07 KST) and `...-7f4c2e.research.json` (15:01:36 KST), both 0 bytes. Original scheduled session trace `01a18b64-28da-7761-99d3-1657b890e842` shows direct Path.write_text(...,encoding='utf-8') after opening final paths; surrogate encoding failure left empty files. The second traceback explicitly reports UnicodeEncodeError, surrogates not allowed. This was final-file creation before successful encoding, not a Worker quarantine or DB failure. Earlier JS TextEncoder/btoa failures occurred before any write. All three existing files are preserved.

## Changes and resulting contract

- Added single canonical `entertainment` to editorial registry and content JSON Schema. Scheduled schema/Pydantic/Worker inherit it. Prior eight values and historical DB categories are unchanged. No hierarchy is invented: music/K-POP detail uses existing title/body/SEO terms.
- Exact suggested labels: ko `엔터테인먼트`, en `Entertainment`, ja `エンタメ`, zh-CN `娱乐`. Free-form `K-POP` labels remain unsupported unless separately reviewed in the future. Trends-only issue label rules remain unchanged.
- Migration 060 inserts only entertainment ON CONFLICT DO NOTHING plus migration/audit events. Existing DB IDs, category references, manuscript versions, provenance and publishing safeguards are unchanged. Runner and isolated-test provisioner support schema 60. A prior test's fixed latest-version assertion was changed to assert its required migration remains in the runner; the existing migration-runner guard checks the actual latest version.
- Added research_snapshot read/write helpers and `scripts/write-research-snapshot.py`: reject empty/non-object/invalid JSON or unencodable Unicode before opening output; encode UTF-8, write/fsync same-directory `.part`, then publish with an atomic exclusive hard link and remove only the helper's temporary file. Existing destinations cannot be replaced. Readers reject empty artifacts. No research-folder scanner existed that could import snapshots as manuscripts; the Worker still consumes only validated ready envelopes.
- AGENTS.md and editorial-taxonomy.md document category selection and safe snapshot command. All 15 saved Automation TOMLs already instruct reading suggested_labels/current taxonomy. No Automation prompt, schedule, model or target was changed; k-pop remains weekday 15:00, Korean, scheduled_article. Occurrence and generation-stage duplicate contracts remain intact.

## Validation and DB application

- Focused category/Import/inbox/snapshot tests: 41 passed. Includes entertainment scheduled_article payload → shared Pydantic validation → atomic ready handoff → real API/DB Import in isolated forced-rollback DB, scheduled origin recording, duplicate prevention, prior stocks compatibility and zero Blogger writes.
- Migration guard/post-publication review/occurrence/duplicate regression: 36 passed. Ruff passed; mypy passed for taxonomy/snapshot modules. No Dashboard code changed; no frontend build required.
- Isolated DB provisioned to schema 60; operational DB CONNECT denial for test app verified. Synthetic articles and ready files exist only under isolated test transactions/tmp paths, never operational inbox.
- Operational backup: `backups/20261030T064705Z.dump`, 2297254 bytes, archive catalog verified by existing backup.py. Existing migrate.py applied schema 60, status confirmed; second runner invocation succeeded without reapplying migration. Rollback: preserve schema/category/audits; use forward correction or restore only through reviewed backup procedure, never delete referenced category rows. Older code would reject new entertainment input, so do not roll back validator alone after new Imports.
- An initial app-role read of schema_migrations was correctly denied; schema status was then checked via the existing owner migration CLI. No privilege bypass/grant was added. Start audit was recorded after that failed transaction, with the delay explicitly noted; migration audit had already recorded actual application.
- Post-migration operational content counts: imports 25, versions 400, Jobs 4. No production article or approval request was created for testing.

## Runtime and remaining scope

Runtime reflection and final verification are appended below. This development invocation is not a Codex Desktop scheduled execution: no new scheduled article, ready envelope, production Import or Blogger success is claimed. The preserved 15:00 slot was not replayed or relabeled. A genuine next scheduled execution must freshly verify facts and local duplicates before using entertainment, and must retain its actual occurrence identity. No public postId/URL was created by this work.

Changed files: AGENTS.md; docs/architecture/editorial-taxonomy.md; docs/schemas/woori-content-import-1.0.schema.json; scripts/060_entertainment_category.sql; scripts/migrate.py; scripts/provision-test-database.py; scripts/write-research-snapshot.py; services/api/woori/editorial_taxonomy.py; services/api/woori/research_snapshot.py; services/api/tests/test_content_imports.py; test_scheduled_import_inbox.py; test_post_publication_reviews.py; test_research_snapshot.py; this record. Commit hashes follow in git log/final runtime record.

### Final reflection

- Code commit: `98ca297` (full hash in git log). At 15:50 KST, existing lifecycle scripts gracefully stopped Research PID 22828 after its current cycle and API listener 15620. New API listener 12932 (runner 39800), Research PID 37212 with fresh running heartbeat and applied source commit. Dashboard PID 38812 and Publication PID 51292 were unchanged. Publication remains `operations-scheduled-auto-and-manual`; no publishing policy code changed.
- Live authenticated `/admin/research/content-imports?limit=1` returned HTTP 200 and the entertainment category. `/health` and Dashboard `/imports` returned HTTP 200. No Dashboard build was needed.
- All 15 Automation TOML byte hashes remain unchanged. The valid snapshot SHA-256 remains `1c28575625e93060dc9f949618735c97cc114f89c2d80c7d55f404d22db07b49`; both historical empty artifacts remain present, rejected by read_snapshot, SHA-256 `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. No final snapshot was overwritten or deleted.
- Final operational counts remain imports 25 / versions 400 / Jobs 4. Task start/completion and migration events were appended without review/approval events. No new operational article, Job or Blogger post was generated.
- Total focused checks: 77 tests passed (41 + 36), Ruff and mypy passed, whitespace checks clean. Actual next scheduled K-POP execution, ready handoff and operational Import are not yet observed; isolated Import compatibility is verified. Publishing remains a separate downstream result.
