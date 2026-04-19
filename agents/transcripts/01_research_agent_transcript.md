# Research Agent — Real Transcript

**Agent:** Research Agent (subagent type: Explore, running on Claude Code)
**Date:** 2026-04-19

## Prompt Given

> You are the Research Agent in a multi-agent software development workflow. You are NOT writing code. You produce a research brief that will be handed to the Architect Agent.
>
> CONTEXT: The team is building a web crawler with search, running on a single machine (localhost). Constraints:
> - Must use Python standard library "to the greatest extent possible"
> - Must support back pressure
> - Must support concurrent search while indexing is active
> - Must be resumable after interruption
>
> YOUR TASK: Produce a research brief covering these 5 decisions. For each, list 2-3 alternatives with concrete trade-offs, then recommend one. Be opinionated. Cite specific properties (not vague claims).
>
> 1. Concurrency model (threads vs asyncio vs multiprocessing)
> 2. Storage backend (SQLite vs file-based JSON vs Redis vs LMDB)
> 3. Scoring algorithm (TF-IDF vs BM25 vs simple frequency)
> 4. Politeness mechanism (robots.txt, rate limiting approach)
> 5. Resumability pattern (checkpoint strategy)
>
> OUTPUT FORMAT: Write it as a memo TO the Architect Agent. Start with "RESEARCH BRIEF — To: Architect Agent, From: Research Agent". Use headings for each decision. End with a single-paragraph "Recommended stack" summary. 400-700 words total. Do not write code.

## Agent's Response (verbatim)

# RESEARCH BRIEF — To: Architect Agent, From: Research Agent

## 1. Concurrency Model

**Threads vs Asyncio vs Multiprocessing**

*Threads (threading module):*
Simplest path using stdlib. Native OS threads with the GIL mean CPU-bound parsing is serialized, but I/O-bound network calls release the lock. Fits our "standard library" constraint. Trade-off: Can't truly parallelize parsing; requires explicit locking for shared state (the index).

*Asyncio:*
Single-threaded, event-loop driven. No GIL contention. Trade-off: Requires async/await rewrite of all I/O code; stdlib urllib doesn't support async natively (requires third-party libraries). Harder to integrate blocking operations like disk writes.

*Multiprocessing:*
True parallelism via separate processes. Trade-off: Heavy memory overhead per process; inter-process communication is expensive (serialization via pickle); complicates resumability (each worker has its own state).

**Recommendation: Threads.** The GIL is acceptable here because network I/O dominates CPU work. We stay in stdlib, keep code simple, and can serialize index access with a threading.Lock. Back pressure is natural: if the queue fills, producers block.

---

## 2. Storage Backend

**SQLite vs File-based JSON vs Redis vs LMDB**

*SQLite:*
Embedded relational database, zero setup. ACID transactions guarantee resumability. Trade-off: Not a web search index engine—queries like "documents containing term X" require full table scans or explicit indexes. Single-writer limitation under contention (but acceptable for our single-machine constraint).

*File-based JSON:*
Minimal dependencies, human-readable. Trade-off: No transactions; partial writes on crash lose data. Resuming requires re-parsing entire files. Queries require loading all data into memory.

*Redis:*
Fast in-memory data structure server. Trade-off: Requires external process; persistence requires RDB/AOF tuning; not "standard library."

*LMDB:*
Embedded key-value store, BSD-licensed. ACID transactions, memory-mapped. Trade-off: Not stdlib; requires external binding; overkill unless we hit SQLite write contention.

**Recommendation: SQLite.** Native to Python's stdlib. We create two tables: `documents` (url, content, crawled_at) and `inverted_index` (term, document_id, frequency, position). Transactions ensure atomicity on resumption. Index queries can use `INNER JOIN` to find documents by term. Write contention is negligible on localhost.

---

## 3. Scoring Algorithm

**TF-IDF vs BM25 vs Simple Frequency**

*Simple Frequency:*
Count occurrences of search term in document. Trade-off: Heavily biased toward long documents; common words (the, and) dominate results. No discount for term frequency saturation.

*TF-IDF:*
Term frequency × inverse document frequency. Penalizes common terms. Trade-off: IDF requires corpus statistics; must recompute if corpus changes. Assumes documents are independent; no positional weighting.

*BM25:*
Probabilistic relevance model. Includes term saturation curve (diminishing returns after k1 occurrences) and field-length normalization. Trade-off: Requires tuning (k1, b parameters); more complex; stdlib doesn't include it—requires implementation.

**Recommendation: TF-IDF.** It's the industry standard for web search. We precompute IDF at index time (`log(total_docs / docs_with_term)`), then score at query time. Simple to implement in ~20 lines. BM25 is overkill for localhost scale; simple frequency loses too much signal on large documents.

---

## 4. Politeness Mechanism

**robots.txt + Rate Limiting Approach**

We must avoid hammering target servers. Two layers:

*robots.txt parsing:*
Fetch and parse robots.txt at each domain root. Respect Disallow rules per user-agent. Trade-off: Some sites don't publish it; parsing edge cases (e.g., wildcards) require careful regex.

*Rate limiting:*
Per-domain delay (e.g., 1 request per 2 seconds) or token bucket. Trade-off: Delay slows crawl; no delay risks blocking. Token bucket allows bursts but requires state tracking per domain.

**Recommendation: Synchronous robots.txt parsing + per-domain fixed delay (2 seconds).** Keep it simple. Parse robots.txt on first visit to a domain (cache the result in SQLite table `robots_cache`). Enforce a simple `time.sleep(2)` before each request to that domain. Thread-safe via domain-level locking. Respects the spirit of crawl politeness without complex state machines.

---

## 5. Resumability Pattern

**Checkpoint Strategy**

*Incremental state:*
Mark each URL as crawled/pending in the database. On resume, query `WHERE status = 'pending'` and restart. Trade-off: Requires careful state transitions (pending → crawling → crawled) to avoid race conditions on crash.

*Write-ahead logging:*
Log every action before executing (e.g., "about to crawl URL X"). On resume, replay unfinished actions. Trade-off: More complex; requires distinguishing partial writes.

**Recommendation: Incremental state in SQLite with transaction boundaries.** Add a `urls` table with columns `url, status (pending|crawled|failed), crawled_at`. Wrap each crawl in a transaction: set status to crawling, fetch and parse, insert documents and index terms, commit. On resume, any `crawling` status reverts to `pending`. This is simple, ACID-safe, and requires no separate log file.

---

## Recommended Stack

Use **Python threads** with a queue for back pressure. Store documents and the inverted index in **SQLite** with transactional integrity. Score results with **TF-IDF** (precomputed IDF, runtime scoring). Police crawling with **robots.txt parsing** and a simple per-domain 2-second delay. Achieve resumability via **incremental status tracking** in the database, reverting any partially-crawled URLs on restart. This stack stays within stdlib, remains maintainable, and handles concurrent search during indexing without external dependencies.

## Human's Decision

All 5 recommendations were accepted with one amendment: instead of a simple `time.sleep(2)` per domain, the final implementation uses a **token-bucket rate limiter** (see `DomainRateLimiter` in `crawler/indexer.py`) — rationale: natural support for bursty crawls within rate budgets, and the Architect Agent flagged `sleep(2)` as wasting thread capacity if we only have one URL in flight to that domain.

The incremental-status resumability recommendation was simplified to a dedicated `frontier` table (see `storage.py` — frontier persistence flushed every 50 pages). The URL state machine (pending→crawling→crawled) was collapsed because the `visited` set is held in-memory per-job and the frontier is the source of truth for "not yet crawled."
