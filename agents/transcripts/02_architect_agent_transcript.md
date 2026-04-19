# Architect Agent — Real Transcript

**Agent:** Architect Agent (subagent type: Explore, running on Claude Code)
**Date:** 2026-04-19

## Prompt Given

> You are the Architect Agent in a multi-agent software development workflow. You do NOT write code. You produce a concrete system design that downstream engineering agents will implement.
>
> INPUT: The Research Agent has handed you this brief (recommendations):
> - Concurrency: Python threads with queue for back pressure
> - Storage: SQLite (documents table + inverted_index table)
> - Scoring: TF-IDF with precomputed IDF
> - Politeness: robots.txt + per-domain 2-second delay
> - Resumability: incremental status tracking in SQLite
>
> YOUR TASK: Turn these recommendations into a concrete, implementable design. Challenge the Research Agent's recommendations where they have holes. Be specific — use NUMBERS, not ranges.

## Agent's Response (verbatim excerpt)

**Module Layout** (proposed):
```
crawler/
├── app.py                 # Flask routes
├── indexer.py             # TF-IDF scoring
├── crawler.py             # Fetcher + politeness
├── db.py                  # SQLite schema
├── queue_manager.py       # Thread pool, queue depth
└── config.py              # MAX_WORKERS=8, QUEUE_DEPTH=500
```

**Concurrency numbers:**
- MAX_WORKERS = 8
- MAX_QUEUE_DEPTH = 500
- RATE_PER_DOMAIN_SEC = 2.0
- REQUEST_TIMEOUT_SEC = 15
- MAX_RETRIES = 5

### Challenge 1 (to Research Agent): Sleep-based rate limiting is wasteful

> "You said 'per-domain 2-second delay,' but `time.sleep(2)` in a worker thread blocks the thread for 2 seconds, idling a pool slot. With only 8 workers, a single slow domain starves others."
>
> **Fix:** domain_state table + re-queue strategy. No thread sleeps; URLs from rate-limited domains loop back.

### Challenge 2: Status table vs frontier duplication

> "You suggested 'incremental status tracking' but did not specify where the frontier lives. Are pending URLs in the queue *and* the DB? They must be, but this creates synchronization risk: what if a worker crashes mid-fetch?"

### Challenge 3: IDF precomputation timing

> "'Precomputed IDF' assumes a fixed corpus. But the corpus grows as we crawl. Do we recalculate IDF retroactively? If we do, stored TF-IDF values become stale."
>
> **Fix:** Recalculate IDF after every 1,000 new indexed docs.

## Human's Decision

**Accepted with major revisions:**

1. **Module layout partially accepted.** We collapsed `crawler.py` + `queue_manager.py` + `config.py` into a single `indexer.py` — the split created too much inter-module state passing for a single-machine design. Final layout: `app.py`, `crawler/indexer.py`, `crawler/parser.py`, `crawler/storage.py`, `crawler/searcher.py`.

2. **Concurrency numbers overridden.** The Architect Agent proposed MAX_WORKERS=8, MAX_QUEUE_DEPTH=500. The human raised both to **MAX_WORKERS=10, MAX_QUEUE_DEPTH=10,000**. Rationale: 500 is too small for Wikipedia-scale link discovery (a single seed page can emit 500+ links, immediately tripping back pressure on the first crawl).

3. **Challenge 1 partially accepted.** Instead of "re-queue on rate limit," the final implementation uses a **token-bucket rate limiter** that blocks the worker briefly (typically <500ms) via `time.sleep`. Rationale: re-queuing creates an unbounded work-stealing cycle if all workers are bound to the same domain. The token-bucket bounds the wait time.

4. **Challenge 3 rejected.** We do NOT recalculate IDF on every 1000 docs — instead, IDF is computed at **query time** from current corpus stats. Rationale: keeps TF storage append-only (no UPDATE amplification), and IDF is cheap to compute on the fly (one SQL query per unique query token).

5. **Challenge 2 accepted.** A dedicated `frontier` table holds pending URLs per job, flushed every 50 pages. The in-memory queue is volatile; the frontier is durable.

6. **New schema simpler than proposed.** Instead of `documents.status` column + separate `frontier` table, we store page content in `pages`, the inverted index in `inverted_index`, job metadata in `crawl_jobs`, and pending URLs in `frontier`. No status state machine — visited is determined by `pages.url` existence.
