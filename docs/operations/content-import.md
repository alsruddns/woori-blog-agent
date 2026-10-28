# Manual external manuscript import

## Current operating path

The application has no production AI generator connected. ChatGPT Scheduled Tasks and Codex are not registered as background providers, and this repository does not create scheduled tasks or call a hidden Codex process. The supported handoff is a user-reviewed JSON export imported from **원고 가져오기** (`/imports`).

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

## ChatGPT Scheduled Tasks capability review

Official documentation describes scheduled tasks as ChatGPT-run work with supported schedules and supported connected-app events. Current documented event-triggered app sources include Gmail, Slack, and GitHub; the documentation does not define a generic webhook endpoint or automatic local file/API delivery for this project. Project files are unavailable to a scheduled task created in a ChatGPT Project. Work on desktop may use local files when the user opens a local folder and grants access, but the local task is not thereby an integration into this application's API. Codex remains a separate workflow. Therefore scheduled output should be reviewed and manually exported/imported; no unattended delivery is claimed.

The documentation says eligible models, availability, and usage limits depend on the specific task, account plan, and workspace. It does not promise strict machine-readable export conformance or establish that every account's scheduled work is covered without additional metered usage. The local schema validator, not prompt wording, is the machine-readable contract. No task or external account setting was created or changed here.

- [Scheduled tasks in ChatGPT](https://help.openai.com/en/articles/10291617-scheduled-tasks-in-chatgpt)
- [ChatGPT Work and Codex](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex)
- [Set up scheduled tasks](https://developers.openai.com/training/walkthroughs/scheduled-tasks)

Recheck the official product documentation and the account's available app surface before designing any future automated handoff. This phase did not create a task, connect an app, change permissions, call an AI endpoint, or make a Blogger request.
