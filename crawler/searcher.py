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

    def search(self, query: str, limit: int = 50, offset: int = 0) -> dict:
        """
        Search indexed pages for the given query.

        Returns dict with:
          - results: list of {relevant_url, origin_url, depth, title, score}
          - total: total matching results
          - limit: page size
          - offset: current offset
        """
        tokens = tokenize(query)
        if not tokens:
            return {"results": [], "total": 0, "limit": limit, "offset": offset}
        return self.storage.search(tokens, limit=limit, offset=offset)
