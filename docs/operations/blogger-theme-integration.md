# Blogger theme integration checklist

This is a manual integration guide. The application does not fetch, edit, or save any Blogger theme.

## Current verification boundary

- The four configured blog names and registered mappings are used only as local preparation metadata: `trend-ko.blogspot.com`, `trend-journal-en.blogspot.com`, `trend-zh.blogspot.com`, and `trend-ja.blogspot.com`.
- No live theme XML/CSS or public Blogger page was retrieved for this task. Live selector conflicts, widths, fonts, widgets, Blogger normalization, canonical/robots tags, Open Graph output, and structured-data duplication remain unverified.
- Playwright used local fixture themes with representative `post-body`, `entry-content`, and `blog-post` selectors. Fixture success is not proof about the live templates.
- The preview is sandboxed and substitutes remote images with alt-text placeholders. A live Blogger page may resolve images, font stacks, links, scripts/widgets, and layout differently.

## Manual application procedure

1. In Blogger, back up the theme XML for one blog before testing. Do not copy a theme from another locale without comparing its widgets and layout.
2. Review the optional, namespaced CSS in [`blogger-editorial-theme.css`](blogger-editorial-theme.css). Keep selectors under `.wb-article`; do not paste global `body`, `.post-body`, heading, table, or link rules into a theme without checking specificity and side effects.
3. In Blogger Theme > Customize > Advanced > Add CSS, add the scoped CSS to a staging or low-risk theme preview first. Alternatively, edit the theme XML only after creating and checking a backup. Blogger's UI labels can differ by account/template.
4. Preview each language at narrow mobile, tablet, and desktop widths. Check the template's post-body width and inherited fonts, title/date/labels, tables, long URLs, images, captions, and source links.
5. Inspect the rendered page source for duplicate canonical, robots, Open Graph, or Article/BlogPosting metadata before any manual save. Do not add duplicate tags or change indexing directives as a workaround.
6. Save theme changes only through a separately authorized human operation, then review a public post and rollback using the saved theme backup if the layout regresses.

The local preview stylesheet is [`../../apps/dashboard/public/blogger-editorial.css`](../../apps/dashboard/public/blogger-editorial.css); the optional theme copy is [`blogger-editorial-theme.css`](blogger-editorial-theme.css). Keep these copies synchronized and run the renderer/layout tests after changes. A shared style system improves consistency but cannot guarantee identical rendering across Blogger templates.

## Blogger API preparation limits

The Posts API request artifact contains only `title`, `content`, and `labels`, and is never submitted by this feature. The Posts resource documents those fields; search descriptions and custom permalink settings are surfaced separately for human review rather than added as undocumented request properties. Search descriptions and theme SEO settings must be checked in Blogger's editor/theme UI. This phase did not issue Blogger API requests.

References: [Blogger Posts resource](https://developers.google.com/blogger/docs/3.0/reference/posts), [Blogger theme CSS and layout help](https://support.google.com/blogger/answer/176245?hl=en-US-u-mu-fahrenhe).
