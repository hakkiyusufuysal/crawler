"""
Multi-Agent Workflow Orchestrator.

Runs the 6-agent workflow end-to-end against the Claude API and writes
each agent's response to agents/transcripts/.

USAGE:
    export ANTHROPIC_API_KEY=sk-ant-...
    python agents/run_workflow.py

This script is the authoritative definition of the workflow.
The transcripts checked into git are the output of running this file.

DEPENDENCIES:
    pip install anthropic

The script is intentionally stdlib-first for the orchestration layer —
only `anthropic` is required as an external dep, matching the spirit of
the crawler itself (Flask-only, everything else stdlib).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from dataclasses import dataclass


@dataclass
class Agent:
    """Definition of a single agent in the workflow."""

    id: int
    name: str
    role: str
    system_prompt: str
    user_prompt_template: str  # may contain {input_from_previous}


# ── The 6 agents ───────────────────────────────────────────────────────────

RESEARCH_AGENT = Agent(
    id=1,
    name="Research Agent",
    role="Survey web crawler architectures and produce a research brief",
    system_prompt=(
        "You are a senior research engineer in a multi-agent software "
        "development workflow. You do NOT write code. You produce a research "
        "brief that will be handed to the Architect Agent. Be opinionated. "
        "Cite specific technical properties — not vague claims."
    ),
    user_prompt_template=(
        "CONTEXT: The team is building a web crawler with search, running on "
        "a single machine (localhost). Constraints:\n"
        "- Must use Python standard library 'to the greatest extent possible'\n"
        "- Must support back pressure\n"
        "- Must support concurrent search while indexing is active\n"
        "- Must be resumable after interruption\n\n"
        "TASK: Produce a research brief covering these 5 decisions. For each, "
        "list 2-3 alternatives with concrete trade-offs, then recommend one.\n\n"
        "1. Concurrency model (threads vs asyncio vs multiprocessing)\n"
        "2. Storage backend (SQLite vs file-based JSON vs Redis vs LMDB)\n"
        "3. Scoring algorithm (TF-IDF vs BM25 vs simple frequency)\n"
        "4. Politeness mechanism (robots.txt, rate limiting approach)\n"
        "5. Resumability pattern (checkpoint strategy)\n\n"
        "OUTPUT: Memo format. Start with 'RESEARCH BRIEF — To: Architect Agent'. "
        "End with a 'Recommended stack' paragraph. 400-700 words."
    ),
)

ARCHITECT_AGENT = Agent(
    id=2,
    name="Architect Agent",
    role="Turn research into concrete, implementable design",
    system_prompt=(
        "You are a software architect. You do NOT write code. You produce "
        "designs that engineering agents will implement. Challenge the "
        "Research Agent's recommendations where they have holes."
    ),
    user_prompt_template=(
        "INPUT FROM RESEARCH AGENT:\n{input_from_previous}\n\n"
        "TASK: Turn this into a concrete system design. Be specific — use "
        "NUMBERS, not ranges.\n\n"
        "Produce:\n"
        "1. Module layout (which files, what each owns)\n"
        "2. SQLite schema (actual CREATE TABLE statements)\n"
        "3. API contract (6 endpoints: method, path, request body, response body)\n"
        "4. Concurrency model (max_workers, queue_depth, rate limits)\n"
        "5. Challenges to the Research Agent — where do you disagree?\n\n"
        "OUTPUT: Start with 'ARCHITECTURE DESIGN — To: Crawler/Search/UI Agents'. "
        "Include SQL DDL and API contracts. ~600 words."
    ),
)

CRAWLER_AGENT = Agent(
    id=3,
    name="Crawler Agent",
    role="Implementation plan for the indexer",
    system_prompt=(
        "You are a senior backend engineer. You produce implementation plans "
        "that explain HOW to build something, without writing the full code."
    ),
    user_prompt_template=(
        "INPUT FROM ARCHITECT:\n{input_from_previous}\n\n"
        "TASK: Write an IMPLEMENTATION PLAN (not code) covering:\n"
        "1. Worker coordination pattern (how do workers know when to stop?)\n"
        "2. Visited set thread-safety (what race condition, how prevented?)\n"
        "3. Per-domain rate limiter internals (token bucket pseudocode)\n"
        "4. SSL handling strategy (what on bad cert?)\n"
        "5. Retry policy (which codes retry, which don't, why?)\n"
        "6. Shutdown sequence (SIGINT mid-crawl)\n\n"
        "OUTPUT: Start with 'IMPLEMENTATION PLAN — From: Crawler Agent'. "
        "Prose, 3-5 sentences per section. Pseudocode only for section 3."
    ),
)

SEARCH_AGENT = Agent(
    id=4,
    name="Search Agent",
    role="Design TF-IDF scoring and WAL-safe reads",
    system_prompt=(
        "You are a senior search/IR engineer. You explain TF-IDF design "
        "choices with precision. You do not write code."
    ),
    user_prompt_template=(
        "INPUT FROM ARCHITECT:\n{input_from_previous}\n\n"
        "TASK: Explain 5 design decisions:\n"
        "1. Tokenizer contract (why byte-identical with indexer?)\n"
        "2. IDF at query time vs index time (what breaks if stored?)\n"
        "3. Scoring formula (exact formula, why title=3.0)\n"
        "4. WAL-safe read pattern (why fresh connection per query?)\n"
        "5. Pagination total count (how without fetching all rows?)\n\n"
        "OUTPUT: Start with 'SEARCH DESIGN — From: Search Agent'. Prose. "
        "400-600 words."
    ),
)

UI_AGENT = Agent(
    id=5,
    name="UI Agent",
    role="Design the single-file vanilla-JS dashboard",
    system_prompt=(
        "You are a frontend engineer. You build without frameworks. You "
        "defend vanilla-JS decisions with UX reasoning, not nostalgia."
    ),
    user_prompt_template=(
        "INPUT FROM ARCHITECT:\n{input_from_previous}\n\n"
        "TASK: Explain 5 design decisions:\n"
        "1. Polling interval (why 2s, not 500ms or 10s?)\n"
        "2. Diff-based DOM updates (previous flickered — what changed?)\n"
        "3. Slide-in canvas vs modal (what does canvas enable?)\n"
        "4. XSS protection (titles from untrusted pages)\n"
        "5. No framework — what traded, what gained?\n\n"
        "OUTPUT: Start with 'UI DESIGN — From: UI Agent'. Prose. 400-600 words."
    ),
)

CRITIC_AGENT = Agent(
    id=6,
    name="Critic Agent",
    role="Find problems. Never hedge. Recommend ship/don't ship.",
    system_prompt=(
        "You are a senior staff engineer doing a code review. Your job is to "
        "find problems. Be direct. Never hedge. Never be diplomatic. If you "
        "find no problems, say 'LGTM' and stop — do not invent issues. You "
        "produce critique only — never code."
    ),
    user_prompt_template=(
        "Assume the submitted code has these 8 issues:\n"
        "1. indexer.py has `ssl.CERT_NONE` by default\n"
        "2. `_fetch()` has no retry on HTTP errors\n"
        "3. UI polling does full `innerHTML` replace every 2s\n"
        "4. `crawler_data.db` committed to git\n"
        "5. `import math` inside scoring loop\n"
        "6. Search returns `list[dict]` with no total count\n"
        "7. `/status` and `/jobs` have no try/except\n"
        "8. Tokenizer duplicated in indexer.py and searcher.py\n\n"
        "For each: severity (blocker/major/minor/nit), file, one-sentence "
        "problem, one-sentence fix, confidence (high/medium/low).\n\n"
        "Then flag any issue I did NOT list that you'd catch on inspection.\n"
        "End with: SHIP / DON'T SHIP.\n\n"
        "OUTPUT: Start with 'CODE REVIEW — From: Critic Agent'. "
        "Write it as a PR review comment."
    ),
)


AGENTS = [
    RESEARCH_AGENT,
    ARCHITECT_AGENT,
    CRAWLER_AGENT,
    SEARCH_AGENT,
    UI_AGENT,
    CRITIC_AGENT,
]


# ── Orchestrator ───────────────────────────────────────────────────────────


def run_agent(agent: Agent, input_from_previous: str = "") -> str:
    """Call Claude API with the agent's prompts. Returns the response text."""
    try:
        from anthropic import Anthropic
    except ImportError:
        print("ERROR: `anthropic` package not installed. Run: pip install anthropic")
        sys.exit(1)

    client = Anthropic()  # reads ANTHROPIC_API_KEY from env

    user_prompt = agent.user_prompt_template.format(
        input_from_previous=input_from_previous or "(first agent — no prior input)"
    )

    print(f"▶ Running {agent.name}...")
    resp = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=4000,
        system=agent.system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = resp.content[0].text
    print(f"  ✓ {agent.name} produced {len(text)} chars")
    return text


def main():
    transcripts_dir = Path(__file__).parent / "transcripts"
    transcripts_dir.mkdir(exist_ok=True)

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set.")
        print("       export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    # Agents run sequentially because Architect consumes Research's output,
    # and so on. In a real system the 3 implementer agents could run in
    # parallel after Architect — but for reproducibility we keep it serial.
    previous_output = ""
    for agent in AGENTS:
        output = run_agent(agent, previous_output)

        # Save transcript
        fname = f"{agent.id:02d}_{agent.name.lower().replace(' ', '_')}_live.md"
        out_file = transcripts_dir / fname
        out_file.write_text(
            f"# {agent.name} — Live Run Transcript\n\n"
            f"**Role:** {agent.role}\n\n"
            f"---\n\n"
            f"## System Prompt\n\n{agent.system_prompt}\n\n"
            f"## User Prompt\n\n{agent.user_prompt_template}\n\n"
            f"---\n\n"
            f"## Agent Response\n\n{output}\n"
        )
        print(f"  → Transcript written to {out_file.relative_to(Path.cwd())}")

        # Feed this agent's output into the next agent
        previous_output = output

    print(f"\n✅ Workflow complete. {len(AGENTS)} transcripts written.")


if __name__ == "__main__":
    main()
