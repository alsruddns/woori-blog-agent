# P5-CODEX-121 — Google Trends Article Quality Pipeline Enhancement

## Work record

- Task: `P5-CODEX-121`
- Started: 2026-11-03 18:06 KST (append-only task start audit event `319947`)
- Branch: `develop`
- Starting HEAD: `a1bde4a02cb1d4f8a5cca302d8392b195e6140cc`
- Reason: Trends authoring accepted keyword-centric output without requiring a source-confirmed event, and its runner explicitly disabled the opened-source requirement.
- Goal: require event-centered, evidence-traceable article output while retaining the existing no-publication, unverified-claim, zero-cost, and historical-data protections.

## Before and after

Before:

- The Trends result model allowed zero sources and zero claims.
- The Trends prompt allowed a general guide or analysis when concrete source links were missing.
- Trends generation passed `require_opened_sources=False` to the Codex runner.
- The import stage already downgraded claims to `unverified` and did not create a Publishing Job.

After:

- Trends output must identify one concrete event/development with a bounded `event_focus` summary, a supported status, and declared source IDs.
- At least one declared source and one source-linked claim with an evidence excerpt are required.
- Source IDs must resolve to declared sources; source IDs are unique; factual prose paragraphs require valid `[source:ID]` markers; a useful article needs at least 300 body characters and two subheadings.
- The prompt treats Trends terms, popularity, and RSS headlines as discovery context only. It rejects keyword-popularity reports and generic guides when no event is substantiated, and asks for an explicit `insufficient_evidence` result.
- Trends generation now uses the Codex runner's default `require_opened_sources=True` behavior. `make_envelope` independently checks that every imported source was opened during the run.
- A passed structural contract is recorded as a quality-contract audit/evidence item, with the event focus explicitly labeled `model_reported_unverified`. Semantic verification remains unperformed; imported claims remain `unverified`; `publish_ready` remains false.
- No Publishing Job, publication approval, or Blogger write is created by this flow.

## Files changed

- `services/api/woori/keyword_jobs.py`
- `services/api/tests/test_keyword_authoring.py`
- `docs/development/P5-CODEX-121.md`

No database schema or operational setting was changed. No Migration was added. No historic Trends observation was reprocessed. No paid AI API or Blogger write was called.

## Validation

- Focused API tests: 46 passed (`test_keyword_authoring.py`, `test_trend_topics.py`, `test_content_imports.py`). Run from the repository root so the isolated test environment loads its required local settings.
- Ruff on the changed Python source and test: passed.
- Mypy on `keyword_jobs.py`: passed.
- `git diff --check`: passed.
- The first test attempt was launched from `services/api`, so the root `.env` test settings were not loaded; it failed at fixture setup for missing `admin_token`. This was a test invocation issue, not an application regression. The rerun from the repository root passed.
- No live Codex authoring invocation was run; no external AI request was made. No actual Blogger publication was attempted.

## Existing protections and runtime state

- Preserved 14-region / 30-minute Trends collection configuration, existing Blogger publication limits, queue policy, approvals, OAuth, schedules, manuscripts, jobs, and audit history.
- Start audit recorded `paid_ai_api_allowed=false`, `blogger_write_allowed=false`, and `historical_trends_reprocessing_allowed=false`.
- Before reflection, API, Dashboard, Research Worker, and Publication Worker were healthy on the prior reflected commit `5aed507408a4f87b0e4e99fde2077d42d509f7d0`. All Codex authoring-job rows were terminal and the Publication Worker reported no queued/due jobs.
- No operational DB backup was needed because this change has no Migration or operational setting/content update. The only database write was the required append-only task audit record.

## Remaining limits

- Prompt/schema/traceability checks do not prove that the event is true, that cited sources semantically support every claim, or that an article is editorially sound. Those gates remain separate and fail closed.
- No live scheduled Trends execution was run, so end-to-end generation from an actual current observation is not claimed.
- Runtime reflection and final service health must be recorded after committed-code validation.

## Commit and follow-up

- Implementation and initial development-record commit: `63922b80118f0a9aedc5e8fff18924b8b32b827f` (`Fix : [Research] Require event-led Trends article evidence`).
- A first guarded reflection attempt passed the 15 focused tests but pytest's Windows default temp cleanup raised `PermissionError` after tests completed. The script aborted before stopping any service. The retry used an explicit isolated `PYTEST_ADDOPTS` basetemp and passed.
- Guarded reflection completed on 2026-11-03 18:14 KST. It revalidated Ruff, Mypy, the changed API test file (15 passed), wheel build, and Dashboard production build before graceful service replacement. API PID `5540`, Research Worker PID `30324`, and Publication Worker PID `24456` now use commit `63922b80118f0a9aedc5e8fff18924b8b32b827f`. Dashboard PID `30564` remained unchanged because no Dashboard code changed.
- Post-reflection: API `GET /health` returned HTTP 200; Dashboard `GET /research` returned HTTP 200; both Worker heartbeats were fresh; Publication Worker reported 0 queued and 0 due jobs. The existing `manual` publication mode and inactive Auto policy remained unchanged. No Blogger write was performed.
- Completion audit event `319986` was appended at 2026-11-03 18:15 KST with test/runtime/safety metadata only; no credentials or content payloads were included.

