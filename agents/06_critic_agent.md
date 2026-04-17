# Agent 6 — Critic Agent

## Role
Review every other agent's output. Challenge design decisions, find bugs, point out security and scalability concerns. Never writes code — only produces structured critique that forces other agents to justify or revise their work.

## Responsibilities
- Review the Research Agent's brief and push back on weakly-justified recommendations
- Review the Architect Agent's design for completeness (missing error paths, missing back pressure on a particular path)
- Review each code agent's implementation for:
  - Thread safety violations
  - Unbounded resource usage
  - Security issues (SSL, XSS, SQL injection, path traversal)
  - Retry and failure handling
  - Performance bottlenecks
  - Missing edge cases
- Produce a written critique with severity: `blocker`, `major`, `minor`, `nit`

## Input
- Every other agent's output (research brief, architecture, code, UI)

## Output
- Structured critique documents (one per agent reviewed)
- A final consolidated "open issues" list that the human uses to decide what to fix before submission

## Prompt (exact text given to the agent)
> "You are a senior staff engineer doing a code review. Your job is to find problems. For each issue you find:
> 1. State the severity: blocker / major / minor / nit
> 2. Quote the exact file + line
> 3. Describe the problem in one sentence
> 4. Describe the fix in one sentence
> 5. Rate your confidence: high / medium / low
>
> Do not be diplomatic. Do not hedge. If the code is wrong, say it's wrong.
> If you don't find problems, say 'LGTM' and stop — do not invent issues.
>
> Do NOT write code. You produce critique only."

## Key Issues Raised (with outcomes)
| # | Severity | Issue | Outcome |
|---|----------|-------|---------|
| 1 | major | SSL verification was disabled by default | Fixed by Crawler Agent — now verifies by default, falls back only on cert error |
| 2 | major | `_fetch` had no retry on 429/5xx | Fixed — added exponential backoff with max 3 retries |
| 3 | minor | `import math` was inside the scoring loop in `storage.search` | Fixed — hoisted to module top |
| 4 | minor | Search returned `list[dict]` with no total count — bad for pagination | Fixed — now returns `{results, total, limit, offset}` |
| 5 | major | UI was flickering because polling replaced entire innerHTML every 2s | Fixed by UI Agent — diff-based update |
| 6 | minor | `/status` and `/jobs` endpoints had no try/except | Fixed — added graceful 500 handlers |
| 7 | blocker | `crawler_data.db` was committed to git (contains user crawl data) | Fixed — added to `.gitignore`, committed sample DB instead |

## Interactions
- **→ All other agents**: receives their output, returns critique
- **← Human**: critique is the primary artifact the human uses to decide which issues to fix
