# Web Crawler & Search Engine

**Demo:** [video link placeholder]

A concurrent web crawler and real-time search engine built with Python for Brightwave. The system crawls web pages from a seed URL up to a configurable depth, indexes their content, and provides full-text search — even while crawling is still active.

## Pages

The application has a single-page dashboard with three main sections:

### Indexing Panel
Allows users to create crawler jobs with a given origin URL and depth. When the user clicks "Start Indexing", a thread pool is spawned to begin crawling the initial page at the specified depth. After creating a crawler, users can see its status (running, completed, cancelled) in the jobs table below. Each job shows real-time metrics: pages crawled, queue depth, and available actions (Cancel/Resume). Clicking on any job opens a live view showing all URLs discovered by that specific crawl.

### System Metrics Panel
Displays real-time system state using 2-second polling:
- **Total Pages Indexed**: cumulative count across all jobs
- **Active Jobs**: number of currently running crawl jobs
- **Worker Threads**: size of the thread pool
- **Queue Depth**: visual progress bar showing current queue fill vs. maximum capacity (back pressure indicator)
- **Throttle Status**: whether rate limiting is actively slowing down requests (Idle / Normal / Active)

### Search Panel
Allows users to search indexed content with a query. The query is tokenized, and results are ranked using TF-IDF scoring with title boost. Results show the URL, origin URL, depth, title, and relevancy score. Paginated with Previous/Next navigation. Search works while indexing is still active — new pages become searchable immediately after being indexed.

## Crawler Job (Core Component)

This is the core of the project. It receives a URL and depth parameter and manages the entire crawl lifecycle:

1. **Initialization**: A new `CrawlJob` is created with a unique ID. The job status, origin URL, and depth are persisted to SQLite immediately.

2. **Thread Pool Dispatch**: A fixed pool of worker threads (default: 10) is launched. Each worker pulls `(url, depth)` pairs from a bounded `queue.Queue` (max 10,000 items).

3. **URL Processing**: For each URL, the worker:
   - Checks the visited set (protected by `threading.Lock` to prevent race conditions)
   - Checks `robots.txt` compliance (cached per domain)
   - Waits for the per-domain rate limiter (token bucket, max 2 req/sec/domain)
   - Fetches the page using `urllib.request` with SSL verification (falls back to lenient mode on cert errors)
   - Retries on HTTP 429/5xx with exponential backoff (1s, 2s, 4s — up to 3 attempts)
   - Parses HTML using stdlib `html.parser` to extract title, body text, and links
   - Stores the page content in SQLite
   - Builds inverted index entries (token → URL, TF score, field)
   - Enqueues discovered links at `depth + 1` (if within max depth)

4. **Back Pressure**: Three layers prevent the system from being overwhelmed:
   - **Bounded queue**: When full, new URLs are dropped (not blocking)
   - **Fixed worker pool**: Limits concurrent HTTP connections
   - **Per-domain rate limiter**: Token-bucket throttling ensures no single domain is overloaded

5. **Frontier Persistence**: Every 50 pages, the pending URL frontier is saved to SQLite. This allows resuming a cancelled or interrupted crawl without starting from scratch.

6. **Completion**: When the queue is empty and all workers are idle, the job status is updated to "completed".

## Search (TF-IDF Scoring)

When a user enters a query, each word is tokenized and looked up in the inverted index stored in SQLite:

1. **Tokenization**: The query is lowercased and split into alphanumeric tokens.
2. **Document Frequency**: For each token, we count how many documents contain it.
3. **IDF Calculation**: `IDF = log(total_docs / doc_frequency)` — common words (e.g., "the") get low scores, rare words get high scores.
4. **TF-IDF Scoring**: For each matching document: `score += TF × IDF × weight`, where weight is 3.0 for title matches and 1.0 for body matches.
5. **Ranking**: Documents are sorted by total score and returned with pagination (configurable limit/offset).

Search runs on a separate SQLite read connection (WAL mode), so it never blocks the indexer's write operations. New pages become searchable the moment they are committed to the database.

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌────────────┐
│  Flask API   │────▶│   Indexer    │────▶│  SQLite DB │
│  + Dashboard │     │ (thread pool)│     │ (WAL mode) │
└──────┬──────┘     └──────────────┘     └─────┬──────┘
       │                                        │
       │            ┌──────────────┐            │
       └───────────▶│   Searcher   │◀───────────┘
                    │  (TF-IDF)    │
                    └──────────────┘