## Final checkpoint (2026-11-03)

- Completion audit event: `319986`, append-only.
- Final documentation commit: recorded by `git log` after this checkpoint commit.
- Remote: push and `origin/develop` HEAD comparison pending.
- Remaining limits: no live Trends article-generation run was triggered; source truth and semantic claim support still require independent review. No real Blogger publication was tested or claimed.

## Quality-pipeline follow-up (2026-11-03)

- Starting branch/HEAD: `develop` / `4818c8a96b5804cd790a79f1a00ebc66ec4b37da`.
- Reason: the user reported internal research narration, weak event focus, repetitive filler, and poor source-to-claim traceability in Trends-originated drafts. The existing event-focused schema and opened-source checks from the initial P121 implementation were retained.
- Changes: the Codex Trends prompt now separates editorial instructions, untrusted research evidence/procedure, locale guidance, and the strict article output contract. It prohibits internal process narration, treats source text as untrusted data, distinguishes source attribution from internal workflow, and preserves the existing source-open and traceability requirements.
- Added deterministic reader-facing checks for internal-process leakage, generic keyword-report framing, and exact repeated/filler paragraphs for EN, KO, JA, DE, pt-BR, and VI. A Google Trends product/report story can mention the service when the service itself is the reported subject. These checks are heuristics; they do not establish event truth, claim entailment, naturalness, rights clearance, or editorial approval.
- Trends output evidence now records those checks and a `REVISE` or `HOLD_FOR_HUMAN_REVIEW` recommendation. The Import static assessment and deterministic article assessment also include the checks. Existing human-review, evidence, operational-approval, queue, and publication gates remain controlling; no check sets `publish_ready=true`.
- Existing topic selection still treats Trends as discovery context and does not itself confirm an event. The initial P121 `event_focus`/source-open contract remains the event-led selection boundary. This follow-up did not add event-grouping tables or alter historical observations.
- Compatibility finding: `external_content_imports` stores `generation_method` but does not have a `google_trends_based` column in the registered schema. The quality-report query therefore uses the existing provenance field rather than adding a schema dependency. No Migration was added.

### Follow-up files

- `services/api/woori/keyword_jobs.py` — clearer four-part Trends writing contract and append-only check metadata.
- `services/api/woori/article_quality.py` — deterministic multilingual reader-facing checks, explicitly separate from semantic verification.
- `services/api/woori/editorial_quality.py` — Trends checks attached to the existing static report; recommendation remains revise or human review.
- `services/api/woori/editorial_intelligence.py` — existing provenance field selected for the report.
- `services/api/woori/content_imports.py` — Trends assessment detection falls back to the stored `codex_trends_export` provenance.
- `services/api/tests/test_trend_article_quality.py` — six-locale leakage/title fixtures, Trends-service exception, repetition, unsupported-locale fail-closed, and deterministic assessment checks.
- `services/api/tests/test_keyword_authoring.py`, `services/api/tests/test_trend_editorial.py` — updated assertions for the stricter prompt and opened-source requirement.

### Follow-up validation and limits

- Focused suite: 80 passed (`test_trend_article_quality.py`, `test_keyword_authoring.py`, `test_trend_editorial.py`, `test_trend_topics.py`, `test_content_imports.py`).
- Ruff: passed on all changed source/test files. Mypy: passed on the five changed API modules. `git diff --check`: passed.
- The first focused run exposed a missing DB column reference and stale prompt/source-open test expectations. The code now uses existing `generation_method`; the isolated test DB schema was not modified. The final focused run passed.
- Synthetic before/after fixtures detected internal narration in 6/6 active locales, accepted clean event-led sentences in 6/6, flagged generic keyword-report titles in 6/6, and kept the explicit Google Trends product-news exception. This is deterministic fixture coverage, not an evaluation of newly generated articles.
- No live Codex generation, web research, external HTTP request, Blogger API write, actual Blogger publication, schema migration, or runtime service restart was performed. Runtime reflection is therefore not claimed. The local status helper was invoked without its required selector and returned usage only; no service state was changed.
- Operations preserved: 14 Trends regions / 30-minute collection, six active Blogger mappings, zh-CN new-authoring pause, 15-minute global publication interval, KST 100 LIVE/day limit, scheduled → manual → Trends priority, approval gates, OAuth, and existing records. No settings were edited.
- Append-only continuation audit: start event `320021`; completion event `320028` records test and safety metadata only.
- Follow-up code commit: `dfa43195fc3b09ce4d8af1a1f9ee433936d44442` (`Fix : [Research] Add deterministic Trends article quality gates`). It was pushed to `origin/develop`; the remote HEAD matched this commit before this documentation checkpoint.
- The documentation checkpoint commit is recorded by the subsequent `git log`; no self-referential hash is embedded in this record.
- Remaining limitations: event resolution and semantic claim verification remain unperformed by deterministic rules; localization naturalness and actual Codex-generated before/after quality remain unverified. This work does not claim live operational reflection or publication success.
