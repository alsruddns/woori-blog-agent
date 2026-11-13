# P5-CODEX-152 — Codex scheduled research fallback and retry-context repair

## Work record

- Date: 2026-11-13 (Asia/Seoul)
- Branch: `develop`
- Starting HEAD: `a2f5410` (`Fix : [P5-CODEX-151] Restore Brazil automation topic identity`)
- Append-only start audit: `agent.work.started`, ID `596201`.
- Scope: Codex Desktop scheduled authoring path only.
- Explicitly unchanged: Trends collection, manual Run now research/import behavior, automatic/manual publishing code and policy, P126–P133 policy/common decision logic, existing Desktop Automation definitions and schedules.
- Blogger writes and paid API calls: 0.

## Findings

- Local scheduled Research Packages confirmed `research_engine=fixed_rss_fallback` for Japan market close (`automation-2`, target topic in Japanese), Korea politics (`automation-8`), Korea market close (generic `automation`), Vietnam economy (`automation-12`), and the official Fed/SEC task (`fed-sec`). The packages for Japan, Korea and Vietnam contained U.S. Federal Reserve or White House material unrelated to their target country/topic.
- Cause: after a live Codex search returned `source_validation_failed` or `no_current_sources`, `run_authorized_research` replaced that result with a category-wide fixed feed and recorded `evidence_available`. It also used the same fallback for selected Codex infrastructure errors. Category alone does not establish country or topic relevance. The `general` category did not use a feed, which is why the Vietnam politics package stayed `evidence_unavailable` while other tasks using `economy` or `politics` appeared successful with unrelated sources.
- Retry identity was also under-bound: `automation-research-stage.py` reused an existing package based on occurrence ID and basic shape, without checking that topic/category matched. The saved generation preflight did not bind language, target country/blog, event group or topic, so a retry with altered task inputs could reuse stale context.
- The stored research packages/preflight artifacts show research completion only. The current local `import_receipts/` folder has no receipt for these runs; no article handoff, Import or publication can be inferred from `evidence_available`.

## Changes

- Scheduled research now preserves completed-search failures (`source_validation_failed` and `no_current_sources`) as evidence-unavailable packages and returns blocked on live-search infrastructure errors. No scheduled error path falls back to a category feed. Manual Run now's fixed-feed behavior is unchanged.
- The scheduled stage now adds the exact request context (Automation ID, category, language, country, Blogger ID, event-group ID and topic) to its immutable preflight record. On retries, it blocks when topic/category differs from the saved package or any scheduled request field differs from the saved preflight. Manual mode does not receive this binding or behavior change.
- Added regression coverage for unrelated-feed fallback prevention, exact scheduled retry context, and a scheduled handoff/import/receipt flow using a mocked API. The integration assertion keeps the item review-held and verifies zero Blogger writes.

## Validation

- Focused scheduled research, stage, handoff and inbox suites: **67 passed**.
- Ruff for changed Python files: passed.
- `git diff --check`: passed.
- Mocked scheduled handoff → Import → immutable Receipt E2E: passed; `execution_mode=scheduled`, exact occurrence preserved, `blogger_write_performed=false`, and no publish-ready state.
- No genuine current Desktop scheduled run was triggered; old slots were not replayed. Thus no production Import Receipt, publication queue result, or actual publication is confirmed by this change.
- No Desktop Automation TOML, recurrence, or task registration/deletion was performed. The official Desktop UI's currently loaded prompt state was not verified.

## Files

- `services/api/woori/scheduled_research.py`
- `scripts/automation-research-stage.py`
- `services/api/tests/test_scheduled_research.py`
- `services/api/tests/test_automation_research_stage_cli.py`
- `services/api/tests/test_scheduled_import_inbox.py`
- `docs/development/P5-CODEX-152.md`

## Remaining

- Confirm the official Desktop prompt still supplies the saved exact topic/category/locale/country/blog/event-group arguments on a future scheduled occurrence.
- Observe one naturally occurring new scheduled task through Research Package, validated envelope, ready handoff, production Import Receipt and downstream eligibility. Do not replay prior occurrences. Any real public post remains subject to existing independent gates and user authorization.
- Commit hash and remote push result are recorded in Git history after review.
