"""
SQLite persistence layer.

Why SQLite + WAL?
  - WAL (Write-Ahead Logging) mode allows concurrent readers and a single writer.
  - The indexer writes new pages while the searcher reads — they don't block each other.
  - This is the key to "search while indexing is active" requirement.
  - No external DB setup needed — just a file on disk.

Threading model:
  - ONE write connection shared across all threads, protected by _write_lock
  - Each read operation creates its OWN connection (WAL allows unlimited concurrent reads)
  - This pattern gives us safe concurrent access without connection pooling complexity
"""

import json
import math
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path("crawler_data.db")


def get_connection(path: Path = DB_PATH) -> sqlite3.Connection:
    """Create a new SQLite connection with WAL mode enabled.

    Key PRAGMAs:
    - journal_mode=WAL: enables concurrent read/write (core requirement)
    - synchronous=NORMAL: faster writes (safe with WAL — data survives OS crash)
    - busy_timeout=5000: wait up to 5s for locks instead of failing immediately
    """
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection):
    """Create tables if they don't exist.

    Schema:
    - pages: crawled page content (url, title, body, links)
    - crawl_jobs: job metadata (origin, depth, status, counters)
    - frontier: pending URLs for resumability (persisted queue state)
    - inverted_index: token → URL mapping with TF scores (the search index)
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pages (
            url TEXT PRIMARY KEY,
            title TEXT,
            body_text TEXT,
            links_json TEXT,
            crawl_job_id INTEGER,
            depth INTEGER,
            crawled_at REAL
        );

        CREATE TABLE IF NOT EXISTS crawl_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            origin TEXT NOT NULL,
            max_depth INTEGER NOT NULL,
            status TEXT DEFAULT 'running',
            pages_crawled INTEGER DEFAULT 0,
            pages_queued INTEGER DEFAULT 0,
            created_at REAL,
            finished_at REAL
        );

        CREATE TABLE IF NOT EXISTS frontier (
            url TEXT NOT NULL,
            depth INTEGER NOT NULL,
            crawl_job_id INTEGER NOT NULL,
            PRIMARY KEY (url, crawl_job_id)
        );

        CREATE TABLE IF NOT EXISTS inverted_index (
            token TEXT NOT NULL,
            url TEXT NOT NULL,
            tf REAL NOT NULL,
            field TEXT DEFAULT 'body',
            PRIMARY KEY (token, url, field)
        );

        CREATE INDEX IF NOT EXISTS idx_inverted_token ON inverted_index(token);
        CREATE INDEX IF NOT EXISTS idx_pages_job ON pages(crawl_job_id);
    """)
    conn.commit()


