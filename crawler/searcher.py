"""
Search engine that queries the inverted index.

This is a thin wrapper around Storage.search(). We keep it separate for
separation of concerns — if we later swap SQLite for Elasticsearch,
only this module needs to change. The rest of the system stays the same.

Supports concurrent search while indexing is active:
  - SQLite WAL mode allows readers (search) and writer (indexer) simultaneously
  - Each search query gets its own read connection — no contention
  - Newly indexed pages are visible to search immediately after commit
"""

from .storage import Storage
from .indexer import tokenize


class Searcher:
    """Search over indexed pages using TF-IDF scoring."""

    def __init__(self, storage: Storage):
        self.storage = storage

    def search(self, query: str, limit: int = 50, offset: int = 0) -> dict:
        """Search indexed pages for the given query.

        Pipeline:
        1. Tokenize the query (same tokenizer used during indexing)
        2. Look up tokens in the inverted index
        3. Score documents using TF-IDF with title boost (3x)
        4. Return paginated results sorted by relevancy

        Returns dict with:
          - results: list of {relevant_url, origin_url, depth, title, score}
          - total: total matching results (for pagination)
          - limit: page size
          - offset: current page offset
        """
        tokens = tokenize(query)
        if not tokens:
            return {"results": [], "total": 0, "limit": limit, "offset": offset}
        return self.storage.search(tokens, limit=limit, offset=offset)
