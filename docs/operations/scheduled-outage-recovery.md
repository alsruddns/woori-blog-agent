# P5-CODEX-102: Scheduled manuscript outage contract

This shared contract supersedes earlier instructions that stop research solely
because the local duplicate lookup is unavailable. It does not grant Import or
publication permission and does not change Automation ID, schedule, target,
language, research standards, taxonomy, run-mode resolver, or occurrence identity.

For an eligible current run, keep policy inspection concise and spend the turn on
the actual research and file handoff. A scheduled resolver result with
`automation_policy.allowed=true` is the required pre-research policy check; run
the existing policy recheck once immediately before writing. Do not stop because
the overall duplicate result is `unknown` when local status is definitely clear,
the draft flag is true and remote status is only `not_checked`.

1. Resolve the actual invocation with `scripts/resolve-codex-automation-run.py`.
   Preserve its actual scheduled/manual classification and confirmed KST slot.
   For a scheduled invocation up to five minutes early, the resolver records
   `waiting_for_slot` and performs one bounded wait until that exact slot. The
   configured slot remains the occurrence basis. More than five minutes early,
   an interrupted wait, or execution more than five minutes late ends as
   `deferred`; retry only on the same verified registered slot. A project-derived
   occurrence is not a scheduler-issued ID. Never guess one.
2. Use the existing `scheduled_duplicate_check.py --stage generation` with the
   task's exact identifiers. It validates the current Desktop session and
   configured Automation ID, records `duplicate_check_running`, then records a
   terminal `duplicate_check_completed` result (or `deferred` if slot handling
   or the progress store fails). Do not separately leave a
   `duplicate_check_running` event before invoking this command. This command tries the
   Dashboard proxy first, then a fixed trusted service broker: authenticated
   loopback API, the identical repository preflight, then preserved presence
   indexes. Scheduled model code must not read .env, tokens, database credentials
   or execute SQL/API calls itself. Only this fixed broker may internally use
   existing service credentials; it exposes no URL, SQL or publication option.
3. Existing matches still block a new original. A new article may proceed only
   when generation preflight explicitly returns `local_status=not_found` or
   `failed_only` AND `draft_import_allowed=true`. The overall result may remain
   `unknown` and `remote_status=not_checked`; preserve both values. Any local
   `unknown`, missing eligibility flag, confirmed match, ambiguous identity, or
   active duplicate run blocks research and writing. Remote uniqueness is not
   established here; the normal publication-time check remains mandatory.
   Never use a publication-stage check while drafting, call Blogger, create a
   Publishing Job, or change Google/Auto/emergency-stop settings.
4. Do not create a new pending manuscript when preflight is unknown or
   unavailable. The historical pending saver is only for reconciling already
   existing pending artifacts under its authenticated recovery flow; it is not
   an alternate path for a new article. Missing sources, invalid invocation
   identity, an existing pending file or a confirmed duplicate are not
   permission to manufacture a second manuscript.
5. Record actual progress (`researching`, `writing`) with the shared progress
   helper. On a real usage limit record `usage_limit_waiting`; never invent token
   balances/reset times or switch providers. Preserve complete existing files.
6. For an eligible new article, write a complete UTF-8 envelope to a unique
   `.local/gpt-scheduled-import/incoming/<name>.part`. Validate with
   `scripts/validate-scheduled-import.py`; it uses the importer's Pydantic union
   and accepts both `woori-scheduled-content-import/1.0` and
   `woori-manual-automation-content-import/1.0`. The latter requires
   `generation_method=manual_codex_import` and the exact resolver-returned
   `manual_origin`; never add a scheduled slot to Run now. After preserving the
   exact generation preflight JSON in a local temporary file, use
   `scripts/handoff-automation-manuscript.py <incoming.part> --preflight-json
   <preflight.json>`. It revalidates the exact current Desktop invocation,
   envelope and eligible local duplicate result, then exclusively publishes the
   file into `ready/` without overwrite. It does not call an API or Blogger.
   Manual Run now receives no scheduled Auto authority from this handoff.
   For `--stage generation`, retain the complete preflight JSON. Its
   `automation_execution.invocation` and `automation_execution.contract` fields
   bind the duplicate result to the same resolved turn and select the exact
   scheduled or Run now envelope. If `contract` is null or has an error, stop;
   do not infer a contract from prompt text. The Import Worker writes an
   immutable minimal receipt under `import_receipts/` only after API Import,
   origin audit, and assessment have succeeded.
