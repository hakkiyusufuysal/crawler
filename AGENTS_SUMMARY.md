# What Each Agent Did — Quick Summary

This is the one-page scannable overview. Full details for each agent are in [`/agents`](agents/).
Full workflow narrative is in [`multi_agent_workflow.md`](multi_agent_workflow.md).

---

## The 6 Agents

| # | Agent | What They Produced | Where in Repo |
|---|-------|-------------------|---------------|
| 1 | **Research Agent** | Brief comparing threads vs asyncio, SQLite vs file-based, TF-IDF vs BM25 → recommended **threads + SQLite WAL + TF-IDF** | Influenced `product_prd.md` |
| 2 | **Architect Agent** | System design, SQLite schema (4 tables), API contract, concurrency model with **10 workers / 10K queue / 2 req/s per domain** | `product_prd.md`, schema in `crawler/storage.py` |
| 3 | **Crawler Agent** | Worker pool + bounded queue, per-domain rate limiter, robots.txt cache, HTTP retry with exponential backoff (1s, 2s, 4s), SSL strict→lenient fallback, HTML parsing via stdlib, frontier persistence | `crawler/indexer.py`, `crawler/parser.py` |
| 4 | **Search Agent** | TF-IDF scoring (IDF at query time, title × 3.0 boost), pagination with `total` count, WAL-safe concurrent reads, shared tokenizer with Crawler Agent | `crawler/searcher.py`, `storage.search()` |
| 5 | **UI Agent** | Single-file vanilla HTML/CSS/JS dashboard — metrics, queue bar, job table, slide-in canvas for job details, paginated search, **diff-based DOM updates** (no flicker) | `static/index.html` |
| 6 | **Critic Agent** | Code review — found 7 issues (severity-graded), all fixed before submission | No code; critique drove the fixes below |

---

## What the Critic Agent Caught (All Fixed)

| # | Severity | Issue | Fixed By |
|---|----------|-------|----------|
| 1 | **major** | SSL verification was disabled by default | Crawler Agent — now strict, lenient fallback only on cert errors |
| 2 | **major** | No retry on HTTP 429 / 5xx | Crawler Agent — 3 retries with exponential backoff |
| 3 | **major** | UI flickered from full `innerHTML` replacement every 2s | UI Agent — diff-based updates |
| 4 | **blocker** | `crawler_data.db` was committed to git (contained real user crawl data) | Added to `.gitignore`, replaced with sample DB |
| 5 | **minor** | `import math` inside scoring loop | Search Agent — hoisted to module top |
| 6 | **minor** | Search returned `list[dict]` with no `total` — broken pagination | Search Agent — now `{results, total, limit, offset}` |
| 7 | **minor** | `/status` and `/jobs` had no try/except | Added graceful 500 handlers |

---

## How Agents Communicated

Agents never called each other directly. The **human was the orchestrator**:

```
Human → Agent A → (output) → Human reviews → Human → Agent B
```

Why human-mediated instead of autonomous?
- **Auditable** — every decision visible
- **Cost-controlled** — no runaway loops
- **Scope-controlled** — drift caught at each handoff

---

## Final Decisions the Human Made

- **Threads over asyncio** — language-native constraint won over Critic Agent's scaling concern
- **SQLite over PostgreSQL** — localhost-only constraint
- **Dashboard over CLI** — better for demo
- **Sample DB shipped in repo** — reviewers can search immediately without crawling first
- **Shipped with the "materialize all scores in Python" bottleneck** — out of scope for this exercise

---

## If You Read One Document

Read [`multi_agent_workflow.md`](multi_agent_workflow.md) — it's the long-form story of how these 6 agents produced this codebase.
