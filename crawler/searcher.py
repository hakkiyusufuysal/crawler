"""
Search engine that queries the inverted index.
Supports concurrent search while indexing is active (SQLite WAL mode).
"""

from .storage import Storage
from .indexer import tokenize


class Searcher:
    """Search over indexed pages using TF-IDF scoring."""

    def __init__(self, storage: Storage):
        self.storage = storage

    def search(self, query: str, limit: int = 50) -> list[dict]:
        """
        Search indexed pages for the given query.

        Returns list of dicts with:
          - relevant_url: URL of the matching page
          - origin_url: origin URL of the crawl job that discovered it
          - depth: depth at which it was discovered
          - title: page title
          - score: relevancy score
        """
        tokens = tokenize(query)
        if not tokens:
            return []
        return self.storage.search(tokens, limit=limit)
