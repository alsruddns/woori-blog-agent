# P5-CODEX-056 — Imported manuscript representative lists

- Work date: 2026-10-30 (Asia/Seoul)
- Branch: `develop`
- Reason: Imported manuscripts and the publication review queue repeated the same article across separate import records.
- Before: The import list collapsed linked lineage versions only, and applied its SQL limit before any cross-import comparison. The publication review read model suppressed exact body hashes only. Same-title, similar-body imports remained visible.
- Database inspection: Read-only query of `Official Agency policy change and reporting schedule` returned 13 import IDs and 13 linked content versions, zero parent links, two distinct raw body hashes (6 imports at 571 characters and 7 at 684 characters), and body similarity 0.91. These were separate reimports, not linked revisions. No records or audit events were changed.
- Representative: newest import `426dc88b-040a-4dde-965d-ca925bb89196`, content version `75c72fc9-3300-4a69-9be4-97da95d32a1b`, import version `d2ef8833-79fa-438d-b90c-836141e8273b` (v2), received 2026-10-30 01:47:02.904648 KST.
- After: The read model keeps the newest same-lineage row, or same-blog/same-language exact body, or same normalized title with body similarity >= 0.88 and length ratio >= 0.70. Title alone is never sufficient. Unknown target blogs are isolated by import ID. Search, source filters, totals, and pagination apply after representative selection.
- History: Detail returns matching prior duplicate-import metadata, body hashes, and bodies in the existing history tab. The original import/version/audit records remain intact.
- Publication management: The GET list read model uses the same conservative matching rule to suppress near-identical rows from the review list. No approval, queue creation, Worker dispatch, or Blogger-write logic changed.
- UI: Imported manuscript lists use server-side source filtering, search, totals, and pagination. List links pass both `open_import_id` and `open_content_version_id`; the detail screen flags if the listed version changed before it opened.
- Tests: Focused API tests and helper tests (17 passed); Ruff; Dashboard ESLint, TypeScript typecheck, and production build passed. The selected Playwright E2E files could not run because the configured base URL `http://127.0.0.1:13100` refused connections; no runtime service was started or restarted. Actual operation database list smoke: 1 representative, 12 suppressed; detail history returned all 12 records and two body hashes.
- Files: `services/api/woori/content_representatives.py`, `services/api/woori/content_imports.py`, `services/api/woori/publications.py`, `services/api/tests/test_content_representatives.py`, `services/api/tests/test_content_imports.py`, `apps/dashboard/app/imports/external-import-workspace.tsx`.
- Commit: recorded by Git history after commit; no self-referential hash.
- Remaining: The running Dashboard/API were not restarted or browser-tested in this code-only task. Auto mode, Publishing Worker, job creation, and Blogger live publication were not changed or exercised. `.playwright-mcp/` directories were excluded.
