# P5-CODEX-024 — Codex desktop Local Scheduled task setup

## Supported transfer path

OpenAI's official documentation supports Codex desktop Scheduled tasks in a local project directory or worktree. For this repository's fixed inbox, select the **local project** `C:\Users\achie\git\woori-blog-agent`, not a cloud-only task or separate worktree. Scheduled runs use the configured sandbox and approval behavior. Keep the computer powered on and the desktop app running while local files are needed. Web-only tasks cannot directly access this folder. A local metadata-file probe was successfully written by a Codex desktop Scheduled execution at 2026-10-29 15:51:06 KST; article JSON creation, automatic Import, and downstream review remain unverified.

Official references: [Scheduled tasks](https://learn.chatgpt.com/docs/automations), [ChatGPT desktop app for Windows](https://learn.chatgpt.com/docs/app/windows), and [ChatGPT Work local files](https://learn.chatgpt.com/docs/get-started-with-work).

Verification update (2026-10-29): the existing Codex desktop Local Scheduled task wrote `.local/gpt-scheduled-import/probe/scheduled-test.json` at 15:51:06 KST. Its 268-byte JSON contains only execution metadata; it is not an import envelope. There is still no scheduled manuscript `*.ready.json` or Import receipt. See the Research Package prompt in [P5-CODEX-037](P5-CODEX-037-fed-package-task.md) and the new task catalog in [P5-CODEX-038](P5-CODEX-038-scheduled-task-catalog.md).

This task only writes review-held import files. The local Research Worker polls `.local/gpt-scheduled-import/ready/` every 60 seconds and forwards files to the loopback Import API. Imports remain `awaiting_human_review`, `publish_ready=false`, and have no Blogger write path.

## Common output contract

Paste the relevant task-specific prompt below into a Codex desktop Scheduled task and select the local project above. For each run:

1. Check the available official material and market calendar. If the prior session is not confirmed, official data is unavailable, material is stale, or source rights/claim support are materially unclear, create no file and report the specific hold reason in the task result.
2. Write an independent expert column in the target language. Separate sourced facts from analysis. Do not invent prices, returns, forecasts, market moves, quotes, expertise, or source identities. Record actual observation time, publication date, period, units, and source URLs.
3. Read `docs/schemas/woori-content-import-1.0.schema.json` and `docs/schemas/woori-scheduled-content-import-1.0.schema.json`. Produce exactly one complete `woori-scheduled-content-import/1.0` JSON envelope for one eligible article, or no file. Include `item.generation_method="chatgpt_scheduled_export"`; `publish_ready` is not a permitted input field. Prefer official source records, but use a current, separately reviewed reputable media, industry-analysis, or public-data source when it supports the exact claims and its use conditions are documented. Link every material claim to an exact source span. A single source permits only a scope-limited, explicitly review-held draft. Uncertain rights remain `unknown` or `quotation_review_required`; unresolved facts remain `unverified`, and if those gaps affect the article's core claims, create no file.
4. Use the registered target mapping below. `task_id` is the stable task code in this prompt. `occurrence_id` must be unique for the scheduled occurrence (task code plus market/observation date and run time). These are self-reported labels, not verified ChatGPT task or execution IDs. Do not put a fabricated internal ChatGPT ID or model identity in the file.
5. Save UTF-8 JSON first to `.local/gpt-scheduled-import/incoming/<task-code>-<date>-<language>.part`. After the complete file is written and parsed as valid JSON, rename it on the same local volume to `.local/gpt-scheduled-import/ready/<task-code>-<date>-<language>.ready.json`. Never write directly to `ready`; never overwrite an existing file. If rename or local access is unavailable, return the JSON in the task result and clearly report that local delivery failed. Do not claim automatic delivery.
6. Do not call the Import API, execute scripts, publish to Blogger, or mark human review, independent verification, rights approval, `generation_ready`, or `publish_ready` complete. The local Worker performs import and mechanical assessment separately.

Registered Blogger targets:

| Language | Blog ID | URL |
|---|---:|---|
| Korean (`ko`) | `3321654108096579717` | `https://trend-ko.blogspot.com` |
| English (`en`) | `5240203250707821039` | `https://trend-journal-en.blogspot.com` |
| Japanese (`ja`) | `7562596540375659150` | `https://trend-ja.blogspot.com` |
| Simplified Chinese (`zh-CN`) | `1931836538202286191` | `https://trend-zh.blogspot.com` |

The inbox validates the existing `woori-content-import/1.0` item. For each claim, include evidence excerpt and source ID; excerpts should be the minimum needed for verification. Do not add undocumented fields. `research_package_id` may be set only to an existing package ID that was actually available to the task; otherwise use `null`. Scheduled authoring must not make remote requests outside the project's allowlisted source routes; if the required official evidence is not already available in a Research Package or local reviewed source snapshot, create no file.

## A. Korea market close

```text
Task code: market-close-kr
Run on Korean exchange sessions after the close, preferably 16:30 Asia/Seoul. Check the official KRX calendar and confirm the completed session date; do not infer a session on weekends or holidays. Prefer official KRX and issuer/regulator sources for prices, index and company facts. A separately reviewed reputable market-data source may be used only when the session, instrument, units, freshness, and reuse terms are independently checked; material price discrepancies mean no file. Write an independent Korean (`ko`) expert analysis for the registered Korean Blogger. Analyze only verified closing data and explain facts → meaning → implications, without investment recommendations or unsupported forecasts. Follow the Common output contract and create at most one envelope for the session.
```

## B. US market close

```text
Task code: market-close-us
Schedule after 16:00 America/New_York close with enough time for closing data to settle; respect US exchange holidays and DST using the America/New_York time zone. Confirm the latest completed session date. Prefer official exchange, SEC, Federal Reserve, BLS, BEA, Treasury, or issuer material as appropriate. Separately reviewed reputable market-data sources are acceptable only when the session, instrument, units, freshness, and reuse terms are checked; never mix intraday values with closing values. Write an independent English (`en`) analysis for the registered English Blogger. Clearly label market date, reporting period, units, and interpretation. Follow the Common output contract and create at most one envelope per completed session.
```

## C. Japan market close

```text
Task code: market-close-jp
Run after the Tokyo Stock Exchange session, preferably 16:30 Asia/Tokyo. Check the official JPX calendar and confirm the completed session date. Prefer official JPX, regulator, issuer, and government sources for close data and material facts. A separately reviewed reputable market-data source may be used only when the session, instrument, units, freshness, and reuse terms are independently checked; material price discrepancies mean no file. Write an independent Japanese (`ja`) analysis for the registered Japanese Blogger, with natural Japanese financial terminology. Separate verified facts from analysis and do not translate another language's article. Follow the Common output contract and create at most one envelope per completed session.
```

## D. China market close

```text
Task code: market-close-cn
Run after the Shanghai and Shenzhen sessions, preferably 16:00 Asia/Shanghai. Check the official SSE/SZSE calendar and verify the actual completed session. Prefer official exchange, CSRC, government, and issuer sources. A separately reviewed reputable market-data source may be used only when the session, instrument, units, freshness, and reuse terms are independently checked; material price discrepancies mean no file. Write an independent Simplified Chinese (`zh-CN`) analysis for the registered Simplified Chinese Blogger. Identify which market and session each figure describes; do not conflate mainland, Hong Kong, or Taiwan data. Follow the Common output contract and create at most one envelope per completed session.
```

## E. Friday finance research

```text
Task code: weekly-finance
Run Fridays at 17:30 Asia/Seoul. Review official material published since the prior weekly review, using Federal Reserve, SEC, BLS, BEA, Treasury, central-bank, statistical-agency, regulator, exchange, or company IR sources relevant to a specific reader question. Select zero or one article only when one current, well-supported issue has clear reader value. Choose one registered blog language based on the source region and reader relevance; author in that language from the beginning. If no topic meets the evidence and freshness standard, create no file and report why. Follow the Common output contract.
```

## F. Verified major Trends issue

```text
Task code: trends-major-issue
Run only after an operator has made the current Google Trends observation or issue group available in the selected local project. Preserve its region and exact observed query. Treat Trends as a signal of attention, never as fact, absolute search volume, or a popularity rank unless the source explicitly defines that metric. Confirm a current event using official primary sources where available; otherwise use an existing current, separately reviewed reputable alternative source. Assess relevance to registered-blog readers and record the source limitations. Reject duplicates, stale events, weak or rights-unclear evidence, and issues without a clear article angle. Write one independent column in the target blog's language; do not translate. A single-source article must stay narrowly attributed and review-held. If no usable evidence supports the core claims, create no file. Set `scheduled_origin.task_type` to `trends_major_issue`, use the provided observation date as `market_date` only if one is supplied, and follow the Common output contract.
```

## Operator setup and verification

1. In Codex desktop, create a new Scheduled task; do not edit or delete existing tasks. Select this repository as a local project and select the matching task-specific prompt.
2. Configure the desired recurrence in Asia/Seoul (US task timing may use America/New_York if offered). Review the saved timezone and cadence. Existing task schedules remain untouched.
3. Confirm the desktop app and computer will remain online/awake for the run. A local-only task cannot write when its computer is unavailable. A cloud-only task cannot access this folder.
4. Start the repository API on `127.0.0.1:8100` and the existing Research Worker from their owning terminals. The Worker must be running the new develop code. The Worker moves complete ready files to `processing`, imports and assesses them, then retains them under `processed`; invalid JSON is retained in `quarantine`, permanent API rejection in `rejected`, and transient API failures return to `ready`.
5. In Codex desktop Scheduled, inspect the run result; then check the local JSON filename and SHA-256 in the Dashboard. A file in `ready`/`processed` plus the Worker outcome audit demonstrates local receipt/import. Record task execution, file-writing probe, manuscript-envelope creation, and Import receipt as separate outcomes. A successful probe does not count as an article run.
6. If opening the local project, granting local folder access, choosing a local run mode, or selecting a schedule is unavailable in this account/workspace, stop at the documented setup step. Do not replace it with a web task, browser automation, manual download, session-cookie extraction, unofficial API, or headless Codex loop.