7. Research snapshot, article file, schema validation, ready handoff and Research
   Import are separate outcomes. Save an actual evidence-backed snapshot through
   `scripts/write-research-snapshot.py` before writing the envelope. If the
   snapshot or article cannot be saved and re-read, do not report that stage as
   complete. Never replace or delete an existing file or allocate a fresh
   occurrence for a retry. The ready handoff is local-only and exclusive; a
   Research Worker receipt is required before claiming Import success. The helper
   also preserves the resolver's actual Desktop session identity. Recovery
   re-reads that session's trigger and matches its scheduled occurrence or
   manual run. A configured RRULE alone is insufficient. Missing context is
   review-held; a historical session cannot relabel a newly written draft as its
   scheduled execution (execution time must remain within 6 hours of that start).
   Desktop may append multiple turns to one session transcript. Resolve the
   latest unfinished `task_started` turn by its matching turn ID, accepted
   scheduler trigger (`automation_cron_scheduled` or the existing explicit
   `automation_cron_run_now`), and the Automation ID prompt belonging to that
   turn. Do not require the entire transcript to contain exactly one historical
   start event, and never fall back to a completed or older turn. Multiple live
   starts, mismatched turn IDs, a composer/user trigger, or a prompt that cannot
   be associated with the selected start remains blocked.
8. The Research Worker checks pending files on its normal 60-second intake poll.
   Recovery authenticates to the existing API and rechecks configured occurrence,
   prior occurrence Import, event/title/content duplicates, format, safe HTML and
   generated/source freshness (24-hour conservative initial ceiling). Unknown
   duplicate status stays import_pending. Stale/future/unsafe manuscripts require
   fresh research or human review; they are not auto-imported or silently rewritten.
   The original pending file remains immutable; a separate immutable receipt links
   Import and native Content Version. Import, scheduled/manual origin and recovery
   audit commit atomically. Interrupted retries reconcile the exact same identity.
9. Progress is a self-reported operational state, not proof of research, source
   verification or editorial approval. Offline progress is synchronized into
   append-only PostgreSQL audit events after recovery. Import ends in human review;
   no Publishing Job, Blogger Draft, Publish, Update, approval or Auto activation
   follows from this workflow.

10. Automation-local memory is optional on a task's first run. Resolve
    `CODEX_HOME` using the Desktop environment; when it is unset, use that
    account's standard `~/.codex` location. The memory path is exactly
    `automations/<verified-automation-id>/memory.md`. If it is absent, create
    only that file as a fresh, task-specific baseline using a same-directory
    temporary file and an exclusive atomic rename. Never copy another
    automation's memory, replace an existing file, or treat missing memory as
    evidence that execution mode is invalid.
11. Keep the resolver invocation separate from memory and long-document reads.
    The resolver's scheduled slot gate may intentionally wait for as long as
    five minutes when Desktop starts early. It emits flushed phase diagnostics
    to stderr and the final JSON only after the wait. If the command tool returns
    a process/session ID while still running, retain that ID and continue polling
    the same process until its final result. Do not discard the ID, start a
    second resolver, or interpret an intermediate `waiting_for_slot` record as
    a terminal failure. If the process owner or final result cannot be
    established, record `BLOCKED` with the exact command, working directory,
    PID/session ID when available, elapsed time, exit status, and sanitized
    stdout/stderr; do not research or write an article.
    If the current session record has not appended its start event or matching
    Automation ID prompt yet, the resolver may reread that same transcript a
    bounded number of times (currently four reads with 150 ms spacing). It does
    not start another resolver or wait indefinitely. Exhaustion returns a
    specific blocked reason; it does not infer scheduled/manual mode.
12. Before retrying a slot, inspect its actual session, progress, receipt,
    incoming, ready, processing, processed, and pending artifacts. A live
    matching process or unresolved process/session ID blocks another attempt.
    Never remove a lock or progress artifact without confirming its owner is no
    longer running and checking the exact occurrence for duplicates. A later
    slot has a different occurrence and must not inherit the earlier slot's
    failure state. The exclusive execution receipt is keyed by the exact
    occurrence: an existing receipt from another session blocks a second run;
    preserve it as the idempotency record.

Historical failed slots are not current scheduled invocations. A development
session must not impersonate a Desktop cron or Run now trigger. Preserve failure
records; investigate/reconcile old artifacts first and record a distinct manual
recovery only with a supported actual invocation, never a fabricated provider ID.
