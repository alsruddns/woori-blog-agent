# P5-CODEX-042 — Scheduled manuscript Blogger publication E2E readiness check

- Work ID: `P5-CODEX-042`
- Work time: 2026-10-29 17:26 KST (08:26 UTC)
- Branch: `develop`
- Outcome: `BLOCKED` for real public publication; implementation was not weakened to bypass configured gates.
- Reason: production currently has no scheduled-import manuscript or dispatchable live job, publication Auto/operations approval is disabled, the OAuth A access token is expired, no separate public-publish cost/operations approval exists, and the current import/review model sets `publish_ready=false`.

## Read-only runtime and DB snapshot

- Dashboard `http://127.0.0.1:3100`: HTTP 200, listener PID 15276.
- FastAPI `http://127.0.0.1:8100/health`: `{"status":"ok"}`, listener PID 5872 (checkout runner PID 29772).
- Research Worker: checkout process PIDs 30632/12528.
- Publication Worker: PIDs 42604/40100, launched as `publication-worker.py --operations-mock-only --continuous`; heartbeat is fresh. This process does not dispatch live Blogger jobs.
- Queue snapshot: mock queued/due 0; live queued/due 0; live blocked/uncertain 0. Last existing job is fake, blocked, `quality_held`.
- Read-only DB identity: `woori_blog_agent` / `woori_app`.
- Imports: one historical import total, zero `chatgpt_scheduled_export`; no scheduled-origin receipt events. Latest evaluation row: machine-passed 1, publish-ready 0.
- Publication mode: global `manual`, daily limit 1, interval 1440 minutes, emergency stop off, `operations_auto_approved=false`. All four publication policies are inactive and `auto_publish_allowed=false`.
- Inbox currently has zero `*.ready.json` and zero `*.processed.json`. The prior quarantine/rejected incident files are named `*.processing.json`; they were not moved or reprocessed.
- Four registered blogs map to OAuth A (`4839f8b9-69c8-4ce4-b1c1-5b71e96d5896`), with Blogger write scope stored. Its access token expiry is 2026-10-29 13:51:58 KST, before this check; no refresh or Blogger request was attempted. All `test_publish_verified_at` values are null.
- Existing audit has one Blogger zero-cost attestation, scoped to reads/private draft/user-approved update. There is no `external.blogger.public_publish.approved` event. External policy reports no billable-credential variable names, allows the prior narrow scope, and explicitly reports `public_publish_approved=false`.
- The registered 15 Codex Scheduled task objects are external to this checkout. Their IDs, models, schedules, execution history, and sandbox settings cannot be inspected or changed through repository APIs; they were left untouched.

## First failing stage and code gates

The first zero is before scheduled import: the operational DB has zero scheduled imports, and the local ready/processed folders have zero scheduled envelopes. Consequently there is no scheduled version to assess, no auto-eligible manuscript, no live publishing job, and no publish URL.

After import, content is explicitly untrusted and remains `awaiting_human_review`; assessment writes `publish_ready=false`. The publication candidate gate additionally requires reviewed active sources, reviewed evidence facts, a reviewed package with independent-source evidence, rights review, SEO and sanitized HTML, human editorial approval, publication approval bound to the exact body hash, and `publish_ready=true`. Minor style warnings can be separated in a future policy change, but doing so would not resolve the current missing source/rights/review approvals.

The live queue path also checks the exact registered blog/OAuth mapping, the separate public-publish external-policy event, and current publication settings. Schema 042 constrains `operations_auto_approved` to false; runtime mode APIs always return it as false. The current live worker runs mock-only. No direct DB setting, audit event, approval, or worker argument was changed to get around these controls.

## Safety and validation

- Read-only runtime/API/DB checks only; no operations DB writes, OAuth refresh, external Blogger call, Import reprocessing, content edit, queue insert, Auto toggle, or public post.
- Existing tests covering import, publication gates, publication modes, and Blogger live policy: **63 passed** against the dedicated isolated test DB/Mock transports.
- No production code or existing Scheduled task was modified because the concrete blockers are missing external approvals/data and persistent product-level hard gates; loosening them without an approved policy transition would violate the existing repository rules.
- Existing `.playwright-mcp/` remains untouched.

## Required before resuming live Auto publication

1. Review the Blogger API price/billing/quota uncertainty in `docs/operations/zero-cost-policy.md` in Google Cloud Console. The current repository attestation does not verify project billing or prove a zero-cost public-publish operation.
2. Provide/record the distinct explicit public-publish and unattended Auto operations approval through an approved, auditable path. There is no current application command that records this approval, and schema 042 intentionally prohibits `operations_auto_approved=true`.
3. Refresh/re-consent OAuth A through the official Google flow if the normal token refresh does not succeed; verify write scope and all target blog mappings. No token was exposed or changed here.
4. Generate or receive an actual scheduled envelope; the 15 Scheduled task objects and their runs are not visible from this checkout. Confirm a ready file and successful Import receipt before assessing an article.
5. Preserve factual, source-rights, duplicate, language/blog, HTML, and Blogger remote-state gates. A high-level style/SEO warning can be nonblocking only after a narrowly scoped scheduled-content policy and tests are explicitly approved; it must not mark human review or rights checks as passed.

## Git

This diagnostic record is committed separately; see final report and `git log` for SHA and push state.
