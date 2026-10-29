# External manuscript import

## Current operating path

The application has no in-process production AI generator connected and does not create or manage Codex Scheduled tasks. Official Codex desktop Local Scheduled tasks may write an external `woori-scheduled-content-import/1.0` envelope into `.local/gpt-scheduled-import/ready/`; one metadata-only local file probe was confirmed on 2026-10-29, while article-envelope generation and Import are not yet verified. The supported intake paths are manual import from **원고 가져오기** (`/imports`) and the separately configured local scheduled-import inbox. Neither path implies approval.

An import is an intake record, not a manuscript approval. The API validates the versioned envelope, BCP 47 target locale allowlist, category, explicit reader relevance, source manifest, claim-to-source references, HTTPS source URLs, timestamps, SEO metadata, and issue label. It does not fetch a source URL or trust a submitted verification flag as proof. The immutable record and receipt event remain in `external_content_imports` and `external_content_import_events`, always in `awaiting_human_review`, with `generation_ready=false` and `publish_ready=false`.

The existing Google Trends RSS collectors for KR, US, JP, TW, HK, and SG and the topic/evidence/Research Package pipeline remain the discovery path. The eight-category taxonomy is attached to topic candidates through append-only human classification. Finance/stocks/economy and technology/semiconductors/AI overlap groups are duplicate-review signals, not automatic event merges. Source region is recorded separately from article language. KR/US/JP/CN can suggest a language match for editorial consideration; TW/HK/SG do not imply Simplified Chinese. Additional target languages require a reader-relevance rationale. Suggestions never authorize posting.

## Exchange format

Contract: [`woori-content-import/1.0`](../schemas/woori-content-import-1.0.schema.json). The request body wraps the article object as `{ "submitted_by": "...", "item": { ... } }`.

- Use a stable `content_id` and `event_group_id`; derived localizations/revisions require a `parent_content_id`.
- Include every source in `sources` and `source_ids`; each claim must point to one or more listed source IDs and include an evidence excerpt and factual state.
- `rights_status=unknown` or `quotation_review_required`, conflicts, unverified claims, source freshness, and semantics remain for human review.
- Keep SEO and Blogger labels separate from article Markdown. Google Trends labels are deterministic: ko `이슈`, en `Issues`, ja `話題`, zh-CN `热点`.
- Markdown is stored as text. Raw HTML, internal workflow markers, unknown fields, non-HTTPS URLs, URL credentials, and unlisted claim references are rejected. URLs are never fetched on import.
- Duplicate `(generation_method, content_id)` with identical payload returns the existing import; changed payload under the same identity returns conflict. No import update or delete path exists.

## Review and publication boundary

Use the detail panel to inspect the complete Markdown, submitted source metadata, rights notes, and claims. The panel is review-only. It does not render imported markup as HTML, promote it into `content_versions`, create an editorial approval, or queue a Publisher job. That promotion bridge is intentionally not implemented: the current evaluation and operational manuscript stores use separate provenance/quality records, and imported self-attestation cannot satisfy those gates. A human must verify source documents and claim spans; a future promotion workflow must create new immutable versions and run the existing quality/SEO/editorial review before publication. Blogger real writes, Auto activation, and external AI calls remain disabled.

## Codex desktop Scheduled tasks capability review

Official OpenAI documentation supports Codex desktop Scheduled tasks operating in a selected local project. The scheduled task runs unattended using the configured sandbox/approval policy; the computer and app must remain available for local files. A probe file write was confirmed on 2026-10-29, but the probe was not a manuscript envelope and did not exercise Import. Local file writing is not an API/webhook integration: the task must write a complete envelope to the existing inbox, and the existing Import Worker must separately acknowledge it. Codex CLI and IDE do not manage Scheduled tasks; use the desktop Scheduled UI. Do not treat a ChatGPT web-only task as local-file capable.

The documentation says eligible models, availability, and usage limits depend on the specific task, account plan, and workspace. It does not establish this account's remaining usage or whether additional credits are enabled. The local schema validator, not prompt wording, is the machine-readable contract. Task scheduling is external and operator-managed; no hidden scheduler/provider is created by this repository. Check account usage before enabling recurring tasks where additional-credit spend is possible.

- [Scheduled tasks — OpenAI Learn](https://learn.chatgpt.com/docs/automations)
- [ChatGPT Work and Codex](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex)

The 2026-10-29 scheduled probe did not create a manuscript, Import record, or Blogger request. The exact account usage allowance and whether additional Codex credits are enabled are not visible to the project; recurring tasks must not be enabled until the operator confirms the account's usage settings and selected schedule.
