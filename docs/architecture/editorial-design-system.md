# Versioned editorial design and rendering system

## Sources of truth

- `services/api/woori/editorial_html.py` converts Markdown and sanitizes allowed HTML. It removes a body H1 that matches the Blogger post title, converts a distinct H1 to an H2, strips front matter and unsupported active markup, and never invents editorial copy.
- `services/api/woori/editorial_seo.py` validates structured SEO metadata and produces deterministic, actionable checks without a ranking score or network lookups.
- `apps/dashboard/public/blogger-editorial.css` is the preview stylesheet. `docs/operations/blogger-editorial-theme.css` is the optional copy for a human-reviewed Blogger theme integration. Keep the two byte-identical.
- Design system version `1.1.0` and renderer version `1.1.0` appear in preview responses alongside the rendered body SHA-256. Inputs and original Markdown remain separate from generated HTML.

## Tokens and responsive behavior

The stylesheet uses `--woori-article-*` tokens for body type, line height, reading width, H2/H3 sizes, paragraph and heading spacing, color, border, accent, surface, and radius. Defaults are 17px/1.8, 750px, H2 25px, H3 20px. Mobile body copy never drops below 16px. Tables have a bounded scroll wrapper; URLs, numbers, cards, and images can wrap or shrink within the article column. Typography fallbacks cover Korean, Japanese, Simplified Chinese, and system fonts.

## Markup contract

Semantic tags express the authored content: paragraphs, headings, lists, quote, table, figure/caption, and source links. Optional `wb-summary`, `wb-stat-grid`, and `wb-stat-card` hooks are only used when the source already contains those authored elements. A card is presentation, not a computed claim. No inline style, script, event handler, JSON-LD, meta description, canonical tag, robots tag, or invented image is generated. HTTPS links and images are sanitized; images without safe HTTPS source and alt text are dropped. Blogger owns the title display; no H1 remains in post-body HTML.

## Preview and Blogger differences

Dashboard preview uses a sandboxed iframe, strict CSP, and the shared stylesheet. External images render as local alt-text placeholders to avoid requests from an untrusted article. Preview supports separate rendered, HTML, and SEO views. The live Blogger theme is not fetched or modified, so its global selectors, width, fonts, widgets, Blogger HTML normalization, and meta/structured-data output may differ. Apply the optional CSS manually only after backing up and checking each theme. A preview is not proof of the four live themes' appearance.

## SEO metadata and review

Each immutable human revision stores the SEO metadata object from migration 041: language, target region when known, search intent, primary/related terms, SEO title, search description, core question/answer, category, labels, source records, and review fields. Source identities are reloaded from stored evidence; the client cannot self-certify a source as official. Missing verification time and officiality remain unknown. Revision audit events contain the SEO metadata SHA-256, not the metadata copied into a separate mutable log. Existing original content and revisions are not rewritten. Search Console fields are a nullable contract only; no Google account is connected and all unavailable metrics are shown as unmeasured.

## Non-submitting publication preparation artifact

The editorial preview can create a deterministic JSON preparation artifact on demand. It uses the registered blog mapping and the exact renderer output, title, labels, SEO metadata, content/revision identity, and renderer/design versions. The builder has no network or database access; the route performs a read-only lookup of a registered blog row. The artifact is offered in the preview and can be downloaded locally; it is not persisted to the operations database. It does not evaluate approval, change readiness, submit a request, or establish current Blogger access. `publish_ready` is always false and blockers remain until an explicitly authorized future workflow performs fresh access and policy checks.

Only the documented Blogger post fields `title`, `content`, and `labels` are included in the illustrative request body. The request shape is not executed. Search description, custom permalink, canonical/robots, Open Graph, and structured data are surfaced as manual/theme review items rather than guessed API fields. The live themes for `trend-ko.blogspot.com`, `trend-journal-en.blogspot.com`, `trend-zh.blogspot.com`, and `trend-ja.blogspot.com` were not fetched or inspected. Local collision fixtures test representative Blogger-style selector conflicts only; they do not establish live compatibility.

## Updating and testing

For a style adjustment, change the canonical CSS and copy it to the operations theme stylesheet; do not regenerate articles. For new HTML features, extend the allowlist deliberately, add malicious-input and deterministic-render tests, and confirm the feature remains evidence-neutral. Changes to revision SEO storage require a new additive migration after 041; never rewrite old immutable revision JSON. Run the focused article-review tests, Python lint/type checks, dashboard lint/typecheck/build, and Playwright layout test at 320, 390, 430, 768, and 1280px. Do not apply migration 041 to an operational database as part of this design task.
