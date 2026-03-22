"""
HTML parser using only stdlib html.parser — no BeautifulSoup.

Why stdlib? The assignment says: "use language-native functionality rather than
fully featured libraries that do the core work of the exercise out of the box."
HTML parsing IS the core work, so we use Python's built-in HTMLParser.

This module extracts three things from an HTML document:
1. Page title (from <title> tag)
2. Visible text (excluding script/style/noscript content)
3. Links (from <a href="..."> tags, resolved to absolute URLs)
"""

from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse


class LinkTextExtractor(HTMLParser):
    """Event-driven HTML parser that extracts links, title, and visible text.

    HTMLParser works like SAX: it fires callbacks as it encounters tags.
    We track state (e.g., are we inside a <title>? inside a <script>?)
    to decide what to do with each piece of text we encounter.
    """

    # Tags whose content should be ignored (not visible to users)
    INVISIBLE_TAGS = frozenset([
        "style", "script", "noscript", "head", "meta", "link",
    ])

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url  # Needed to resolve relative URLs like "/page"
        self.links: list[str] = []
        self.title = ""
        self.text_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0  # Tracks nesting depth inside invisible tags

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag == "title":
            self._in_title = True
            return

        if tag in self.INVISIBLE_TAGS:
            self._skip_depth += 1  # Increment: we might have nested invisible tags
            return

        # Extract href from <a> tags and resolve to absolute URL
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                resolved = self._resolve_url(href)
                if resolved:
                    self.links.append(resolved)

    def handle_endtag(self, tag: str):
        if tag in self.INVISIBLE_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str):
        """Called for every text node in the HTML."""
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title += text
            return
        if self._skip_depth > 0:
            return  # We're inside <script>, <style>, etc. — skip
        self.text_parts.append(text)

    def _resolve_url(self, href: str) -> str | None:
        """Resolve a relative URL to absolute and normalize it.

        Normalization ensures deduplication works correctly:
        - "/page" and "https://example.com/page" become the same URL
        - Fragments (#section) are dropped (same page content)
        - Scheme and host are lowercased

        Returns None for non-HTTP URLs (mailto:, javascript:, tel:, etc.)
        """
        href = href.strip()
        if href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
            return None
        try:
            absolute = urljoin(self.base_url, href)
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https"):
                return None
            # Normalize: drop fragment, lowercase scheme and host
            normalized = urlunparse((
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path or "/",
                parsed.params,
                parsed.query,
                "",  # drop fragment
            ))
            return normalized
        except Exception:
            return None

    def get_text(self) -> str:
        return " ".join(self.text_parts)


def parse_html(html: str, base_url: str) -> tuple[str, str, list[str]]:
    """Parse HTML and return (title, visible_text, list_of_links).

    Uses only stdlib html.parser — no BeautifulSoup.
    Tolerates malformed HTML (common on real-world web pages).
    """
    parser = LinkTextExtractor(base_url)
    try:
        parser.feed(html)
    except Exception:
        pass  # Tolerate malformed HTML — extract whatever we can
    return parser.title.strip(), parser.get_text(), parser.links
