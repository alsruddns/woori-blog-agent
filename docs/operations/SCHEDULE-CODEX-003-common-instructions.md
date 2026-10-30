# Common instructions for existing Codex Scheduled article tasks

Append this block to each existing Scheduled task while preserving its current
task name, cadence, timezone, model, subject, language, target blog, and other
task-specific instructions. This file is a paste-ready template; it does not
modify the 15 task definitions stored in the Codex desktop Scheduled UI.

```text
You are running as an actual Codex desktop Scheduled task in this selected local
project. Keep this task's existing subject, schedule, timezone, model, target
language, and registered Blogger blog unchanged. This instruction applies only
to the current scheduled occurrence.

Before researching or writing, identify the topic/event, target country, target
language, registered target Blogger ID, and (only for a market-close task) the
actual completed market session date. Use an event_group_id that remains stable
for the same real-world event. Do not treat quarantine/rejected files as
successful imports or posts.

Run the read-only duplicate preflight using this project command, substituting
the real values from this task and the current occurrence:

.\.venv\Scripts\python.exe .\scripts\scheduled_duplicate_check.py --language-code <ko|en|ja|zh-CN> --target-country <ISO-3166-1-country-code> --target-blog-id <registered-blog-id> [--trade-date YYYY-MM-DD] --event-group-id "<stable-event-id>" --topic "<concise-real-topic>"

Use --trade-date only for a market-close task. The command calls only the fixed
same-origin Dashboard duplicate-check proxy on 127.0.0.1:3100. Do not call the
API on port 8100, connect directly to PostgreSQL, read .env/credentials, or call
Blogger. Interpret the returned status exactly:
- already_published: stop; do not write a new article.
- already_imported: stop creating a new article; report the existing import for
  its existing downstream handling.
- failed_only: a new original is allowed only when blogger_read_complete is
  true. Preserve every failed file and use a new content UUID.
- not_found: a new original is allowed only when blogger_read_complete is true.
- unknown, missing fields, command error, incomplete Blogger read, or any
  ambiguity: stop and create no ready file.

Research current, topic-relevant material using the tools available to this
scheduled task and the project's reviewed outbound/provider rules. Prefer
primary sources, but a directly relevant reputable secondary source is
acceptable when its terms and reuse conditions are actually established. Record
the real source URL, title, publisher, publication date, observation time,
evidence excerpt, rights/use notes, and claim-to-source mapping. Never invent
facts, source IDs, quotes, measurements, rights clearance, or a successful
verification. If the evidence does not support a useful original article, stop
without a file. Paraphrase independently; do not reproduce long source passages,
lyrics, images, or tables. Separate sourced fact, attributed position, and
analysis. Do not write financial, health, legal, political, or other material
whose key claims cannot be checked against the available evidence.

Write one complete, reader-facing article in this task's existing language.
Use the existing task's real subject and audience. Do not translate another
article as a substitute. Do not pad to meet a word count. Keep only claims that
the recorded sources support. Use relation=original, parent_content_id=null,
and a new UUID unless this is an exact idempotent retry of an already accepted
envelope. Keep generation_method=chatgpt_scheduled_export because and only
because this file is produced by the real Scheduled execution. This provenance
is self-reported and does not itself grant approval or publish eligibility.

Occurrence identity: if the Scheduled execution exposes a scheduler-issued
occurrence ID, use it unchanged as both `occurrence_id` and
`scheduler_occurrence_id`, and set `occurrence_id_source` to
`scheduler_issued`. If it does not, read this task's actual Automation ID and
configured slot from the Codex Local automation definition. Do not use the
current wall-clock time as the slot. Verify and derive the ID with:

```powershell
.\.venv\Scripts\python.exe .\scripts\derive-scheduled-occurrence-id.py `
  --automation-id <actual-automation-id> `
  --scheduled-slot <configured-slot-ISO-8601-with-09-00>
```

Copy the returned `occurrence_id`, `occurrence_id_source`, `automation_id`,
`scheduled_slot`, and `scheduler_occurrence_id` fields unchanged into
`scheduled_origin`. For a derived slot, the scheduler ID must be null and the
source must be `project_derived_kst_slot`. The helper checks the active task's
project checkout, KST timezone, and configured RRULE slot. If it cannot verify
the configuration or slot, stop without creating an envelope. `executed_at`
remains the actual execution timestamp; it is not the scheduled slot. A retry
of the same occurrence reuses the same ID, while another date/time slot derives
a different ID.

Create exactly one envelope conforming to
docs/schemas/woori-scheduled-content-import-1.0.schema.json, with item
conforming unchanged to woori-content-import/1.0. Include the actual task code
as task_id (do not invent a Codex internal task ID), a unique occurrence_id for
this run using the occurrence procedure above, correct timezone-bearing executed_at and source_as_of timestamps,
actual target language/blog ID/canonical URL, source_ids, sources, claims,
fact_checked_at, SEO metadata, and only labels returned by the project's
editorial_taxonomy.suggested_labels(category, language_code,
google_trends_based=...). Never set a review result, publish_ready,
generation_ready, auto_eligible, rights approval, or human approval in the file.

Use scheduled_origin.task_type as follows: market_close_kr, market_close_jp,
market_close_cn, or market_close_us only for that exact market-close report;
weekly_finance for the existing weekly finance task; trends_major_issue only
when the researched issue genuinely originated from an identified Google
Trends observation and `item.google_trends_based` is true; otherwise use
scheduled_article. A topic that is often searched, or a prompt that mentions
trends as a secondary lead, is not sufficient. Source-led policy, technology,
finance, politics, tourism, culture, or product articles use
`scheduled_article`. Keep `item.google_trends_based` false for those articles.
Market-close tasks must include the actual market_date and
the language fixed by the schema. Do not relabel another topic as a Trends
issue to pass validation.

Write UTF-8 JSON first to
.local/gpt-scheduled-import/incoming/<unique-name>.part. Parse the JSON and run
the shared Pydantic validator, which is the same contract used by Import Worker:

.\.venv\Scripts\python.exe .\scripts\validate-scheduled-import.py ".local\gpt-scheduled-import\incoming\<unique-name>.part"

Only if it returns valid=true, atomically rename the complete file on the same
volume into
.local/gpt-scheduled-import/ready/<unique-name>.ready.json. The Worker polls
ready, not incoming. Never write directly into ready, overwrite a file, or leave
a failed/partial document with a .ready.json extension. On schema or factual
validation failure, do not place anything in ready; preserve the diagnostic
file under the existing failed/rejected handling and report the safe reason.

Do not modify DB rows, approvals, Auto policy, worker settings, existing task
definitions, or files outside this project. Do not create a Publishing Job or
call Blogger. The Import Worker, quality/review gates, and Publication Worker
own downstream processing. Report the duplicate status, source/evidence
coverage, validator result, final ready path and SHA-256 only when actually
created, and whether the run was genuinely scheduled or manually invoked.
```

## Contract alignment

`scheduled_article` is the generic scheduled task type for existing topics that
are neither market-close, weekly-finance, nor genuinely Trends-originated. It
does not change the subject or schedule and does not imply source or publication
approval. The envelope remains `woori-scheduled-content-import/1.0`; the shared
item contract remains `woori-content-import/1.0`.

The Worker intake contract is `.part` in `incoming/`, validation, then an atomic
move to `ready/*.ready.json`. A file named `incoming/*.ready.json` is not the
Worker's ready queue and must not be used as a substitute.
