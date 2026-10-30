# P5-CODEX-038 — Codex Local Scheduled task catalog

## Status

This is registration preparation, not proof that tasks were created. The Codex desktop Scheduled UI is the supported management surface; this repository has no task-registration API. On 2026-10-29 the local probe established that a Scheduled run could write a file in the project. It did not generate or import an article. No task from this catalog is registered by this change.

Before enabling recurrence, confirm the selected Codex plan/workspace has sufficient included usage and that additional credits or currency billing are disabled or explicitly acceptable. Local Scheduled tasks use Codex task execution, not the OpenAI API, but this repository cannot inspect account usage or credit settings. Keep the computer powered on and Codex desktop running. Use Local project mode for this checkout, not a web-only task or a detached worktree.

The times below are **proposed defaults** for operator review, not saved schedules. On market holidays or when no new approved Research Package exists, the task must produce no file. No task should force a daily article count.

## Common prompt for all 11 tasks

Paste this block before the task-specific purpose:

```text
You are a Codex desktop Scheduled task running in the selected local project.
Use only existing, current Research Packages and source snapshots in the project.
Do not browse arbitrary URLs, call external APIs, modify the database directly, call Blogger directly, create publishing jobs, alter approvals, change files outside this checkout, or run git commit/push. No paid API or provider fallback. The only permitted project HTTP call is the read-only duplicate preflight below, through the fixed same-origin Dashboard proxy; it records a bounded audit event but does not write manuscript, publication, approval, or Blogger data. The only other permitted project script is the explicitly named local envelope validator.

Before drafting, run the read-only duplicate preflight using the exact target language, country, registered Blogger ID, market/trade date when applicable, stable event group, and concise topic:

```powershell
.\.venv\Scripts\python.exe .\scripts\scheduled_duplicate_check.py --stage generation --language-code <ko|en|ja|zh-CN> --target-country <ISO-3166-1> --target-blog-id <registered-blog-id> [--trade-date YYYY-MM-DD for market task only] --event-group-id <stable-event-id> --topic <issue-title>
```

Omit `--trade-date` for non-market tasks. For article generation, pass `--stage generation`; the script calls only `http://127.0.0.1:3100/api/research/content-imports/duplicate-check`, sends the matching local Origin, and relies on the Dashboard proxy to add its server-held admin credential. Never read `.env` or call the API on port 8100 directly. The response is unaudited manuscript input: `local_status=already_published` means stop, `already_imported` means do not create a new original, and only local `not_found`/`failed_only` with `draft_import_allowed=true` allows drafting. The overall `status` may remain `unknown` while `remote_status=not_checked`; never call that `not_found` or verified uniqueness. The Publication Worker independently performs Blogger remote duplicate checks before publication and retries read failures with a bounded delay; do not publish while remote state is unknown. Never infer local absence from a folder scan.

Choose at most one not-yet-authored Research Package whose current reviewed sources, exact evidence spans, dates, rights notes, freshness, language, and target blog support the requested topic. Prefer official primary sources; a separately reviewed reputable media, industry-analysis, or public-data source is acceptable when it directly supports the claims and its reuse conditions are documented. A single-source package may support only a narrow, explicitly review-held draft. A package awaiting human review may be used for a review-held draft when its evidence is sufficient; never change its state or imply it is generation-ready. Keep fact, attributed position, and interpretation distinct. If no verifiable source supports the core claims, source text is unavailable, facts conflict, rights are unclear, the source is stale, language quality cannot be met, or evidence is insufficient even for a review-held draft, create no file and report the exact reason. Do not use Google Trends as factual evidence. Do not translate another article to fill a slot.

Read docs/schemas/woori-content-import-1.0.schema.json and docs/schemas/woori-scheduled-content-import-1.0.schema.json. Produce one complete woori-scheduled-content-import/1.0 envelope or no file. Include the actual Research Package ID, exact source IDs and publication/observation dates, source excerpts and claim mappings, target language/blog, SEO fields, and truthful rights status. Use generation_method=chatgpt_scheduled_export. Never set publish_ready, auto_eligible, generation_ready, or human approval fields. The item is an untrusted draft; the importer and review gates decide separately.

Write UTF-8 to .local/gpt-scheduled-import/incoming/<unique-name>.part, parse it with the local schema, then atomically rename on the same volume to .local/gpt-scheduled-import/ready/<unique-name>.ready.json. Never overwrite or write directly into ready. If validation fails, leave no ready file. Do not hand-create execution IDs, model names, source facts, or rights approvals. The `generation_method` must be `chatgpt_scheduled_export` because this is a real Scheduled task; do not copy this value to a manual Codex export. The item must use `relation=original`, `parent_content_id=null`, and a new UUID unless an existing accepted import is being retried exactly. Report the actual final file/hash only when the task wrote it.