class Storage:
    """Thread-safe storage layer wrapping SQLite.

    Concurrency pattern:
    - Single _write_conn protected by _write_lock (SQLite allows 1 writer)
    - Each read creates a fresh connection via _read_conn() (WAL allows N readers)
    - Readers never block the writer, writer never blocks readers
    """

    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self._write_conn = get_connection(path)
        self._write_lock = threading.Lock()  # Serialize all write operations
        init_db(self._write_conn)

    def _read_conn(self) -> sqlite3.Connection:
        """Create a new read connection. Each call gets its own connection
        so multiple search queries can run concurrently without blocking."""
        return get_connection(self.path)

    # ── Crawl Jobs ──

    def create_job(self, origin: str, max_depth: int) -> int:
        """Insert a new crawl job record and return its ID."""
        with self._write_lock:
            cur = self._write_conn.execute(
                "INSERT INTO crawl_jobs (origin, max_depth, created_at) VALUES (?, ?, ?)",
                (origin, max_depth, time.time()),
            )
            self._write_conn.commit()
            return cur.lastrowid

    def update_job_counts(self, job_id: int, crawled: int, queued: int):
        """Update live crawl/queue counters for a running job."""
        with self._write_lock:
            self._write_conn.execute(
                "UPDATE crawl_jobs SET pages_crawled=?, pages_queued=? WHERE id=?",
                (crawled, queued, job_id),
            )
            self._write_conn.commit()

    def finish_job(self, job_id: int, status: str = "completed"):
        """Mark a crawl job as finished with given status."""
        with self._write_lock:
            self._write_conn.execute(
                "UPDATE crawl_jobs SET status=?, finished_at=? WHERE id=?",
                (status, time.time(), job_id),
            )
            self._write_conn.commit()

    def get_jobs(self) -> list[dict]:
        """Return all crawl jobs, most recent first."""
        conn = self._read_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM crawl_jobs ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_job(self, job_id: int) -> dict | None:
        """Return a single crawl job by ID, or None if not found."""
        conn = self._read_conn()
        try:
            row = conn.execute(
                "SELECT * FROM crawl_jobs WHERE id=?", (job_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def cancel_job(self, job_id: int):
        """Mark a job as cancelled and clear its saved frontier."""
        with self._write_lock:
            self._write_conn.execute(
                "UPDATE crawl_jobs SET status='cancelled', finished_at=? WHERE id=?",
                (time.time(), job_id),
            )
            self._write_conn.execute(
                "DELETE FROM frontier WHERE crawl_job_id=?", (job_id,)
            )
            self._write_conn.commit()

    # ── Pages ──

    def page_exists(self, url: str) -> bool:
        """Check whether a URL has already been indexed."""
        conn = self._read_conn()
        try:
            row = conn.execute(
                "SELECT 1 FROM pages WHERE url=?", (url,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def save_page(self, url: str, title: str, body_text: str,
                  links: list[str], job_id: int, depth: int):
        """Persist a crawled page (upsert by URL)."""
        with self._write_lock:
            self._write_conn.execute(
                """INSERT OR REPLACE INTO pages
                   (url, title, body_text, links_json, crawl_job_id, depth, crawled_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (url, title, body_text, json.dumps(links), job_id, depth, time.time()),
            )
            self._write_conn.commit()

    def get_pages_by_job(self, job_id: int, limit: int = 100, offset: int = 0) -> dict:
        """Return paginated list of pages crawled by a specific job."""
        conn = self._read_conn()
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM pages WHERE crawl_job_id=?", (job_id,)
            ).fetchone()[0]

            rows = conn.execute(
                "SELECT url, title, depth, crawled_at FROM pages "
                "WHERE crawl_job_id=? ORDER BY crawled_at DESC LIMIT ? OFFSET ?",
                (job_id, limit, offset),
            ).fetchall()

            return {
                "pages": [
                    {
                        "url": r["url"],
                        "title": r["title"] or "",
                        "depth": r["depth"],
                        "crawled_at": r["crawled_at"],
                    }
                    for r in rows
                ],
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        finally:
            conn.close()

    def total_pages(self) -> int:
        """Return total number of indexed pages."""
        conn = self._read_conn()
        try:
            return conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        finally:
            conn.close()

    # ── Inverted Index ──

    def save_index_entries(self, entries: list[tuple[str, str, float, str]]):
        """Save batch of (token, url, tf, field) entries."""
        with self._write_lock:
            self._write_conn.executemany(
                "INSERT OR REPLACE INTO inverted_index (token, url, tf, field) VALUES (?, ?, ?, ?)",
                entries,
            )
            self._write_conn.commit()

    def search(self, tokens: list[str], limit: int = 50, offset: int = 0) -> dict:
        """Search the inverted index using TF-IDF scoring.

        TF-IDF algorithm:
        1. For each query token, compute IDF = log(total_docs / docs_containing_token)
           → Rare words get higher IDF (more discriminating)
           → Common words get lower IDF (less useful for ranking)
        2. For each matching document: score += TF × IDF × weight
           → TF comes from the inverted index (precomputed at index time)
           → weight = 3.0 for title matches, 1.0 for body matches
        3. Sort all matching docs by total score, then paginate

        Returns {results: [...], total: int, limit: int, offset: int}.
        """
        if not tokens:
            return {"results": [], "total": 0, "limit": limit, "offset": offset}

        conn = self._read_conn()
        try:
            total_docs = max(1, conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0])

            # Get document frequency for each token
            placeholders = ",".join("?" for _ in tokens)
            df_rows = conn.execute(
                f"SELECT token, COUNT(DISTINCT url) as df FROM inverted_index "
                f"WHERE token IN ({placeholders}) GROUP BY token",
                tokens,
            ).fetchall()
            df_map = {row["token"]: row["df"] for row in df_rows}

            # Precompute IDF for each token
            idf_map: dict[str, float] = {}
            for token in tokens:
                df = df_map.get(token, 0)
                if df > 0:
                    idf_map[token] = math.log(total_docs / df)

            # Score each document
            scores: dict[str, float] = {}
            for token, idf in idf_map.items():
                rows = conn.execute(
                    "SELECT url, tf, field FROM inverted_index WHERE token=?",
                    (token,),
                ).fetchall()
                for row in rows:
                    weight = 3.0 if row["field"] == "title" else 1.0
                    scores[row["url"]] = scores.get(row["url"], 0) + row["tf"] * idf * weight

            if not scores:
                return {"results": [], "total": 0, "limit": limit, "offset": offset}

            # Sort by score, then paginate
            sorted_urls = sorted(scores, key=scores.get, reverse=True)
            total_results = len(sorted_urls)
            page_urls = sorted_urls[offset:offset + limit]

            # Get page metadata
            results = []
            for url in page_urls:
                page = conn.execute(
                    "SELECT p.url, p.title, p.depth, p.crawl_job_id, j.origin "
                    "FROM pages p JOIN crawl_jobs j ON p.crawl_job_id = j.id "
                    "WHERE p.url=?",
                    (url,),
                ).fetchone()
                if page:
                    results.append({
                        "relevant_url": page["url"],
                        "origin_url": page["origin"],
                        "depth": page["depth"],
                        "title": page["title"],
                        "score": round(scores[url], 4),
                    })
            return {
                "results": results,
                "total": total_results,
                "limit": limit,
                "offset": offset,
            }
        finally:
            conn.close()

    # ── Frontier (for resumability) ──

    def save_frontier(self, items: list[tuple[str, int, int]]):
        """Save frontier items: (url, depth, crawl_job_id)."""
        with self._write_lock:
            self._write_conn.executemany(
                "INSERT OR IGNORE INTO frontier (url, depth, crawl_job_id) VALUES (?, ?, ?)",
                items,
            )
            self._write_conn.commit()

    def load_frontier(self, job_id: int) -> list[tuple[str, int]]:
        """Load saved frontier for a job."""
        conn = self._read_conn()
        try:
            rows = conn.execute(
                "SELECT url, depth FROM frontier WHERE crawl_job_id=?", (job_id,)
            ).fetchall()
            return [(row["url"], row["depth"]) for row in rows]
        finally:
            conn.close()

    def clear_frontier(self, job_id: int):
        """Remove all frontier entries for a completed/cancelled job."""
        with self._write_lock:
            self._write_conn.execute(
                "DELETE FROM frontier WHERE crawl_job_id=?", (job_id,)
            )
            self._write_conn.commit()

    def get_visited_urls(self, job_id: int) -> set[str]:
        """Get all URLs already crawled for a job."""
        conn = self._read_conn()
        try:
            rows = conn.execute(
                "SELECT url FROM pages WHERE crawl_job_id=?", (job_id,)
            ).fetchall()
            return {row["url"] for row in rows}
        finally:
            conn.close()

    def close(self):
        self._write_conn.close()
