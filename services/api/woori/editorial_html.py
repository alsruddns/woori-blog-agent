"""Small allowlist sanitizer for human-authored article markup."""

from __future__ import annotations

from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit

ALLOWED_TAGS = {
    "p", "h2", "h3", "ul", "ol", "li", "strong", "b", "em", "i",
    "a", "blockquote", "br", "code",
}
BLOCK_TAGS = {"p", "h2", "h3", "ul", "ol", "li", "blockquote"}
VOID_TAGS = {"br"}
BLOCKED_TAGS = {"script", "style", "iframe", "object", "svg", "math"}


def _safe_href(value: str) -> bool:
    parsed = urlsplit(value.strip())
    if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
        return True
    return value.startswith("/") and not value.startswith("//") and not parsed.scheme


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.text: list[str] = []
        self.open_tags: list[str] = []
        self.blocked_tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.blocked_tags:
            if tag in BLOCKED_TAGS:
                self.blocked_tags.append(tag)
            return
        if tag in BLOCKED_TAGS:
            self.blocked_tags.append(tag)
            return
        if tag not in ALLOWED_TAGS:
            return
        if tag in BLOCK_TAGS:
            self.text.append("\n")
        if tag == "a":
            href = next((value for name, value in attrs if name.lower() == "href"), None)
            if href and _safe_href(href):
                self.output.append(f'<a href="{escape(href.strip(), quote=True)}" rel="nofollow noopener noreferrer">')
            else:
                self.output.append("<a>")
        else:
            self.output.append(f"<{tag}>")
        if tag not in VOID_TAGS:
            self.open_tags.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
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
        if self.blocked_tags or not data:
            return
        self.output.append(escape(data, quote=False))
        self.text.append(data)

    def close(self) -> None:
        super().close()
        while self.open_tags:
            opened = self.open_tags.pop()
            self.output.append(f"</{opened}>")
            if opened in BLOCK_TAGS:
                self.text.append("\n")


def sanitize_editorial_html(value: str) -> tuple[str, str]:
    if len(value) > 100_000:
        raise ValueError("editorial_html_too_large")
    parser = _Sanitizer()
    parser.feed(value)
    parser.close()
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
