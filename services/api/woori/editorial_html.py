"""Deterministic Blogger article rendering and strict allowlist sanitizing."""

from __future__ import annotations

import re
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

ALLOWED_TAGS = {
    "p", "h2", "h3", "ul", "ol", "li", "strong", "b", "em", "i",
    "a", "blockquote", "br", "code", "hr", "figure", "figcaption", "img",
    "div", "article", "table", "thead", "tbody", "tr", "th", "td",
}
BLOCK_TAGS = {
    "p", "h2", "h3", "ul", "ol", "li", "blockquote", "hr", "figure",
    "figcaption", "div", "article", "table", "thead", "tbody", "tr", "th", "td",
}
VOID_TAGS = {"br", "hr", "img"}
BLOCKED_TAGS = {"script", "style", "iframe", "object", "svg", "math"}
ALLOWED_CLASSES = {
    "wb-article", "wb-lead", "wb-summary", "wb-stat-card", "wb-stat-grid",
    "wb-table-wrap", "wb-figure", "wb-caption", "wb-sources", "wb-source-list",
}


def _safe_href(value: str) -> bool:
    parsed = urlsplit(value.strip())
    if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
        return True
    return value.startswith("/") and not value.startswith("//") and not parsed.scheme


def _safe_image_src(value: str) -> bool:
    parsed = urlsplit(value.strip())
    return bool(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password)


