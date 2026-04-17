# Agent 3 — Crawler Agent

## Role
Implement the indexer — the code that actually crawls the web. Own everything inside `crawler/indexer.py`, `crawler/parser.py`, and the frontier persistence logic in `crawler/storage.py`.

## Responsibilities
- Implement the concurrent worker pool (threading)
- Implement the bounded queue-based back pressure
- Implement per-domain token-bucket rate limiting
- Implement robots.txt respect (cached per domain)
- Implement HTTP fetch with retry + exponential backoff
- Implement HTML parsing using only stdlib `html.parser`
- Implement URL normalization and deduplication (visited set with lock)
- Implement frontier persistence for resumability
- Implement graceful shutdown that saves state

## Input
- Architecture spec from Architect Agent
- SQLite schema

## Output
- `crawler/indexer.py` — Indexer class, DomainRateLimiter, RobotsCache, CrawlJob dataclass
- `crawler/parser.py` — LinkTextExtractor (HTMLParser subclass)
- Frontier methods in `crawler/storage.py`

## Prompt (exact text given to the agent)
> "You are a backend engineer. Implement the crawler given this architecture:
>
> - Thread pool of 10 workers
> - Bounded queue with max depth 10,000 (drop URLs when full)
> - Per-domain rate limit of 2 req/sec (token bucket)
> - robots.txt respect with caching
> - HTTP fetch via urllib with 3 retries + exponential backoff (1s, 2s, 4s)
> - SSL verification on, with lenient fallback on cert errors
> - Visited-URL deduplication using a set + threading.Lock
> - Persist frontier every 50 pages to enable resume
>
> Use ONLY Python stdlib for core logic. No requests, no BeautifulSoup, no aiohttp.
>
> Write production-quality code: proper error handling, logging, graceful shutdown. Avoid comments that describe WHAT the code does — only WHY."

## Key Decisions Delivered
- **Coordinator + worker pattern**: one coordinator thread spawns N workers, each worker pulls from the queue until empty AND in-flight counter is 0.
- **in-flight counter**: tracks URLs currently being processed (not yet in queue, not yet indexed) — prevents premature shutdown when queue is momentarily empty.
- **SSL fallback**: first attempts with strict cert verification; on `SSLCertVerificationError` (caught via `URLError.reason`), retries once with `CERT_NONE`. Logs the fallback so it's auditable.
- **Retry policy**: only retries on 429 and 5xx. 4xx client errors are NOT retried — they indicate a permanent problem.
- **Frontier persistence**: flushed every 50 pages, not every page. Trade-off between resume granularity and write amplification on SQLite.

## Interactions
- **← Architect Agent**: consumes spec
- **→ Search Agent**: calls `storage.save_index_entries()` from `_index_page()`; Search Agent owns the scoring side
- **← Critic Agent**: receives challenges about thread safety, SSL handling, retry logic
- **← QA/Testing (if enabled)**: receives bug reports
