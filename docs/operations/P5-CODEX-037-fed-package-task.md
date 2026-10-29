# P5-CODEX-037 — Fed Research Package scheduled draft

Use this as the body of the existing local-project Codex scheduled task after confirming it targets `C:\Users\achie\git\woori-blog-agent`. Do not create a second recurring task for this one-time validation.

## Inputs

- Research snapshot: `.local/gpt-scheduled-import/research/P5-CODEX-037-c0b6f2b2-7a74-4b3f-a4f1-f4219c12321d.research.json`
- Research Package: `c0b6f2b2-7a74-4b3f-a4f1-f4219c12321d`
- Package SHA-256: `cbfee121e31f426372393553667ddb7486f616918976054119c9e34182e15481`
- Primary source: Federal Reserve Board FOMC statement at the URL contained in the snapshot.
- Target: Korean, Blog ID `3321654108096579717`, `https://trend-ko.blogspot.com`.
- Trends context: original query `fed meeting`, observed in SG. Treat it only as an attention signal; it is not evidence for any article fact.

## Scheduled-task instructions

Read the snapshot and the two import schemas:

- `docs/schemas/woori-content-import-1.0.schema.json`
- `docs/schemas/woori-scheduled-content-import-1.0.schema.json`

Write at most one Korean reader-centered expert column explaining what the October 28, 2026 FOMC statement actually said and what can cautiously be inferred from its wording. The snapshot is immutable input. Preserve the distinction between the 2026-10-28 statement date and the 2026-10-29 KST collection time. Use only claims supported by the supplied official statement and its exact evidence spans. Do not invent forecasts, interviews, market reactions, numeric comparisons, or independent confirmation. Keep the article length proportionate to the 11 supplied fact spans. A single primary statement is suitable for explaining that statement, but the snapshot records zero independent sources.

The package is `evidence_collected_pending_human_review`, with `generation_ready=false`, `human_review_required=true`, and `publish_ready=false`. The source record says Board-authored text is public domain unless otherwise indicated, with attribution and exclusion of third-party material. Do not quote third-party content. Preserve that rights note. Do not claim a human semantic, independent-source, or rights review. If an essential claim cannot be matched to a supplied exact span, omit it or mark it `unverified`; do not expand the article with unsupported context.

Produce exactly one `woori-scheduled-content-import/1.0` envelope, or produce no file and report the specific blocker. Use:

- `task_type`: `trends_major_issue`
- `task_id`: `fed-statement-ko`
- `target_language_code`: `ko`
- `target_blog_id`: `3321654108096579717`
- `target_blog_url`: `https://trend-ko.blogspot.com`
- `source_region`: `US`
- `google_trends_based`: `true`
- `research_package_id`: the existing package ID above
- `generation_method`: `chatgpt_scheduled_export`
- `blogger_labels`: only labels accepted by the existing taxonomy; for `finance`/`ko` the current allowed suggestions are `이슈`, `금융`.

Use the real scheduled execution timestamp for `scheduled_origin.executed_at` and a unique occurrence label for `scheduled_origin.occurrence_id`; do not invent a platform execution ID or model identity. Use the source's recorded publication and observation times from the snapshot. Set rights to the conservative value required by the evidence; a filled field is not a completed rights approval. Do not add `publish_ready` or approval fields.

Write UTF-8 to `.local/gpt-scheduled-import/incoming/fed-statement-ko-<actual-run-time>.part`, parse the completed JSON, then atomically rename it on the same volume to `.local/gpt-scheduled-import/ready/fed-statement-ko-<actual-run-time>.ready.json`. Never overwrite an existing file or write directly to `ready`. Do not call the Import API, run scripts, create publication jobs, or call Blogger. Report only the actual final path and hash if the write succeeded. The existing local Research Worker performs idempotent Import and deterministic assessment. Human review and publication remain separate gates.

## Expected system behavior

The Research Worker's scheduled inbox poll validates the envelope, imports it idempotently, appends scheduled-origin/file provenance, creates an immutable import/content version, and runs the existing deterministic assessment. Import or `machine_passed=true` does not grant `auto_eligible`, `publish_ready`, a Blogger job, or Blogger write permission. The current Fed package's zero independent-source count and pending human semantic/rights review keep it out of automatic publication.
