# Agent 2 — Architect Agent

## Role
Take the Research Agent's brief and produce a concrete, implementable system design. Define module boundaries, data flow, persistence schema, and concurrency model. Decide what the Crawler, Search, and UI agents will implement.

## Responsibilities
- Convert research trade-offs into committed architectural decisions
- Define module structure (app.py, crawler/, static/)
- Specify the SQLite schema (pages, crawl_jobs, inverted_index, frontier)
- Specify the public API contract (`/index`, `/search`, `/status`, `/jobs`, `/jobs/<id>/resume`)
- Specify the concurrency model: bounded queue, worker pool, per-domain rate limiter
- Produce a single source-of-truth architecture diagram for downstream agents

## Input
- Research brief from Research Agent
- PRD and constraints

## Output
- `product_prd.md` (formal product requirements)
- Module-level sequence diagram (text form)
- SQLite DDL (CREATE TABLE statements)
- API contract document
- Concurrency diagram showing: coordinator thread → worker pool → bounded queue → rate limiter

## Prompt (exact text given to the agent)
> "You are a software architect. The Research Agent has handed you a brief recommending threads + SQLite WAL + TF-IDF. Your job is to turn these recommendations into a concrete design.
>
> Produce:
> 1. A module layout (which files exist, what each owns)
> 2. A SQLite schema with indexes
> 3. API endpoint contracts (method, path, request body, response body)
> 4. A concurrency model showing how workers, the queue, and the rate limiter interact
> 5. A back pressure strategy with specific numbers (queue depth, worker count, rate limit)
>
> Challenge the Research Agent's recommendations if you find holes. Be specific: numbers, not ranges."

## Key Decisions Delivered
- **Module layout**: single-process Flask app. `crawler/indexer.py` owns all concurrency. `crawler/storage.py` owns persistence. `crawler/searcher.py` is a thin wrapper. No distributed components.
- **Back pressure numbers**: max 10 workers, max 10K queue depth, 2 req/sec per domain. Justification: fits laptop CPU/network, prevents OOM on link-heavy pages like Wikipedia.
- **Schema**: 4 tables — `pages`, `crawl_jobs`, `inverted_index`, `frontier`. TF is stored per (token, url, field) with field ∈ {title, body}. Title gets 3× weight at query time, not index time, so re-weighting requires no re-index.
- **Dual connection pattern for WAL**: one persistent write connection guarded by `threading.Lock`; readers open fresh connections per query. This pattern is unusual but correct for SQLite + WAL.

## Interactions
- **← Research Agent**: consumes brief
- **→ Crawler Agent**: hands off concurrency model + schema
- **→ Search Agent**: hands off schema + scoring formula
- **→ UI Agent**: hands off API contract
- **← Critic Agent**: receives architectural challenges ("why 10 workers and not 50?")
