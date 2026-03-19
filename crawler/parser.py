"""
HTML parser using only stdlib html.parser.
Extracts links, title, and visible text from HTML documents.
"""

from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlunparse


class LinkTextExtractor(HTMLParser):
    """Extracts hyperlinks, page title, and visible text from HTML."""

    INVISIBLE_TAGS = frozenset([
        "style", "script", "noscript", "head", "meta", "link",
    ])

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []
        self.title = ""
        self.text_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag == "title":
            self._in_title = True
            return

        if tag in self.INVISIBLE_TAGS:
            self._skip_depth += 1
            return

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
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title += text
            return
        if self._skip_depth > 0:
            return
        self.text_parts.append(text)

    def _resolve_url(self, href: str) -> str | None:
        """Resolve a relative URL and normalize it. Returns None for non-HTTP URLs."""
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
    """
    Parse HTML and return (title, visible_text, list_of_links).
    Uses only stdlib html.parser — no BeautifulSoup.
    """
    parser = LinkTextExtractor(base_url)
    try:
        parser.feed(html)
    except Exception:
        pass  # Tolerate malformed HTML
    return parser.title.strip(), parser.get_text(), parser.links
