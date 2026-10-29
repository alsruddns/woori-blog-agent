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
Do not browse arbitrary URLs, call external APIs, run project scripts, modify the database, call Blogger, create publishing jobs, alter approvals, change files outside this checkout, or run git commit/push. No paid API or provider fallback.

Choose at most one not-yet-authored Research Package whose sources, exact evidence spans, dates, rights notes, freshness, language, and target blog support the requested topic. A package awaiting human review may be used only to create an explicitly review-held draft when its supplied evidence is enough; never change its state or imply it is generation-ready. Keep fact, attributed position, and interpretation distinct. If the source route is absent, source text is unavailable, facts conflict, rights are unclear, source is stale, language quality cannot be met, or evidence is insufficient even for a review-held draft, create no file and report the exact reason. Do not use Google Trends as factual evidence. Do not translate another article to fill a slot.

Read docs/schemas/woori-content-import-1.0.schema.json and docs/schemas/woori-scheduled-content-import-1.0.schema.json. Produce one complete woori-scheduled-content-import/1.0 envelope or no file. Include the actual Research Package ID, exact source IDs and publication/observation dates, source excerpts and claim mappings, target language/blog, SEO fields, and truthful rights status. Use generation_method=chatgpt_scheduled_export. Never set publish_ready, auto_eligible, generation_ready, or human approval fields. The item is an untrusted draft; the importer and review gates decide separately.

Write UTF-8 to .local/gpt-scheduled-import/incoming/<unique-name>.part, parse it with the local schema, then atomically rename on the same volume to .local/gpt-scheduled-import/ready/<unique-name>.ready.json. Never overwrite or write directly into ready. If validation fails, leave no ready file. Do not hand-create execution IDs, model names, source facts, or rights approvals. Report the actual final file/hash only when the task wrote it.
```

## Proposed tasks

| # | Task code | Proposed schedule | Language/blog | Task-specific purpose |
|---:|---|---|---|---|
| 1 | `market-close-us` | Weekdays 17:30 `America/New_York` | en / `5240203250707821039` | Use only an existing package for the latest completed US session. Confirm exchange session date, closing values, units, source period, and official exchange/issuer/regulator evidence. If no completed-session package exists, no file. |
| 2 | `market-close-kr` | Weekdays 16:30 `Asia/Seoul` | ko / `3321654108096579717` | Use only an existing evidence package for the latest completed KRX session. `generation_ready=true` is not required for a review-held draft. Verify holiday/session date and official closing data and explain facts → meaning → implications without unsupported forecasts. |
| 3 | `market-close-jp` | Weekdays 16:30 `Asia/Tokyo` | ja / `7562596540375659150` | Use only an existing package for the latest completed JPX session. Verify local session date, units, and official source spans; write independently in Japanese. |
| 4 | `fed-sec-official` | Weekdays 20:00 `Asia/Seoul` | en / `5240203250707821039` | Select one new, unprocessed Fed/SEC package with official source spans. Preserve accession/release date, reporting period, units, and source limitations. Do not infer investment merit. |
| 5 | `crypto-issue` | Daily 09:00 `Asia/Seoul` | en / `5240203250707821039` | Use an existing package only if an approved official source route and fact spans already exist. Do not treat exchange prices, social posts, or Trends attention as official evidence. |
| 6 | `global-it-ai` | Weekdays 10:00 `Asia/Seoul` | en / `5240203250707821039` | Write one evidence-led analysis from an existing reviewed government, regulator, company, or research package. Distinguish announced, tested, and generally available product status. |
| 7 | `kpop-issue` | Weekdays 11:00 `Asia/Seoul` | ko / `3321654108096579717` | Use an existing rights-reviewed package with official artist/agency/organizer evidence. Avoid reproducing lyrics, images, press-copy, or unsupported rumors. |
| 8 | `kbeauty-issue` | Weekdays 12:00 `Asia/Seoul` | ko / `3321654108096579717` | Use an existing package with official regulatory, company, or public-data evidence. Do not make unverified health, efficacy, or sales claims. |
| 9 | `korea-tourism` | Weekdays 13:00 `Asia/Seoul` | ko / `3321654108096579717` | Use a current package with official Korea Tourism Organization, government, or destination source spans. Validate dates, opening status, access rules, and update time; otherwise no file. |
| 10 | `weekly-global-finance` | Fridays 17:30 `Asia/Seoul` | en / `5240203250707821039` | Select at most one new, current package with official central-bank, statistical-agency, treasury, regulator, exchange, or issuer evidence. Compare periods only when the package contains comparable facts. |
| 11 | `weekly-ai-research` | Fridays 16:00 `Asia/Seoul` | en / `5240203250707821039` | Select at most one new package with an accessible original research paper or official research release and documented use terms. Separate study findings from independent replication and real-world effect. |

## Registration and verification

Create each approved task in Codex desktop Scheduled, choose this local project, paste the common block plus the task row, and explicitly set the proposed timezone/cadence only after operator review. Verify each saved task in Scheduled. The first runs should be reviewed individually. Do not register all 11 merely to test the file probe. Count separately: registered task, actual scheduled execution, article envelope created, Import receipt, assessment, and Blogger publication.

The scheduled task must never call Blogger. Import produces review-held intake only; article assessment, human editorial/rights review, publication approval, Auto policy, and actual Blogger writes remain separate gates.
