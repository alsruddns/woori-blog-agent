# Blogger expert-column HTML and preview

The editorial renderer produces deterministic, sanitized post-body HTML. The Blogger post title remains a separate API field; a matching Markdown or HTML `h1` is omitted from the body. A nonmatching body `h1` becomes `h2`. SEO description metadata is shown separately and is never inserted into the article body automatically.

Markdown supports paragraphs, `h2`/`h3`, emphasis, inline code, HTTPS links, lists, blockquotes, horizontal rules, accessible comparison tables, and standalone HTTPS images with alt text and an optional caption. Tables are wrapped for narrow screens. Authors can explicitly use the allowlisted `wb-summary`, `wb-stat-grid`, and `wb-stat-card` HTML classes where a card communicates the same authored information. The renderer does not infer or rewrite factual claims to create cards.

Google Trends status must be explicitly recorded or selected in the preview. When marked as Trends-based, the preview and the next saved editorial revision use the locale label: `이슈` (`ko`), `Issues` (`en`), `話題` (`ja`), or `热点` (`zh-CN`). The checkbox only changes preview state until an editor saves a new version. It does not publish or change readiness.

The preview is a sandboxed iframe with a strict CSP. Remote images are replaced by alt-text placeholders in the preview so opening an article cannot trigger an unreviewed third-party request. The returned post HTML retains safe HTTPS image references for a separately approved future publish flow. No Blogger API call is made by this feature.

## Theme compatibility

No Blogger theme/template source is present in the repository, and this change does not fetch or edit a live Blogger theme. Therefore compatibility with the four live templates has not been verified. The optional, namespaced stylesheet is [`blogger-editorial-theme.css`](blogger-editorial-theme.css); review a theme backup and its preview before a human manually applies it. The application does not write theme settings.

The local iframe reproduces the Blogger title area and the article-body typography, but actual pages can differ due to each template's global selectors, selector specificity, content width, widgets, font loading, image hosting/transformations, and Blogger-side HTML normalization. Until the optional stylesheet is manually reviewed and applied, the post HTML remains semantically formatted but will use each blog's existing theme styling.

The reference article rules and quality gate in `docs/architecture/editorial-writing-standard.md` remain unchanged. This renderer changes presentation only; it does not grant editorial approval, `generation_ready`, or `publish_ready`.
