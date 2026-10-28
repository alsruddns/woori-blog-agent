# Blogger SEO metadata and pre-publish checks

The dashboard's SEO panel is an editorial checklist, not a ranking predictor. Title, description, keywords, and labels use the existing revision fields. Target region, search intent, core question, and core answer are stored in the append-only revision's `seo_metadata` JSON object from migration 041. Category and language derive from the manuscript; source identities are reloaded from the stored evidence relation. Official-source status and fact-verification time stay unknown unless the system has explicit reviewed evidence. No search volume, competition, click-through rate, impressions, or rank is estimated. The API model reserves nullable fields for future Search Console observations, but there is no account connection or performance collection in this release.

## Current Blogger support boundary

Reviewed on 2026-10-28 against Google's official documentation:

| Item | Current support / handling |
| --- | --- |
| Post title and HTML content | Blogger API v3 `Posts` resource fields `title` and `content` are documented. |
| Labels | `labels[]` is documented by the API and localized Trends labels remain deterministic metadata. |
| Per-post search description | Blogger Help describes a post editor's Search description setting. The API v3 `Posts` resource and `posts.insert` request body do not document a search-description property. The dashboard stores a description, but does not claim to send it through API v3. It requires manual Blogger editor entry unless future official API documentation adds a supported field. |
| Custom permalink | Blogger Help documents configuring a custom permalink in the post editor. No corresponding property is documented in the API v3 post resource; set it in Blogger UI and verify the resulting URL if required. |
| Image alt text | Blogger Help describes alt text in the editor. Renderer accepts an image only with a safe HTTPS URL and non-empty alt text; actual Blogger normalization must be checked after any separately approved post. |
| Canonical URL, robots, Open Graph | These are theme/site-level output and settings, not documented properties of the API v3 Posts resource. Do not inject duplicate tags into article content. Review the actual theme and page source before any manual change. |
| Article / BlogPosting structured data | No schema is emitted by this renderer. Add it only at theme level after checking that the live theme does not already emit equivalent structured data and that author, URL, title, and dates are accurate. |
| Sitemap and discovery | Site/blog level. Blogger's documented search visibility and crawler settings are managed in Blogger settings; this app does not modify them. |

Sources: [Blogger API Posts resource](https://developers.google.com/blogger/docs/3.0/reference/posts), [Blogger API posts.insert](https://developers.google.com/blogger/docs/3.0/reference/posts/insert), [Blogger Help: search visibility, headings, alt text, robots, and permalinks](https://support.google.com/blogger/answer/41373?hl=en), and [Blogger Help: blog settings, crawlers, and Search Console](https://support.google.com/blogger/answer/9691230?hl=en).

## Checks and limits

The pre-publish check reports title agreement, description presence, optional primary-term presence, heading/title duplication, source-link presence, official-source verification state, image alt text, local duplicate-content availability, fact-review timestamp, editorial review, and Search Console connection/measurement status. It makes no network requests to verify links or fetch search metrics. Duplicate-content checks are not run because a complete public-post corpus is not connected. A “ready” structural check does not establish article accuracy, indexing, rich-result eligibility, or ranking.

Trends issue labels are assigned only when a writer explicitly marks the article as Trends-based: `이슈` (ko), `Issues` (en), `話題` (ja), `热点` (zh-CN). Editors can inspect and change labels in the existing editorial revision flow. Related internal-link suggestions are not generated unless a verified destination is explicitly provided; this release does not fabricate post URLs.

## Versioning and maintenance

The renderer and design system version plus rendered HTML SHA-256 are returned by the non-persistent preview endpoint. The original Markdown, title, body, SEO metadata, and publication labels remain separate. Re-rendering is deterministic for the same renderer version and input. Update `services/api/woori/editorial_html.py`, `services/api/woori/editorial_seo.py`, the shared stylesheet `apps/dashboard/public/blogger-editorial.css`, and its optional theme copy together; run renderer, security, mobile layout, and dashboard checks. Migration 041 is additive and has not been applied to any operational database. The theme copy is not automatically installed. Preview behavior is an approximation until each live template is reviewed.

This release does not write Blogger posts or themes, connect Search Console, change database approval/readiness fields, or assert that search performance will improve.
