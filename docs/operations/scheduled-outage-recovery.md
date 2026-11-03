# P5-CODEX-102: Scheduled manuscript outage contract

This shared contract supersedes earlier instructions that stop research solely
because the local duplicate lookup is unavailable. It does not grant Import or
publication permission and does not change Automation ID, schedule, target,
language, research standards, taxonomy, run-mode resolver, or occurrence identity.

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
3. Existing matches still block a new original. A successful local check permits
   the established incoming -> validation -> exclusive atomic ready handoff.
   Never use a publication-stage check while drafting, call Blogger, create a
   Publishing Job, or change Google/Auto/emergency-stop settings.
4. If the result explicitly says `research_allowed=true`,
   `local_save_allowed=true` and `import_status=pending`, continue source research
   and writing even if the command exits 3. Preserve `local_status=unknown` and
   `draft_import_allowed=false`; never rewrite them to clear. Use verified,
   accessible evidence, rights notes and source/claim mapping exactly as usual.
   Missing sources, invalid invocation identity, an existing pending file or a
   confirmed duplicate are not permission to manufacture a second manuscript.
5. Record actual progress (`researching`, `writing`) with the shared progress
   helper. On a real usage limit record `usage_limit_waiting`; never invent token
   balances/reset times or switch providers. Preserve complete existing files.
6. For an outage manuscript write a complete UTF-8 envelope to a unique
   `.local/gpt-scheduled-import/incoming/<name>.part`. Validate with
   `scripts/validate-scheduled-import.py`. Keep the truthful duplicate/occurrence
   metadata, original evidence and actual execution time. Do not move it to ready.
   Run `.venv/Scripts/python.exe scripts/save-pending-manuscript.py <incoming.part>`.
   Manual Run now envelopes additionally require `--target-blog-id <actual-id>`;
   they retain manual_codex_import and never receive scheduled provenance.
7. Saving is local-only, content-hashed and exclusive by invocation/blog/language.
   A retry must reuse byte-identical content. A changed payload for that identity
   conflicts; do not replace it or allocate a fresh occurrence. The pending file
   records manuscript_saved/import_pending, exact slot, topic, target, path, time
   and duplicate_check_unavailable. No manuscript means do not report saved.
   The helper also preserves the resolver's actual Desktop session identity.
   Recovery re-reads that session's trigger and matches its scheduled occurrence
   or manual run. A configured RRULE alone is insufficient. Missing context is
   review-held; a historical session cannot relabel a newly written draft as its
   scheduled execution (execution time must remain within 6 hours of that start).
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

Historical failed slots are not current scheduled invocations. A development
session must not impersonate a Desktop cron or Run now trigger. Preserve failure
records; investigate/reconcile old artifacts first and record a distinct manual
recovery only with a supported actual invocation, never a fabricated provider ID.
