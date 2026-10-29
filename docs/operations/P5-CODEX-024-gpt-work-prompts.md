# P5-CODEX-024 — ChatGPT Work scheduled task setup

## Supported transfer path

OpenAI's current official documentation describes scheduled tasks in the ChatGPT desktop app working in a local project directory or worktree. For this repository's fixed inbox, select the **local project** `C:\Users\achie\git\woori-blog-agent`, not a cloud-only task or separate worktree. The computer must remain powered on, online, signed in, and the ChatGPT desktop app must remain running while local files are needed. Web-only scheduled tasks cannot directly access a local folder. The documented capability does not verify this account's project permissions or prove a scheduled run wrote a file; task creation and the first unattended run remain operator actions.

Official references: [Scheduled tasks](https://learn.chatgpt.com/docs/automations), [ChatGPT desktop app for Windows](https://learn.chatgpt.com/docs/app/windows), and [ChatGPT Work local files](https://learn.chatgpt.com/docs/get-started-with-work).

This task only writes review-held import files. The local Research Worker polls `.local/gpt-scheduled-import/ready/` every 60 seconds and forwards files to the loopback Import API. Imports remain `awaiting_human_review`, `publish_ready=false`, and have no Blogger write path.

## Common output contract

Paste the relevant task-specific prompt below into a scheduled ChatGPT Work task and select the local project above. For each run:

1. Check the available official material and market calendar. If the prior session is not confirmed, official data is unavailable, material is stale, or source rights/claim support are materially unclear, create no file and report the specific hold reason in the task result.
2. Write an independent expert column in the target language. Separate sourced facts from analysis. Do not invent prices, returns, forecasts, market moves, quotes, expertise, or source identities. Record actual observation time, publication date, period, units, and source URLs.
3. Read `docs/schemas/woori-content-import-1.0.schema.json` and `docs/schemas/woori-scheduled-content-import-1.0.schema.json`. Produce exactly one complete `woori-scheduled-content-import/1.0` JSON envelope for one eligible article, or no file. Include `item.generation_method="chatgpt_scheduled_export"`; `publish_ready` is not a permitted input field. Use one or more official source records and claim-to-source links. Uncertain source rights must remain `unknown` or `quotation_review_required`; unresolved facts remain `unverified`.
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

The inbox validates the existing `woori-content-import/1.0` item. For each claim, include evidence excerpt and source ID; excerpts should be the minimum needed for verification. Do not add undocumented fields. `research_package_id` may be set only to an existing package ID that was actually available to the task; otherwise use `null`.

## A. Korea market close

```text
Task code: market-close-kr
Run on Korean exchange sessions after the close, preferably 16:30 Asia/Seoul. Check the official KRX calendar and confirm the completed session date; do not infer a session on weekends or holidays. Use official KRX and issuer/regulator sources for prices, index and company facts. Write an independent Korean (`ko`) expert analysis for the registered Korean Blogger. Analyze only verified closing data and explain facts → meaning → implications, without investment recommendations or unsupported forecasts. Follow the Common output contract and create at most one envelope for the session.
```

## B. US market close

```text
Task code: market-close-us
Schedule after 16:00 America/New_York close with enough time for official closing data to settle; respect US exchange holidays and DST using the America/New_York time zone. Confirm the latest completed session date. Use official exchange, SEC, Federal Reserve, BLS, BEA, Treasury, or issuer material as appropriate; never mix intraday values with closing values. Write an independent English (`en`) analysis for the registered English Blogger. Clearly label market date, reporting period, units, and interpretation. Follow the Common output contract and create at most one envelope per completed session.
```

## C. Japan market close

```text
Task code: market-close-jp
Run after the Tokyo Stock Exchange session, preferably 16:30 Asia/Tokyo. Check the official JPX calendar and confirm the completed session date. Use official JPX, regulator, issuer, and government sources for close data and material facts. Write an independent Japanese (`ja`) analysis for the registered Japanese Blogger, with natural Japanese financial terminology. Separate verified facts from analysis and do not translate another language's article. Follow the Common output contract and create at most one envelope per completed session.
```

## D. China market close

```text
Task code: market-close-cn
Run after the Shanghai and Shenzhen sessions, preferably 16:00 Asia/Shanghai. Check the official SSE/SZSE calendar and verify the actual completed session. Use official exchange, CSRC, government, and issuer sources. Write an independent Simplified Chinese (`zh-CN`) analysis for the registered Simplified Chinese Blogger. Identify which market and session each figure describes; do not conflate mainland, Hong Kong, or Taiwan data. Follow the Common output contract and create at most one envelope per completed session.
```

## E. Friday finance research

```text
Task code: weekly-finance
Run Fridays at 17:30 Asia/Seoul. Review official material published since the prior weekly review, using Federal Reserve, SEC, BLS, BEA, Treasury, central-bank, statistical-agency, regulator, exchange, or company IR sources relevant to a specific reader question. Select zero or one article only when one current, well-supported issue has clear reader value. Choose one registered blog language based on the source region and reader relevance; author in that language from the beginning. If no topic meets the evidence and freshness standard, create no file and report why. Follow the Common output contract.
```

## F. Verified major Trends issue

```text
Task code: trends-major-issue
Run only after an operator has made the current Google Trends observation or issue group available in the selected local project. Preserve its region and exact observed query. Treat Trends as a signal of attention, never as fact, absolute search volume, or a popularity rank unless the source explicitly defines that metric. Confirm one actual current event with primary official sources and assess whether it is relevant to a registered blog's readers. Reject duplicates, stale events, weak evidence, or issues without a clear article angle. Write one independent column in the target blog's language; do not translate. If no issue qualifies, create no file. Set `scheduled_origin.task_type` to `trends_major_issue`, use the provided observation date as `market_date` only if one is supplied, and follow the Common output contract.
```

## Operator setup and verification

1. In ChatGPT desktop, create a new scheduled Work task; do not edit or delete existing tasks. Select this repository as a local project and select the matching task-specific prompt.
2. Configure the desired recurrence in Asia/Seoul (US task timing may use America/New_York if offered). Review the saved timezone and cadence. Existing task schedules remain untouched.
3. Confirm the desktop app and computer will remain online/awake for the run. A local-only task cannot write when its computer is unavailable. A cloud-only task cannot access this folder.
4. Start the repository API on `127.0.0.1:8100` and the existing Research Worker from their owning terminals. The Worker must be running the new develop code. The Worker moves complete ready files to `processing`, imports and assesses them, then retains them under `processed`; invalid JSON is retained in `quarantine`, permanent API rejection in `rejected`, and transient API failures return to `ready`.
5. In ChatGPT Scheduled, inspect the run result; then check the local JSON filename and SHA-256 in the Dashboard. A file in `ready`/`processed` plus the Worker outcome audit demonstrates local receipt/import, while the task's own ID and self-reported envelope do not cryptographically prove a specific scheduled execution. The current implementation reports verified GPT task-run count as zero unless an independently verifiable execution record becomes available.
6. If opening the local project, granting local folder access, choosing a local run mode, or selecting a schedule is unavailable in this account/workspace, stop at the documented setup step. Do not replace it with a web task, browser automation, manual download, session-cookie extraction, unofficial API, or headless Codex loop.
