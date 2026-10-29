# P5-CODEX-037 — separate scheduled article run

This is a **new, one-time Codex scheduled task instruction** for the local project. It does not replace, edit, or delete the existing probe task. Do not register it from repository code. The operator must create it in the official Codex Scheduled UI and select this checkout. The local app and project must remain available during the run.

## Purpose and fixed input

Create at most one Korean draft from this existing immutable Research Package:

- Package ID: `c0b6f2b2-7a74-4b3f-a4f1-f4219c12321d`
- Package payload SHA-256: `cbfee121e31f426372393553667ddb7486f616918976054119c9e34182e15481`
- Snapshot: `.local/gpt-scheduled-import/research/P5-CODEX-037-c0b6f2b2-7a74-4b3f-a4f1-f4219c12321d.research.json`
- Target: language `ko`, blog ID `3321654108096579717`, `https://trend-ko.blogspot.com`
- Package state: `evidence_collected_pending_human_review`; `generation_ready=false`; `human_review_required=true`; `publish_ready=false`
- Evidence: one official Federal Reserve statement source and 11 source-linked fact spans; independent-source count is zero.

The package topic is recorded as `fed meeting` (SG observation). The newest four-hourly selection is a separate triage record: three India IPO queries and one HK `fomc` query. None of those four has a linked source or package. The HK topic is not automatically merged with the existing SG Fed package. Do not create an additional package or claim that the shortlisted topic was researched by this task. Use the existing package only for a statement-focused draft, and do not claim independent corroboration.

## Task instructions

1. Read the snapshot and the schemas `docs/schemas/woori-content-import-1.0.schema.json` and `docs/schemas/woori-scheduled-content-import-1.0.schema.json`.
2. Confirm the snapshot package ID and hash. Use only its supplied Federal Reserve source and exact evidence spans. Do not browse or fetch other URLs, infer market reaction, or add facts from memory.
3. Write one concise, reader-centered Korean expert column about what the October 28, 2026 FOMC statement says and what its wording does and does not establish. Explain sourced facts first and clearly label bounded interpretation. Omit any claim that cannot be matched to an exact supplied span. Do not pad the article.
4. Create one `woori-scheduled-content-import/1.0` JSON envelope using the existing schemas exactly. Required fields include source and claim mappings, dates, SEO metadata, target blog, `research_package_id`, `generation_method: "chatgpt_scheduled_export"`, actual execution timestamp, and a unique occurrence ID. `body_markdown` must be Markdown, not raw HTML. Do not add approval fields, `auto_eligible`, or `publish_ready`.
5. For the source-rights field, preserve the package's note that Board-authored text is public domain unless indicated, cite the Board, and exclude third-party material. Set the import's rights status conservatively; a populated value does not mean rights review is complete.
6. Write UTF-8 to `.local/gpt-scheduled-import/incoming/<unique-name>.part`, finish and parse the JSON, then atomically rename it on the same volume to `.local/gpt-scheduled-import/ready/<unique-name>.ready.json`. Never overwrite a file. Do not call APIs, run scripts, modify the database, create publishing jobs, or call Blogger.
7. Report the final file path and SHA-256 only if the scheduled run itself wrote the file. If no file can be safely produced, report the exact schema/evidence/permission blocker and leave `ready/` untouched.

## Expected result

The existing Import Worker may import a successfully delivered envelope and run its deterministic assessment. That is an import/draft result only. This package still requires human semantic and rights review; the current project policy keeps `publish_ready=false`, does not create a Blogger job from scheduled import, and blocks live writes. No publication or auto-eligibility success may be claimed by this task.

## Operator check after the scheduled run

Verify in the official Scheduled UI that this was an automatic execution, record whether it prompted for file-write approval, and check the file timestamp/hash. Then let the existing Import Worker process the ready file and verify the DB import receipt and content version. Do not call a manually launched run an unattended success.
