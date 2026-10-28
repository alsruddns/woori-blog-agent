# P5-CODEX-004 — Blogger expert-column HTML and preview

- Date: 2026-10-28 (KST)
- Branch: `develop`
- Objective: produce a safe, repeatable Blogger-body HTML preview that follows the P5-CODEX-003 expert-column rules without posting or changing editorial readiness.

## Initial state and scope

The manuscript detail view had a basic HTML iframe preview. Its Markdown fallback escaped all inline markup, did not render tables or citations as links, and did not show the Blogger title/label/source context together. The API HTML allowlist did not include accessible tables, figures, or the namespaced design classes. No Blogger theme/template CSS was found in the repository.

## Implementation

- Added a deterministic Markdown-to-Blogger-body renderer for article structure, inline emphasis/code/HTTPS links, lists, quotes, tables, and standalone image figures.
- Kept the Blogger post title out of body HTML. Matching H1s are omitted; other body H1s are converted to H2. SEO description remains metadata and is not injected into the body.
- Extended the sanitizer with a strict allowlist for semantic tables, HTTPS images with required alt text, and explicit `wb-*` design hooks. Active content, event attributes, unsafe URLs, and arbitrary styles remain excluded.
- Added authenticated, non-persistent `POST /admin/research/editorial-preview`, exposed through the existing same-origin Dashboard proxy. It only converts/sanitizes HTML and returns resolved labels; it performs no publication or DB write.
- Added a title-aware preview with rendered and HTML-source views, a Trends marker, locale labels, manuscript source text and source links. Saving an editorial revision includes the locale issue label when the author has explicitly marked it as Google Trends-based.
- The preview iframe is sandboxed and uses a strict CSP. Remote images are rendered as alt-text placeholders in the preview; the post HTML preserves safe HTTPS image URLs. This prevents page opening from making unreviewed remote image requests.
- Added an optional namespaced theme stylesheet and a guide. Existing live Blogger themes were not fetched or modified; compatibility with those templates remains unverified.
- Preserved the expert-writing standard and quality checks. No AI inference, DB migration, operational DB write, Blogger call, or publication-state change occurred.

## Validation

- Focused editorial test module: 22 passed. The added cases cover the actual stored Korean and English Codex evaluation articles, title de-duplication, safe rendering, table/image allowlists, locale labels, and non-persistent preview behavior.
- Ruff: passed for changed Python files.
- mypy: passed for `editorial_html.py` and `research_routes.py`.
- Dashboard ESLint: passed.
- Dashboard TypeScript typecheck: passed.
- Next.js production build: passed.
- Playwright preview E2E: 2 passed (desktop and mobile projects). At 320, 360, 390, and 430 CSS pixels, both the document and iframe had no horizontal overflow. The test also verified a single Blogger title heading, a title-free post body, the locale label, the source listing, the image placeholder, and zero external requests.
- Screenshots: [`P5-CODEX-004-preview-desktop.png`](assets/P5-CODEX-004-preview-desktop.png) and [`P5-CODEX-004-preview-320.png`](assets/P5-CODEX-004-preview-320.png).
- `git diff --check`: passed.

## Compatibility and remaining checks

Live theme CSS and Blogger's final sanitization/rendering behavior are not available from local repository assets and were not queried. The iframe is an approximation: Blogger's theme selectors, widgets, widths, font loading, image handling, and host-side HTML normalization can change the final appearance. Before any future live theme change, back up each theme and verify it in Blogger's theme preview. No live post, draft, theme, or operational DB data was changed.

## Audit and Git

- External services and AI: no calls; additional cost: 0.
- Blogger create/update/delete: 0.
- `generation_ready` / `publish_ready`: unchanged; no operational state was promoted.
- Existing untracked `.playwright-mcp/` was preserved and not staged.
- Commit and push result: to be filled after commit.