```

**Concurrency Model:**
- Worker threads pull URLs from a `queue.Queue` (thread-safe, bounded)
- `threading.Lock` protects the visited-URL set (prevents duplicate crawls)
- SQLite WAL mode allows concurrent reader (search) + writer (indexer)
- Graceful shutdown via SIGINT handler persists state to disk

## Quick Start

```bash
# Clone and enter the project
git clone https://github.com/hakkiyusufuysal/crawler.git && cd crawler

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies (only Flask — everything else is stdlib)
pip install -r requirements.txt

# Run the server
python app.py
```

Open **http://localhost:8090** in your browser.

## Usage

### Via Dashboard (recommended)
1. Enter a URL and depth in the "Start New Crawl" section
2. Watch real-time progress in the metrics panel (queue depth, throttle status)
3. Click on any job row to see all URLs discovered by that crawl
4. Search indexed content using the search box (works during active crawls)
5. Cancel a running job, then Resume it later — it picks up where it left off

### Via API

```bash
# Start a crawl
curl -X POST http://localhost:8090/index \
  -H 'Content-Type: application/json' \
  -d '{"origin": "https://example.com", "k": 2}'

# Search (with pagination)
curl 'http://localhost:8090/search?q=python+programming&limit=20&offset=0'

# System status
curl http://localhost:8090/status

# List jobs
curl http://localhost:8090/jobs

# Cancel a job
curl -X DELETE http://localhost:8090/jobs/1

# Resume a cancelled/interrupted job
curl http://localhost:8090/jobs/1/resume
```

## API Reference

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/index` | Start a crawl job. Body: `{"origin": "url", "k": depth}` |
| `GET` | `/search?q=...&limit=N&offset=N` | Search indexed pages. Returns `(relevant_url, origin_url, depth)` triples |
| `GET` | `/status` | System metrics: active jobs, queue depth, worker count |
| `GET` | `/jobs` | List all crawl jobs (active + completed) |
| `GET` | `/jobs/<id>` | Get details of a specific job |
| `GET` | `/jobs/<id>/pages` | Get all pages crawled by a specific job |
| `DELETE` | `/jobs/<id>` | Cancel a running crawl job |
| `GET` | `/jobs/<id>/resume` | Resume a previously cancelled/interrupted job |

## Search Response Format

```json
{
  "query": "web crawling",
  "count": 3,
  "total": 45,
  "limit": 20,
  "offset": 0,
  "results": [
    {
      "relevant_url": "https://example.com/crawling",
      "origin_url": "https://example.com",
      "depth": 1,
      "title": "Web Crawling Guide",
      "score": 2.4531
    }
  ]
}
```

## Project Structure

```
crawler/
├── app.py                 # Flask API server + entry point
├── crawler/
│   ├── __init__.py
│   ├── indexer.py         # Core crawler with thread pool + back pressure
│   ├── parser.py          # HTML parser (stdlib html.parser)
│   ├── searcher.py        # TF-IDF search engine
│   └── storage.py         # SQLite persistence layer (WAL mode)
├── static/
│   └── index.html         # Dashboard UI (single-page)
├── product_prd.md         # Product Requirements Document
├── recommendation.md      # Production deployment recommendations
├── requirements.txt       # Python dependencies (Flask only)
└── readme.md              # This file
```

## Design Decisions

- **Why threads over asyncio?** The `urllib` stdlib is synchronous. A thread pool with bounded queue provides natural back pressure without adding async complexity. For a single-machine crawler with 10 workers, thread overhead is minimal.
- **Why SQLite?** Zero-config, file-based, supports concurrent reads via WAL mode. Perfect for localhost and single-machine scale. The inverted index lives in SQLite tables rather than in-memory for persistence and resumability.
- **Why TF-IDF?** Simple, effective, and easy to reason about. Title matches get a 3x boost. No external ML dependencies needed.
- **Why stdlib HTML parser?** The assignment requires language-native functionality. `html.parser.HTMLParser` handles real-world HTML well enough for link and text extraction.
- **Why SSL fallback?** Many sites have certificate issues. The crawler first tries strict verification, then falls back to lenient mode — balancing security with practical crawling.

## Crawler Limitations

- Single-machine, single-process design — no distributed crawling
- Bounded to one write thread (SQLite limitation) — write throughput is capped
- No JavaScript rendering — SPA content is not captured
- No content deduplication (e.g., same article at different URLs)
- Rate limiter is per-process — restarting resets the rate state

## Requirements

- Python 3.10+
- Flask (the only non-stdlib dependency)

## License

MIT
