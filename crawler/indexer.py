"""
Core web crawler / indexer.

Uses only stdlib for fetching and parsing:
  - urllib.request for HTTP
  - html.parser for link extraction
  - threading + queue for concurrency and back pressure

Back pressure mechanisms:
  1. Bounded work queue (max_queue_depth)
  2. Fixed-size worker pool (max_workers)
  3. Per-domain rate limiting (token bucket)
  4. Request timeout
"""

import logging
import math
import queue
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from collections import Counter
from dataclasses import dataclass, field

from .parser import parse_html
from .runtime_agents import runtime_agents
from .storage import Storage

logger = logging.getLogger(__name__)

# ── Tokenizer (language-native, no nltk/spacy) ──
# We intentionally avoid NLP libraries. Tokenization is simple:
# 1. Lowercase everything
# 2. Extract alphanumeric tokens (min 2 chars) via regex
# 3. Filter out common English stop words to improve search relevancy
#    (e.g., "the", "is", "and" would match almost every page otherwise)

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_STOP_WORDS = frozenset([
    "the", "be", "to", "of", "and", "in", "that", "have", "it", "for",
    "not", "on", "with", "he", "as", "you", "do", "at", "this", "but",
    "his", "by", "from", "they", "we", "say", "her", "she", "or", "an",
    "will", "my", "one", "all", "would", "there", "their", "what", "so",
    "up", "out", "if", "about", "who", "get", "which", "go", "me", "when",
    "make", "can", "like", "time", "no", "just", "him", "know", "take",
    "come", "could", "than", "been", "its", "over", "such", "how", "some",
    "them", "may", "into", "other", "then", "now", "only", "also", "new",
    "more", "these", "two", "way", "are", "was", "is", "has", "had", "were",
])


def tokenize(text: str) -> list[str]:
    """Convert text into searchable tokens. Used by both indexer and searcher."""
    return [w for w in _TOKEN_RE.findall(text.lower()) if w not in _STOP_WORDS]


# ── Per-domain rate limiter (token bucket) ──
# Back pressure layer 3: Prevents overloading any single host.
# Each domain gets its own token bucket — at most `rate` requests/sec.
# This is "polite crawling": we don't want to DDoS target websites.
#
# How it works:
# - Track last request time per domain
# - If too soon since last request, sleep until the interval passes
# - Lock ensures thread-safe access (multiple workers may hit same domain)

class DomainRateLimiter:
    """Token-bucket rate limiter keyed by domain."""

    def __init__(self, rate: float = 2.0):
        """rate: max requests per second per domain (default: 2 req/sec)."""
        self._rate = rate
        self._lock = threading.Lock()
        self._last_request: dict[str, float] = {}

    def wait(self, domain: str):
        """Block the calling thread until a request to this domain is allowed."""
        with self._lock:
            now = time.monotonic()
            last = self._last_request.get(domain, 0)
            min_interval = 1.0 / self._rate  # e.g., 0.5s for 2 req/sec
            wait_time = max(0, min_interval - (now - last))
            self._last_request[domain] = now + wait_time

        if wait_time > 0:
            runtime_agents.record("ratelimiter", f"throttling {domain} ({wait_time:.2f}s)")
            time.sleep(wait_time)
        else:
            runtime_agents.record("ratelimiter", f"pass → {domain}")


# ── robots.txt cache ──