class _Sanitizer(HTMLParser):
    def __init__(self, post_title: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.text: list[str] = []
        self.open_tags: list[str] = []
        self.blocked_tags: list[str] = []
        self.post_title = " ".join(post_title.casefold().split())
        self.heading_one_text: list[str] | None = None
        self.unclosed_h1 = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.heading_one_text is not None:
            return
        if self.blocked_tags:
            if tag in BLOCKED_TAGS:
                self.blocked_tags.append(tag)
            return
        if tag in BLOCKED_TAGS:
            self.blocked_tags.append(tag)
            return
        if tag == "h1":
            self.heading_one_text = []
            return
        if tag not in ALLOWED_TAGS:
            return
        if tag in BLOCK_TAGS:
            self.text.append("\n")
        attributes = {name.lower(): value for name, value in attrs if value is not None}
        css_class = attributes.get("class", "").strip()
        class_attr = f' class="{escape(css_class, quote=True)}"' if css_class in ALLOWED_CLASSES else ""
        if tag == "a":
            href = next((value for name, value in attrs if name.lower() == "href"), None)
            if href and _safe_href(href):
                self.output.append(f'<a href="{escape(href.strip(), quote=True)}" rel="nofollow noopener noreferrer">')
            else:
                self.output.append("<a>")
        elif tag == "img":
            src = attributes.get("src", "").strip()
            alt = attributes.get("alt", "").strip()
            if not src or not alt or not _safe_image_src(src):
                return
            title = attributes.get("title", "").strip()
            title_attr = f' title="{escape(title, quote=True)}"' if title else ""
            self.output.append(f'<img src="{escape(src, quote=True)}" alt="{escape(alt, quote=True)}"{title_attr}>')
        elif tag in {"th", "td"}:
            scope = ' scope="col"' if tag == "th" and attributes.get("scope") == "col" else ""
            self.output.append(f"<{tag}{scope}{class_attr}>")
        elif tag in {"div", "figure", "article"}:
            self.output.append(f"<{tag}{class_attr}>")
        elif tag == "figcaption":
            caption_class = ' class="wb-caption"' if attributes.get("class") == "wb-caption" else ""
            self.output.append(f"<figcaption{caption_class}>")
        else:
            self.output.append(f"<{tag}>")
        if tag not in VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.heading_one_text is not None:
            if tag == "h1":
                heading = " ".join("".join(self.heading_one_text).split())
                if heading and heading.casefold() != self.post_title:
                    self.output.append(f"<h2>{escape(heading, quote=False)}</h2>")
                    self.text.extend(("\n", heading, "\n"))
                self.heading_one_text = None
            return
        if self.blocked_tags:
            for index in range(len(self.blocked_tags) - 1, -1, -1):
                if self.blocked_tags[index] == tag:
                    del self.blocked_tags[index:]
                    break
            return
        if tag not in self.open_tags:
            return
        while self.open_tags:
            opened = self.open_tags.pop()
            self.output.append(f"</{opened}>")
            if opened in BLOCK_TAGS:
                self.text.append("\n")
            if opened == tag:
                break

    def handle_data(self, data: str) -> None:
        if self.heading_one_text is not None:
            self.heading_one_text.append(data)
            return
        if self.blocked_tags or not data:
            return
        self.output.append(escape(data, quote=False))
        self.text.append(data)

    def close(self) -> None:
        super().close()
        if self.heading_one_text is not None:
            self.unclosed_h1 = True
            self.heading_one_text = None
        while self.open_tags:
            opened = self.open_tags.pop()
            self.output.append(f"</{opened}>")
            if opened in BLOCK_TAGS:
                self.text.append("\n")


def sanitize_editorial_html(value: str, *, post_title: str = "") -> tuple[str, str]:
    if len(value) > 100_000:
        raise ValueError("editorial_html_too_large")
    parser = _Sanitizer(post_title=post_title)
    parser.feed(value)
    parser.close()
    if parser.unclosed_h1:
        raise ValueError("editorial_html_unclosed_h1")
    safe_html = "".join(parser.output).strip()
    plain_text = "\n".join(line.strip() for line in "".join(parser.text).splitlines() if line.strip())
    if not safe_html or not plain_text:
        raise ValueError("editorial_body_empty_after_sanitization")
    if len(plain_text) > 50_000:
        raise ValueError("editorial_body_text_too_large")
    return safe_html, plain_text


def plain_text_as_html(value: str) -> str:
    """Escape original text for first edit without interpreting existing markup."""
    paragraphs = [part.strip() for part in value.split("\n\n") if part.strip()]
    return "".join(f"<p>{escape(part, quote=False)}</p>" for part in paragraphs)


def _inline_markdown(value: str) -> str:
    """Render a deliberately small inline Markdown subset after escaping text."""
    token_pattern = re.compile(r"(`[^`]+`|\*\*.+?\*\*|__.+?__|\*[^*\n]+\*|_[^_\n]+_|!?\[[^\]]+\]\([^\s)]+(?:\s+\"[^\"]*\")?\))")
    output: list[str] = []
    cursor = 0
    for match in token_pattern.finditer(value):
        output.append(escape(value[cursor:match.start()], quote=False))
        token = match.group(0)
        if token.startswith("!["):
            image = re.fullmatch(r'!\[([^\]]+)\]\((https://[^\s)]+)(?:\s+"([^"]*)")?\)', token)
            if image and _safe_image_src(image.group(2)):
                title = f' title="{escape(image.group(3), quote=True)}"' if image.group(3) else ""
                output.append(f'<img src="{escape(image.group(2), quote=True)}" alt="{escape(image.group(1), quote=True)}"{title}>')
            else:
                output.append(escape(token, quote=False))
        elif token.startswith("["):
            link = re.fullmatch(r'\[([^\]]+)\]\(([^\s)]+)(?:\s+"([^"]*)")?\)', token)
            if link and _safe_href(link.group(2)):
                output.append(f'<a href="{escape(link.group(2), quote=True)}" rel="nofollow noopener noreferrer">{escape(link.group(1), quote=False)}</a>')
            else:
                output.append(escape(token, quote=False))
        elif token.startswith("`"):
            output.append(f"<code>{escape(token[1:-1], quote=False)}</code>")
        elif token.startswith(("**", "__")):
            output.append(f"<strong>{escape(token[2:-2], quote=False)}</strong>")
        else:
            output.append(f"<em>{escape(token[1:-1], quote=False)}</em>")
        cursor = match.end()
    output.append(escape(value[cursor:], quote=False))
    return "".join(output)


def markdown_to_blogger_html(markdown: str, *, post_title: str, summary: str = "") -> str:
    """Render article Markdown as Blogger body HTML; Blogger owns the post title."""
    if len(markdown) > 100_000 or len(post_title) > 500 or len(summary) > 500:
        raise ValueError("editorial_preview_input_too_large")
    source = markdown.replace("\r\n", "\n").replace("\r", "\n")
    if source.startswith("---\n"):
        closing = source.find("\n---\n", 4)
        if closing < 0:
            raise ValueError("editorial_preview_front_matter_not_closed")
        source = source[closing + 5:]
    blocks = re.split(r"\n\s*\n", source.strip())
    title_key = " ".join(post_title.casefold().split())
    rendered: list[str] = []
    index = 0
    while index < len(blocks):
        block = blocks[index].strip()
        if not block:
            index += 1
            continue
        lines = block.splitlines()
        if re.match(r"^#\s+", lines[0]):
            heading = re.sub(r"^#\s+", "", lines[0]).strip()
            # The Blogger post title is supplied by the platform, so never emit body H1.
            # A matching title is omitted entirely; any other H1 becomes a section heading.
            if " ".join(heading.casefold().split()) != title_key:
                rendered.append(f"<h2>{_inline_markdown(heading)}</h2>")
            index += 1
            continue
        if re.match(r"^#{2,3}\s+", lines[0]):
            level = 3 if lines[0].startswith("###") else 2
            heading = re.sub(r"^#{2,3}\s+", "", lines[0]).strip()
            rendered.append(f"<h{level}>{_inline_markdown(heading)}</h{level}>")
            if len(lines) > 1:
                blocks[index] = "\n".join(lines[1:])
            else:
                index += 1
                continue
            block = blocks[index].strip()
            lines = block.splitlines()
        if all(re.match(r"^\s*[-*+]\s+", line) for line in lines):
            rendered.append("<ul>" + "".join(f"<li>{_inline_markdown(re.sub(r'^\s*[-*+]\s+', '', line))}</li>" for line in lines) + "</ul>")
        elif all(re.match(r"^\s*\d+[.)]\s+", line) for line in lines):
            rendered.append("<ol>" + "".join(f"<li>{_inline_markdown(re.sub(r'^\s*\d+[.)]\s+', '', line))}</li>" for line in lines) + "</ol>")
        elif all(line.lstrip().startswith(">") for line in lines):
            quote = " ".join(re.sub(r"^\s*>\s?", "", line) for line in lines)
            rendered.append(f"<blockquote>{_inline_markdown(quote)}</blockquote>")
        elif len(lines) >= 2 and "|" in lines[0] and re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*", lines[1]):
            def table_cells(line: str) -> list[str]:
                return [cell.strip() for cell in line.strip().strip("|").split("|")]

            headers = table_cells(lines[0])
            rows = [table_cells(line) for line in lines[2:] if "|" in line]
            head = "<thead><tr>" + "".join(f'<th scope="col">{_inline_markdown(cell)}</th>' for cell in headers) + "</tr></thead>"
            body = "<tbody>" + "".join("<tr>" + "".join(f"<td>{_inline_markdown(cell)}</td>" for cell in row[:len(headers)]) + "</tr>" for row in rows) + "</tbody>"
            rendered.append(f'<div class="wb-table-wrap"><table>{head}{body}</table></div>')
        elif len(lines) == 1 and (image := re.fullmatch(r'!\[([^\]]+)\]\((https://[^\s)]+)(?:\s+"([^"]*)")?\)', lines[0].strip())):
            if _safe_image_src(image.group(2)):
                caption = f'<figcaption class="wb-caption">{escape(image.group(3))}</figcaption>' if image.group(3) else ""
                rendered.append(f'<figure class="wb-figure"><img src="{escape(image.group(2), quote=True)}" alt="{escape(image.group(1), quote=True)}">{caption}</figure>')
            else:
                rendered.append(f"<p>{_inline_markdown(lines[0])}</p>")
        elif re.fullmatch(r"-{3,}|\*{3,}|_{3,}", block):
            rendered.append("<hr>")
        else:
            paragraph = _inline_markdown(" ".join(line.strip() for line in lines))
            rendered.append(f'<p class="wb-lead">{paragraph}</p>' if not rendered else f"<p>{paragraph}</p>")
        index += 1
    sanitized, _plain = sanitize_editorial_html('<article class="wb-article">' + "".join(rendered) + "</article>")
    return sanitized


TREND_LABELS = {"ko": "이슈", "en": "Issues", "ja": "話題", "zh-CN": "热点"}


def resolve_blogger_labels(language_code: str, google_trends_based: bool, labels: list[str]) -> list[str]:
    """Apply locale issue label only when the caller identifies a Trends article."""
    normalized = language_code.strip()
    result = list(dict.fromkeys(label.strip() for label in labels if label.strip()))
    if google_trends_based and normalized in TREND_LABELS:
        locale_label = TREND_LABELS[normalized]
        return [locale_label, *(label for label in result if label.casefold() != locale_label.casefold())]
    return result
