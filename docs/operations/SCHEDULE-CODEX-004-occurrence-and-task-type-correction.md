# SCHEDULE-CODEX-004 — occurrence identity and scheduled article taxonomy

This instruction corrects the common export contract for the currently saved
Codex Desktop Local tasks. It does not edit Automation definitions, prompts,
schedules, models, project bindings, or Blogger targets. Apply the task-type
correction to those prompts through a separately authorized SCHEDULE-CODEX
change, then verify the saved prompt in Codex Desktop.

## Occurrence identity

Codex Desktop prompts currently do not receive a documented scheduler-issued
occurrence ID. When the execution context supplies one, preserve it exactly as
`occurrence_id`, set `occurrence_id_source=scheduler_issued`, and copy it to
`scheduler_occurrence_id`. Never infer or manufacture a provider-issued ID.

If no provider ID is supplied, use the actual active Automation ID and the
configured occurrence slot in `Asia/Seoul`. The slot must come from the saved
Automation RRULE, not the local clock or a guessed execution time. For example,
the crypto task `automation-3` is configured for daily 10:30 KST; the slot for
2026-10-30 is `2026-10-30T10:30:00+09:00` and the project-derived identity is
`codex-slot:automation-3:20261030T1030KST`.

Verify the active Automation ID, project checkout and configured slot before
using a derived identity:

```powershell
.\.venv\Scripts\python.exe .\scripts\derive-scheduled-occurrence-id.py `
  --automation-id automation-3 `
  --scheduled-slot 2026-10-30T10:30:00+09:00
```

Copy all returned occurrence metadata into `scheduled_origin`. For derived
identities, `scheduler_occurrence_id` is null and
`occurrence_id_source=project_derived_kst_slot`. Keep the actual execution
timestamp in `executed_at`; it is separate from the scheduled slot. A retry of
the same slot reuses the exact ID and byte-identical envelope. A different
date, time slot, or Automation ID yields a different identity. If the active
Automation, project binding, timezone, schedule slot, or actual run context
cannot be established, stop without exporting. This project-derived key is an
idempotency key, not proof that the scheduler itself attested to a run.

## Correct task-type taxonomy

Use `trends_major_issue` only when the article was actually selected from an
identified Google Trends observation and `item.google_trends_based=true`.
Web-researched topics are `scheduled_article`, even if they are popular or
trend-like. Preserve the task's subject, language, target blog, model and
schedule.

| Automation ID | Task code | Current task | Correct `task_type` |
| --- | --- | --- | --- |
| `ai` | `weekly-ai-research` | Weekly AI research | `scheduled_article` |
| `automation` | `market-close-kr` | Korea market close | `market_close_kr` |
| `automation-10` | `politics-cn` | China politics and policy | `scheduled_article` |
| `automation-2` | `market-close-jp` | Japan market close | `market_close_jp` |
| `automation-3` | `crypto-issue` | Crypto policy and market issue | `scheduled_article` |
| `automation-4` | `korea-tourism` | Korea tourism | `scheduled_article` |
| `automation-5` | `weekly-global-finance` | Weekly global finance | `weekly_finance` |
| `automation-6` | `market-close-us` | US market close | `market_close_us` |
| `automation-7` | `politics-us` | US politics and policy | `scheduled_article` |
| `automation-8` | `politics-kr` | Korea politics and policy | `scheduled_article` |
| `automation-9` | `politics-jp` | Japan politics and policy | `scheduled_article` |
| `fed-sec` | `fed-sec-official` | Fed/SEC official developments | `scheduled_article` |
| `it-ai` | `global-it-ai` | Global IT and AI | `scheduled_article` |
| `k-beauty` | `kbeauty-issue` | K-Beauty issue | `scheduled_article` |
| `k-pop` | `kpop-issue` | K-Pop issue | `scheduled_article` |

The saved definitions were inspected read-only for this correction. Ten tasks
in addition to crypto currently use `trends_major_issue` in their prompts even
though their work is web/source-led. Correct those prompt fields using the
table when updating the shared task instructions. Do not classify these
existing prompts as corrected until their saved Codex definitions are actually
updated and re-read.

## Handoff

Use the existing `woori-scheduled-content-import/1.0` envelope and the shared
Pydantic validator. New articles remain `relation=original` with a fresh UUID
and null parent. Perform read-only duplicate preflight first; unknown, already
imported, or already published results stop new creation. Write only to a
unique `incoming/*.part`, validate, and atomically move to `ready/*.ready.json`.
The ready file is a handoff only; report Research Worker import and later
publishing outcomes only after observing their actual receipts/status. Do not
call Blogger or fabricate any approval or scheduler identity.