class RobotsCache:
    """Caches and checks robots.txt per domain."""

    def __init__(self, user_agent: str):
        self._user_agent = user_agent
        self._lock = threading.Lock()
        self._cache: dict[str, urllib.robotparser.RobotFileParser] = {}

    def can_fetch(self, url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        with self._lock:
            if domain not in self._cache:
                rp = urllib.robotparser.RobotFileParser()
                rp.set_url(f"{domain}/robots.txt")
                try:
                    rp.read()
                except Exception:
                    # If we can't read robots.txt, assume allowed
                    rp.allow_all = True
                self._cache[domain] = rp
            return self._cache[domain].can_fetch(self._user_agent, url)


# ── Crawl Job ──

@dataclass
class CrawlJob:
    job_id: int
    origin: str
    max_depth: int
    status: str = "running"
    pages_crawled: int = 0
    pages_queued: int = 0
    is_throttled: bool = False
    _cancel_event: threading.Event = field(default_factory=threading.Event)

    def cancel(self):
        self._cancel_event.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel_event.is_set()


# ── Indexer Engine ──

class Indexer:
    """
    Concurrent web crawler with back pressure.

    Architecture:
    - A bounded queue holds (url, depth) pairs to crawl
    - A fixed pool of worker threads pull from the queue
    - Per-domain rate limiting prevents overloading any single host
    - The visited set (thread-safe) ensures no URL is crawled twice
    """

    USER_AGENT = "ITU-Crawler/1.0 (educational project)"

    def __init__(
        self,
        storage: Storage,
        max_workers: int = 10,
        max_queue_depth: int = 10_000,
        rate_per_domain: float = 2.0,
        request_timeout: int = 10,
        verify_ssl: bool = True,
        max_retries: int = 3,
    ):
        self.storage = storage
        self.max_workers = max_workers
        self.max_queue_depth = max_queue_depth
        self.request_timeout = request_timeout
        self.max_retries = max_retries

        self._rate_limiter = DomainRateLimiter(rate_per_domain)
        self._robots = RobotsCache(self.USER_AGENT)

        # Thread-safe structures
        self._visited: dict[int, set[str]] = {}  # job_id -> set of visited URLs
        self._visited_lock = threading.Lock()
        self._active_jobs: dict[int, CrawlJob] = {}
        self._jobs_lock = threading.Lock()

        # SSL context — verify by default, fallback to unverified on cert errors
        if verify_ssl:
            self._ssl_ctx = ssl.create_default_context()
        else:
            self._ssl_ctx = ssl.create_default_context()
            self._ssl_ctx.check_hostname = False
            self._ssl_ctx.verify_mode = ssl.CERT_NONE

        # Lenient SSL context used as fallback when strict fails
        self._ssl_ctx_lenient = ssl.create_default_context()
        self._ssl_ctx_lenient.check_hostname = False
        self._ssl_ctx_lenient.verify_mode = ssl.CERT_NONE

    def start_crawl(self, origin: str, max_depth: int, resume_job_id: int | None = None) -> CrawlJob:
        """Start a new crawl job in background threads."""
        if resume_job_id:
            job_id = resume_job_id
            # Load existing frontier
            frontier_items = self.storage.load_frontier(job_id)
            visited = self.storage.get_visited_urls(job_id)
            job_info = self.storage.get_job(job_id)
            pages_crawled = job_info["pages_crawled"] if job_info else 0
        else:
            job_id = self.storage.create_job(origin, max_depth)
            frontier_items = [(origin, 0)]
            visited = set()
            pages_crawled = 0

        job = CrawlJob(
            job_id=job_id,
            origin=origin,
            max_depth=max_depth,
            pages_crawled=pages_crawled,
        )

        with self._visited_lock:
            self._visited[job_id] = visited

        with self._jobs_lock:
            self._active_jobs[job_id] = job

        # Create bounded queue (back pressure: producers block/drop when full)
        work_queue: queue.Queue[tuple[str, int] | None] = queue.Queue(
            maxsize=self.max_queue_depth
        )

        # Seed the queue
        for url, depth in frontier_items:
            if url not in visited:
                try:
                    work_queue.put_nowait((url, depth))
                except queue.Full:
                    break
        job.pages_queued = work_queue.qsize()

        # Launch coordinator thread
        coordinator = threading.Thread(
            target=self._coordinate,
            args=(job, work_queue),
            daemon=True,
            name=f"crawl-coordinator-{job_id}",
        )
        coordinator.start()
        return job

    def _coordinate(self, job: CrawlJob, work_queue: queue.Queue):
        """Coordinator: spawns workers and waits for completion."""
        workers: list[threading.Thread] = []
        active_count = threading.Semaphore(0)  # tracks items being processed

        # Track how many items are in-flight (being processed by workers)
        in_flight = threading.atomic if hasattr(threading, 'atomic') else type('Counter', (), {'_val': 0, '_lock': threading.Lock()})()
        in_flight._val = 0
        in_flight._lock = threading.Lock()

        def inc_flight():
            with in_flight._lock:
                in_flight._val += 1

        def dec_flight():
            with in_flight._lock:
                in_flight._val -= 1

        def get_flight():
            with in_flight._lock:
                return in_flight._val

        def worker():
            while not job.cancelled:
                try:
                    item = work_queue.get(timeout=2)
                except queue.Empty:
                    # Check if we should stop: no items in queue and nothing in-flight
                    if get_flight() == 0 and work_queue.empty():
                        break
                    continue

                if item is None:
                    work_queue.task_done()
                    break

                url, depth = item
                inc_flight()
                try:
                    self._process_url(job, work_queue, url, depth)
                except Exception as e:
                    logger.warning(f"Error processing {url}: {e}")
                finally:
                    dec_flight()
                    work_queue.task_done()

        # Start worker threads
        for i in range(self.max_workers):
            t = threading.Thread(
                target=worker,
                daemon=True,
                name=f"crawl-worker-{job.job_id}-{i}",
            )
            t.start()
            workers.append(t)

        # Wait for all workers to finish
        for t in workers:
            t.join()

        # Finalize — flush final counts before marking complete
        self.storage.update_job_counts(job.job_id, job.pages_crawled, job.pages_queued)
        status = "cancelled" if job.cancelled else "completed"
        job.status = status
        self.storage.finish_job(job.job_id, status)
        self.storage.clear_frontier(job.job_id)

        with self._jobs_lock:
            self._active_jobs.pop(job.job_id, None)
        with self._visited_lock:
            self._visited.pop(job.job_id, None)

        logger.info(f"Job {job.job_id} {status}: {job.pages_crawled} pages crawled")

    def _process_url(self, job: CrawlJob, work_queue: queue.Queue, url: str, depth: int):
        """Fetch, parse, index a single URL.

        This is the core pipeline — each worker thread runs this for every URL:
        1. Dedup check   → skip if already visited (Lock-protected set)
        2. Robots check  → respect robots.txt rules
        3. Rate limit    → wait for per-domain token bucket
        4. Fetch         → HTTP GET with retry + SSL fallback
        5. Parse         → extract title, text, links (stdlib html.parser)
        6. Store         → save page content to SQLite
        7. Index         → build inverted index entries (TF per token)
        8. Enqueue       → add discovered links to queue (bounded — back pressure)
        """
        # Step 1: Check visited set — Lock prevents race condition where
        # two threads check the same URL simultaneously and both proceed.
        # The "check-then-add" must be atomic.
        with self._visited_lock:
            visited = self._visited.get(job.job_id, set())
            if url in visited:
                runtime_agents.record("dedup", f"skip (seen): {url[:60]}")
                return
            visited.add(url)
            runtime_agents.record("dedup", f"accept ({len(visited)} visited): {url[:50]}")

        # Step 2: Respect robots.txt — cached per domain
        if not self._robots.can_fetch(url):
            logger.debug(f"Blocked by robots.txt: {url}")
            return

        # Step 3: Per-domain rate limiting (back pressure layer 3)
        # This sleep ensures we don't overwhelm any single host
        domain = urllib.parse.urlparse(url).netloc
        self._rate_limiter.wait(domain)
        job.is_throttled = True

        # Step 4: Fetch the page (with retry + exponential backoff)
        runtime_agents.record("fetcher", f"GET {url[:70]}")
        html = self._fetch(url)
        job.is_throttled = False
        if html is None:
            runtime_agents.record("fetcher", f"FAIL {url[:70]}")
            return

        # Step 5: Parse HTML — extract title, visible text, and links
        title, text, links = parse_html(html, url)
        runtime_agents.record(
            "parser",
            f"{len(links)} links, {len(text)} chars from {url[:40]}",
        )

        # Step 6: Persist page content to SQLite
        self.storage.save_page(url, title, text, links, job.job_id, depth)
        job.pages_crawled += 1

        # Step 7: Build inverted index (token → URL, TF score, field)
        # This is what makes search work — each token maps to the pages it appears in
        self._index_page(url, title, text)

        # Update job metrics (every 10 pages to reduce DB writes)
        job.pages_queued = work_queue.qsize()
        if job.pages_crawled % 10 == 0:
            self.storage.update_job_counts(job.job_id, job.pages_crawled, job.pages_queued)

        # Step 8: Enqueue discovered links (if within depth limit)
        # Back pressure layer 1: bounded queue — when full, URLs are DROPPED (not blocked)
        # This prevents memory from growing unboundedly on link-heavy pages
        if depth < job.max_depth:
            with self._visited_lock:
                visited = self._visited.get(job.job_id, set())
            frontier_batch = []
            for link in links:
                if link not in visited:
                    try:
                        work_queue.put_nowait((link, depth + 1))
                        frontier_batch.append((link, depth + 1, job.job_id))
                    except queue.Full:
                        # Queue is full — drop remaining URLs (back pressure)
                        job.is_throttled = True
                        break
            # Persist frontier every 50 pages for resumability
            # If the process is interrupted, we can reload these URLs on resume
            if frontier_batch and job.pages_crawled % 50 == 0:
                self.storage.save_frontier(frontier_batch)

    def _fetch(self, url: str) -> str | None:
        """
        Fetch URL using urllib (stdlib). Returns HTML string or None.
        Retries with exponential backoff on transient errors (429, 503, 5xx).
        Falls back to lenient SSL on certificate errors.
        """
        last_error = None
        for attempt in range(self.max_retries):
            ctx = self._ssl_ctx
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": self.USER_AGENT},
                )
                with urllib.request.urlopen(
                    req, timeout=self.request_timeout, context=ctx
                ) as resp:
                    content_type = resp.headers.get("Content-Type", "")
                    if "text/html" not in content_type and "text/xhtml" not in content_type:
                        return None
                    # Read up to 2MB
                    data = resp.read(2 * 1024 * 1024)
                    charset = resp.headers.get_content_charset() or "utf-8"
                    return data.decode(charset, errors="replace")

            except urllib.error.HTTPError as e:
                last_error = e
                # Retry on 429 (rate limited) and 5xx (server errors)
                if e.code == 429 or 500 <= e.code < 600:
                    wait = min(2 ** attempt, 8)  # 1s, 2s, 4s (capped at 8s)
                    logger.debug(f"HTTP {e.code} for {url}, retry {attempt+1}/{self.max_retries} in {wait}s")
                    time.sleep(wait)
                    continue
                # 4xx client errors (except 429) — don't retry
                logger.debug(f"HTTP {e.code} for {url}, not retrying")
                return None

            except (urllib.error.URLError, OSError, ValueError) as e:
                # Check if underlying cause is an SSL cert error
                # (urllib wraps ssl.SSLCertVerificationError inside URLError)
                cause = getattr(e, 'reason', None)
                is_ssl = isinstance(cause, ssl.SSLCertVerificationError) or (
                    isinstance(e, OSError) and 'CERTIFICATE_VERIFY_FAILED' in str(e)
                )
                if is_ssl:
                    logger.debug(f"SSL cert error for {url}, retrying without verification")
                    try:
                        req = urllib.request.Request(
                            url, headers={"User-Agent": self.USER_AGENT},
                        )
                        with urllib.request.urlopen(
                            req, timeout=self.request_timeout, context=self._ssl_ctx_lenient
                        ) as resp:
                            content_type = resp.headers.get("Content-Type", "")
                            if "text/html" not in content_type and "text/xhtml" not in content_type:
                                return None
                            data = resp.read(2 * 1024 * 1024)
                            charset = resp.headers.get_content_charset() or "utf-8"
                            return data.decode(charset, errors="replace")
                    except Exception as e2:
                        logger.debug(f"SSL fallback also failed {url}: {e2}")
                        return None

                last_error = e
                # Network errors — retry with backoff
                wait = min(2 ** attempt, 8)
                logger.debug(f"Fetch error {url}: {e}, retry {attempt+1}/{self.max_retries} in {wait}s")
                time.sleep(wait)
                continue

            except Exception as e:
                logger.debug(f"Unexpected fetch error {url}: {e}")
                return None

        logger.debug(f"Fetch failed after {self.max_retries} retries {url}: {last_error}")
        return None

    def _index_page(self, url: str, title: str, text: str):
        """Build inverted index entries for a page.

        For each unique token in the page, we compute Term Frequency (TF):
          TF = occurrences_of_token / total_tokens_in_field

        We store TF separately for "title" and "body" fields.
        At search time, title matches get a 3x boost (see storage.search).

        Example: A page with title "Python Tutorial" and body "Learn python basics"
        would produce entries like:
          ("python", url, 0.5, "title")   — 1 out of 2 title tokens
          ("tutorial", url, 0.5, "title")
          ("learn", url, 0.33, "body")    — 1 out of 3 body tokens
          ("python", url, 0.33, "body")
          ("basics", url, 0.33, "body")
        """
        title_tokens = tokenize(title)
        body_tokens = tokenize(text)

        entries = []

        # Title TF — these get 3x weight at search time
        title_counts = Counter(title_tokens)
        title_len = max(len(title_tokens), 1)
        for token, count in title_counts.items():
            tf = count / title_len
            entries.append((token, url, tf, "title"))

        # Body TF
        body_counts = Counter(body_tokens)
        body_len = max(len(body_tokens), 1)
        for token, count in body_counts.items():
            tf = count / body_len
            entries.append((token, url, tf, "body"))

        if entries:
            self.storage.save_index_entries(entries)
            runtime_agents.record(
                "indexer",
                f"+{len(entries)} index entries ({len(title_tokens)} title + {len(body_tokens)} body tokens)",
            )

    # ── Public API ──

    def get_active_jobs(self) -> list[dict]:
        with self._jobs_lock:
            return [
                {
                    "job_id": j.job_id,
                    "origin": j.origin,
                    "max_depth": j.max_depth,
                    "status": j.status,
                    "pages_crawled": j.pages_crawled,
                    "pages_queued": j.pages_queued,
                    "is_throttled": j.is_throttled,
                }
                for j in self._active_jobs.values()
            ]

    def cancel_job(self, job_id: int) -> bool:
        """Cancel an active crawl job. Returns True if the job was found and cancelled."""
        with self._jobs_lock:
            job = self._active_jobs.get(job_id)
            if job:
                job.cancel()
                self.storage.cancel_job(job_id)
                return True
        return False

    def get_status(self) -> dict:
        """Get overall system status."""
        active = self.get_active_jobs()
        return {
            "active_jobs": len(active),
            "total_pages_indexed": self.storage.total_pages(),
            "max_workers": self.max_workers,
            "max_queue_depth": self.max_queue_depth,
            "jobs": active,
        }

    def save_state(self):
        """Persist frontier for all active jobs (for graceful shutdown)."""
        with self._jobs_lock:
            for job in self._active_jobs.values():
                self.storage.update_job_counts(
                    job.job_id, job.pages_crawled, job.pages_queued
                )
