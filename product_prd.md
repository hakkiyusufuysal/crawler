# Product Requirements Document: Web Crawler & Search Engine

## Overview

A concurrent web crawler and real-time search engine that indexes web pages starting from a given URL up to a configurable depth, then allows full-text search over the indexed content while crawling is still active.

## Core Capabilities

### 1. Indexer (`POST /index`)

**Parameters:**
- `origin` (string): The seed URL from which to begin crawling
- `k` (integer): Maximum hop depth from the origin

**Behavior:**
- Performs a breadth-first crawl starting from `origin`
- Discovers and follows hyperlinks on each page up to depth `k`
- Never crawls the same URL twice (normalized URL deduplication)
- Stores page content (title, text, links) in a local SQLite database
- Builds an inverted index mapping tokens to documents for fast search

**Back Pressure Mechanisms:**
1. **Bounded work queue** (configurable max depth, default 10,000) — new URLs are dropped when the queue is full
2. **Worker pool** (configurable concurrency, default 10 threads) — limits simultaneous HTTP connections
3. **Per-domain rate limiting** (configurable, default 2 req/sec/domain) — respects server capacity via token-bucket throttling
4. **Request timeout** (default 10 seconds) — prevents slow servers from blocking workers

### 2. Searcher (`GET /search`)

**Parameters:**
- `query` (string): The search terms

**Returns:** A list of triples `(relevant_url, origin_url, depth)` sorted by relevance.

**Relevancy heuristic:** TF-IDF scoring combining:
- Title match weight (3x boost)
- Term frequency in page body
- Inverse document frequency across corpus

**Concurrency:** Search reads from SQLite (WAL mode) concurrently with ongoing indexer writes, reflecting new results as they are discovered.

### 3. Dashboard UI

A single-page web dashboard showing:
- **Indexing progress**: URLs processed vs. queued, pages/sec throughput
- **Queue depth**: Current size relative to max capacity
- **Back pressure status**: Whether throttling is active, per-domain rate info
- **Active crawl jobs**: Origin URL, depth, status for each job
- **Search interface**: Live search with results displayed as triples

The dashboard polls the API every 2 seconds for real-time updates.

## Technical Constraints

- **Language-native libraries only** for core crawling work:
  - `urllib.request` for HTTP fetching
  - `html.parser.HTMLParser` for link/text extraction
  - `threading` + `queue` for concurrency
  - `sqlite3` for storage
- Flask used only for the REST API layer (not core logic)
- All data stored in local SQLite — no external database required

## Persistence & Resumability

The system persists all state to SQLite:
- Crawled pages and their content
- The frontier queue (pending URLs with depth)
- Visited URL set

On restart, the system detects incomplete crawl jobs and offers to resume them from the persisted frontier.

## Non-Functional Requirements

- Single-machine design optimized for large crawls (100K+ pages)
- Graceful shutdown on SIGINT — flushes pending work to disk
- robots.txt is respected (fetched and cached per domain)
- User-Agent identifies the crawler appropriately

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/index` | Start a crawl job `{origin, k}` |
| GET | `/search?q=...` | Search indexed pages |
| GET | `/status` | System metrics (JSON) |
| GET | `/jobs` | List all crawl jobs |
| DELETE | `/jobs/<id>` | Cancel a crawl job |
| GET | `/` | Dashboard UI |