Import identity and taxonomy rules (mandatory):
- Use relation=original and parent_content_id=null unless the parent is confirmed as a successfully imported PostgreSQL record. A quarantined/rejected/incoming/generated file is not an imported parent. A correction made before first successful import remains original and gets a new unique content_id. For an already accepted import, an exact retry reuses the same full envelope/content_id; a revision is allowed only when the parent exists in external_content_imports and has a native content-version mapping.
- occurrence_id identifies the scheduled occurrence, not a manuscript attempt: keep it for a correction of that same occurrence, and use a new value for a new scheduled run. Never submit a different manuscript under an occurrence already accepted/audited; exact duplicate delivery must reuse the same file/envelope.
- Copy blogger_labels exactly from services/api/woori/editorial_taxonomy.py using suggested_labels(category, language_code, google_trends_based=...). Do not invent labels. Example: stocks/ko permits ["주식"], or ["이슈", "주식"] for Trends-based content.
- After writing the complete .part file, run `.venv\\Scripts\\python.exe scripts\\validate-scheduled-import.py .local\\gpt-scheduled-import\\incoming\\<filename>.part`. This read-only validator invokes the same ScheduledImportEnvelope Pydantic contract as the Worker; it does not access the API or DB. Rename atomically to ready/*.ready.json only when it reports valid=true. This supplements schema parsing with label and cross-field checks.
```

## Proposed tasks

| # | Task code | Proposed schedule | Language/blog | Task-specific purpose |
|---:|---|---|---|---|
| 1 | `market-close-us` | Weekdays 17:30 `America/New_York` | en / `5240203250707821039` | Use only an existing package for the latest completed US session. Confirm exchange session date, closing values, units, and source period. Prefer reviewed primary-source evidence; a secondary market-data source requires separate review of session, instrument, freshness, reuse terms, and material discrepancies. |
| 2 | `market-close-kr` | Weekdays 16:30 `Asia/Seoul` | ko / `3321654108096579717` | Use only an existing evidence package for the latest completed KRX session. `generation_ready=true` is not required for a review-held draft. Verify holiday/session date and closing data from reviewed sources, preferring KRX primary material; a secondary market-data source needs equivalent date, unit, freshness, and rights checks. Do not infer figures or forecasts. |
| 3 | `market-close-jp` | Weekdays 16:30 `Asia/Tokyo` | ja / `7562596540375659150` | Use only an existing package for the latest completed JPX session. Prefer JPX primary data; a reviewed secondary source may be used only when session date, units, freshness, rights, and any price discrepancy are checked. Write independently in Japanese. |
| 4 | `fed-sec-official` | Weekdays 20:00 `Asia/Seoul` | en / `5240203250707821039` | Select one new, unprocessed Fed/SEC package, preferably with official primary-source spans. Preserve accession/release date, reporting period, units, and source limitations. Do not infer investment merit. |
| 5 | `crypto-issue` | Daily 09:00 `Asia/Seoul` | en / `5240203250707821039` | Use an existing current, reviewed package with claim-linked evidence and documented rights. A source being non-official is not by itself a rejection; do not treat exchange prices, social posts, or Trends attention as factual evidence. |
| 6 | `global-it-ai` | Weekdays 10:00 `Asia/Seoul` | en / `5240203250707821039` | Write one evidence-led analysis from an existing reviewed government, regulator, company, research, or reputable specialist-media package. Distinguish announced, tested, and generally available product status. |
| 7 | `kpop-issue` | Weekdays 11:00 `Asia/Seoul` | ko / `3321654108096579717` | Use an existing rights-reviewed package with reliable, claim-linked evidence from official or reputable reporting. Avoid reproducing lyrics, images, press-copy, or unsupported rumors. |
| 8 | `kbeauty-issue` | Weekdays 12:00 `Asia/Seoul` | ko / `3321654108096579717` | Use an existing package with claim-linked regulatory, company, or separately reviewed specialist evidence. Do not make unverified health, efficacy, or sales claims. |
| 9 | `korea-tourism` | Weekdays 13:00 `Asia/Seoul` | ko / `3321654108096579717` | Use a current package with reviewed destination evidence. Prefer official Korea Tourism Organization, government, or venue sources for dates, opening status, and access rules; if these cannot be verified, omit those claims or create no file. |
| 10 | `weekly-global-finance` | Fridays 17:30 `Asia/Seoul` | en / `5240203250707821039` | Select at most one new, current package with claim-linked reviewed evidence, preferring central-bank, statistical-agency, treasury, regulator, exchange, or issuer sources. Compare periods only when the package contains comparable facts. High-risk financial claims need stricter corroboration and remain review-held. |
| 11 | `weekly-ai-research` | Fridays 16:00 `Asia/Seoul` | en / `5240203250707821039` | Select at most one new package with accessible reviewed research evidence and documented use terms. Prefer the original paper or research release; separate study findings from independent replication and real-world effect. |

## Registration and verification

Create each approved task in Codex desktop Scheduled, choose this local project, paste the common block plus the task row, and explicitly set the proposed timezone/cadence only after operator review. Verify each saved task in Scheduled. The first runs should be reviewed individually. Do not register all 11 merely to test the file probe. Count separately: registered task, actual scheduled execution, article envelope created, Import receipt, assessment, and Blogger publication.

The scheduled task must never call Blogger. Import produces review-held intake only; article assessment, human editorial/rights review, publication approval, Auto policy, and actual Blogger writes remain separate gates.
