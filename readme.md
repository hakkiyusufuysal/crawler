# Web Crawler & Search Engine

A concurrent web crawler and real-time search engine built with Python. Indexes web pages from a seed URL up to a configurable depth, then provides full-text search over indexed content — even while crawling is still active.

## Features

- **Breadth-first crawling** from a seed URL to configurable depth `k`
- **Back pressure control**: bounded queue (10K default), worker pool (10 threads), per-domain rate limiting (2 req/sec)
- **Concurrent search**: search queries work while indexing is active (SQLite WAL mode)
- **TF-IDF relevancy**: title-boosted term frequency / inverse document frequency scoring
- **Real-time dashboard**: indexing progress, queue depth, throttle status, search interface
- **Resumable crawls**: persisted frontier allows resuming after interruption
- **Language-native**: uses only `urllib`, `html.parser`, `threading`, `sqlite3` for core work

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

**Back Pressure Mechanisms:**
1. **Bounded work queue** — URLs dropped when queue is full (configurable max depth)
2. **Fixed worker pool** — limits concurrent HTTP connections
3. **Per-domain rate limiter** — token-bucket throttling per hostname
4. **Request timeout** — prevents slow servers from blocking workers

**Concurrency Model:**
- Worker threads pull URLs from a `queue.Queue` (thread-safe, bounded)
- `threading.Lock` protects the visited-URL set
- SQLite WAL mode allows concurrent reader (search) + writer (indexer)
- Graceful shutdown via SIGINT handler persists state to disk

## Quick Start

```bash
# Clone and enter the project
git clone <repo-url> && cd crawler

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
2. Watch real-time progress in the metrics panel
3. Search indexed content using the search box

### Via API

```bash
# Start a crawl
curl -X POST http://localhost:8090/index \
  -H 'Content-Type: application/json' \
  -d '{"origin": "https://example.com", "k": 2}'

# Search
curl 'http://localhost:8090/search?q=python+programming'

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
| `GET` | `/search?q=...` | Search indexed pages. Returns `(relevant_url, origin_url, depth)` triples |
| `GET` | `/status` | System metrics: active jobs, queue depth, worker count |
| `GET` | `/jobs` | List all crawl jobs (active + completed) |
| `DELETE` | `/jobs/<id>` | Cancel a running crawl job |
| `GET` | `/jobs/<id>/resume` | Resume a previously cancelled/interrupted job |

## Search Response Format

```json
{
  "query": "web crawling",
  "count": 3,
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
- **Why SQLite?** Zero-config, file-based, supports concurrent reads via WAL mode. Perfect for localhost and single-machine scale. The inverted index lives in SQLite tables rather than in-memory for persistence.
- **Why TF-IDF?** Simple, effective, and easy to reason about. Title matches get a 3x boost. No external ML dependencies needed.
- **Why stdlib HTML parser?** The assignment requires language-native functionality. `html.parser.HTMLParser` handles real-world HTML well enough for link and text extraction.

## Requirements

- Python 3.10+
- Flask (for the web server — the only non-stdlib dependency)

## License

MIT
