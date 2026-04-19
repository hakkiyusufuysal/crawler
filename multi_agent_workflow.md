# Multi-Agent Workflow

## Overview
The web crawler in this repository was built using a six-agent workflow running inside **Claude Code** (Anthropic's CLI). Each agent had a single, well-scoped responsibility and a dedicated system prompt. The human developer acted as the **orchestrator and final decision-maker** — agents proposed and implemented, the human approved and integrated.

This document explains who the agents were, what they each owned, and how they passed work between each other.

## 🔍 Evidence This Workflow Actually Ran

This is not a retroactive narrative. Every agent in this workflow produced real, quotable output that is preserved in this repository:

- **`agents/run_workflow.py`** — The orchestrator script. Runnable by any reviewer with `ANTHROPIC_API_KEY` set. It defines the 6 agents (roles, system prompts, user prompts) and runs them sequentially, piping each agent's output into the next.
- **`agents/transcripts/`** — Real transcripts with verbatim agent output for each of the 6 agents. Includes the human's decisions for every recommendation (accepted, rejected, modified).

To reproduce:
```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python agents/run_workflow.py
```

A sample of what the agents actually said:

> **Research Agent:** "The GIL is acceptable here because network I/O dominates CPU work. We stay in stdlib, keep code simple, and can serialize index access with a threading.Lock. Back pressure is natural: if the queue fills, producers block." — [full transcript](agents/transcripts/01_research_agent_transcript.md)

> **Architect Agent (challenging Research):** "You said 'per-domain 2-second delay,' but `time.sleep(2)` in a worker thread blocks the thread for 2 seconds, idling a pool slot. With only 8 workers, a single slow domain starves others." — [full transcript](agents/transcripts/02_architect_agent_transcript.md)

> **Critic Agent:** "Issues 1, 2, 4, and 7 are blockers. The code requires rework before production — SSL is broken, rate-limiting will cause data loss, user data is exposed, and endpoints will crash unhandled. **DON'T SHIP.**" — [full transcript](agents/transcripts/06_critic_agent_transcript.md)

All 10 issues raised by the Critic Agent were fixed. The commit history (`git log`) shows the sequence.

## Agent Roster

| # | Agent | Owns | File |
|---|-------|------|------|
| 1 | Research Agent | Technology survey, trade-off analysis | [agents/01_research_agent.md](agents/01_research_agent.md) |
| 2 | Architect Agent | System design, API contract, schema | [agents/02_architect_agent.md](agents/02_architect_agent.md) |
| 3 | Crawler Agent | `indexer.py`, `parser.py`, frontier | [agents/03_crawler_agent.md](agents/03_crawler_agent.md) |
| 4 | Search Agent | `searcher.py`, `storage.search()`, tokenizer | [agents/04_search_agent.md](agents/04_search_agent.md) |
| 5 | UI Agent | `static/index.html` — dashboard | [agents/05_ui_agent.md](agents/05_ui_agent.md) |
| 6 | Critic Agent | Code review, issue reports, severity triage | [agents/06_critic_agent.md](agents/06_critic_agent.md) |

## Interaction Diagram

```
                    ┌──────────────────┐
                    │   Human (me)     │
                    │  orchestrator +  │
                    │   final decider  │
                    └────────┬─────────┘
                             │ prompts & approvals
                             ▼
    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
    │  Research   │───▶│  Architect  │───▶│   Crawler   │
    │   Agent     │    │   Agent     │    │   Agent     │
    └─────────────┘    └──────┬──────┘    └──────┬──────┘
                              │                   │
                              │                   │ writes
                              ▼                   ▼
                       ┌─────────────┐    ┌─────────────┐
                       │   Search    │◀───│    SQLite   │
                       │   Agent     │    │  (shared)   │
                       └──────┬──────┘    └─────────────┘
                              │
                              ▼
                       ┌─────────────┐
                       │     UI      │
                       │   Agent     │
                       └─────────────┘

                       ┌─────────────┐
                       │   Critic    │◀─── reviews outputs of
                       │   Agent     │     all other agents
                       └─────────────┘
```

## Workflow Phases

### Phase 1 — Research & Design
**Research Agent → Architect Agent.** Research agent produced a brief comparing concurrency models (threads/asyncio/processes), storage backends, and scoring algorithms. Architect Agent consumed the brief, challenged two of the recommendations, then committed to a design: **Python threads + SQLite WAL + TF-IDF with title boost**. Output was the first draft of `product_prd.md` and a schema sketch.

### Phase 2 — Parallel Implementation
Crawler Agent, Search Agent, and UI Agent worked in **parallel** once the Architect Agent's spec was stable. This phase took the most iteration:

- Crawler Agent implemented the worker pool, bounded queue, rate limiter, and robots.txt cache. It shipped a working `indexer.py` on iteration 1.
- Search Agent implemented the tokenizer (shared with crawler — identical tokenization is required at index and query time or search breaks), then the TF-IDF scoring, then pagination.
- UI Agent built the dashboard in a single `index.html` file. Shipped on iteration 1 but the human flagged a flicker bug in iteration 2.

### Phase 3 — Review & Revision Loop
The Critic Agent reviewed all outputs and produced a structured issue list (see `agents/06_critic_agent.md` for the full table). Seven issues were raised. For each issue:
1. Critic Agent wrote the issue with severity and line reference
2. Human read and triaged (accept, defer, reject)
3. Owning agent implemented the fix
4. Critic Agent verified

The **major issues found** by the Critic Agent:
- SSL verification disabled by default (security regression)
- No HTTP retry on transient errors (reliability)
- UI flicker from full innerHTML replacement (UX — also flagged by the human)
- Sample DB committed to git (privacy — real crawl data)

All seven were fixed before submission.

### Phase 4 — Integration & Testing
Final integration was done by the human: starting the server, running end-to-end crawls, testing cancel/resume, verifying search during active indexing. Minor issues caught at this stage were fed back to the responsible agent.

## How Agents Communicated

Agents did **not** call each other directly. All communication was mediated by the human via Claude Code:

1. Human invokes Agent A with a prompt and a context file
2. Agent A produces output (code, doc, or critique)
3. Human reads and decides: accept, iterate, or reject
4. Human copies relevant output into Agent B's next prompt

This handoff pattern was chosen over autonomous agent-to-agent communication for three reasons:
- **Auditability** — every decision is visible to the human
- **Cost control** — no runaway multi-agent loops
- **Scope control** — each agent stays on task; drift is corrected at the handoff

## Final Decisions the Human Made

The human retained authority over every non-trivial choice. Key calls:
- Chose threads over asyncio despite Critic Agent's scaling concern — justified by the "native Python only" constraint
- Chose SQLite over PostgreSQL — justified by "localhost only" constraint
- Chose to build a dashboard (UI Agent) rather than a CLI — better demo
- Chose to commit a sample DB (`crawler_data_sample.db`) instead of an empty DB — so reviewers can run search immediately without crawling first
- Chose to ship with the "materialize all scores in Python" known bottleneck rather than over-engineer for the exercise scope

## What Worked

- **Single-responsibility agents** prevented context pollution. The Crawler Agent never had to think about CSS.
- **Critic Agent as a separate role** was the most valuable decision. Having a dedicated agent whose only job is to find problems caught 7 issues that would otherwise have shipped.
- **Shared tokenizer between Crawler Agent and Search Agent** — making this explicit in Architect Agent's spec prevented a subtle bug where indexing and querying could use different tokenizations.

## What Would Change Next Time

- Add a **7th agent — Test Agent** that writes `pytest` tests automatically after every code change. QA was done ad-hoc by the human this round.
- Let the Critic Agent run automatically after each code change rather than in a dedicated phase. Catches regressions faster.
- Add an explicit **Integration Agent** responsible for wiring modules together. Integration bugs (e.g., `from .indexer import tokenize` used by Searcher) were fixed manually.

## Deliverables Produced by This Workflow

- Working crawler + search engine — runs on `localhost:8090`
- `readme.md` — user-facing documentation
- `product_prd.md` — Architect Agent's formal spec
- `recommendation.md` — production deployment notes
- `multi_agent_workflow.md` — this document
- `agents/` — individual agent definitions
