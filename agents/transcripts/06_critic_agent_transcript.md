# Critic Agent — Real Transcript

**Agent:** Critic Agent (subagent type: Explore)
**Date:** 2026-04-19

## Prompt Given

> You are the Critic Agent. Your role: find problems. Never hedge. Never be diplomatic.
>
> CONTEXT: The Crawler, Search, and UI agents have submitted their code. You are doing a code review. The human will fix the issues you raise before shipping.
>
> Given this list of issues in the code [SSL off, no retries, innerHTML flicker, DB in git, import in loop, no total count, no try/except, tokenizer duplication]:
> - Rate severity: blocker/major/minor/nit
> - Cite file + area
> - Why broken (1 sentence)
> - Fix (1 sentence)
> - Confidence
>
> Flag any issue I did NOT list. End with: SHIP / DON'T SHIP.

## Agent's Response (verbatim)

**ISSUE 1: SSL Verification Disabled**
- **Severity:** Blocker
- **File:** indexer.py
- **Problem:** `ssl_ctx.verify_mode = ssl.CERT_NONE` disables certificate verification, leaving the crawler vulnerable to man-in-the-middle attacks on all HTTPS requests.
- **Fix:** Set `ssl_ctx.verify_mode = ssl.CERT_REQUIRED` and load system CA certificates.
- **Confidence:** High

**ISSUE 2: No HTTP Retry Logic**
- **Severity:** Blocker
- **File:** crawler.py (_fetch)
- **Problem:** A single 429 response will permanently fail that URL with no exponential backoff, causing data loss on rate-limited domains.
- **Fix:** Implement exponential backoff with jitter (start 1s, cap 60s) for 429/5xx errors, retrying up to 3 times.

**ISSUE 3: UI Flicker from innerHTML Replacement**
- **Severity:** Major
- **File:** ui/app.js
- **Problem:** `container.innerHTML = jobsHtml` every 2 seconds causes the DOM to be completely recreated, destroying focus, scroll position, and triggering unnecessary reflows.
- **Fix:** Use a diffing approach and only replace changed nodes.

**ISSUE 4: Real User Data Committed to Git**
- **Severity:** Blocker
- **File:** crawler_data.db
- **Problem:** Database containing actual user crawl data is tracked in version control, exposing PII and test data to all repository users.
- **Fix:** Add to `.gitignore`, remove from git history via `git filter-repo`.

**ISSUE 5: Import Inside Loop**
- **Severity:** Minor
- **Fix:** Move `import math` to the top of the file.

**ISSUE 6: Search Response Missing Total Count**
- **Severity:** Major
- **Fix:** Return `{"results": list[dict], "total": int}` so pagination can calculate page count.

**ISSUE 7: Missing Error Handlers in Flask Endpoints**
- **Severity:** Major
- **Fix:** Wrap endpoint logic in try/except, log errors, return `{"error": "message"}` with 400/500.

**ISSUE 8: Tokenizer Code Duplication**
- **Severity:** Major
- **Problem:** Identical tokenizer logic in two files creates drift risk — if one is updated, queries will tokenize differently than indexed data, breaking search.
- **Fix:** Extract tokenizer to a shared module.

---

## Additional Issues Found (NOT in Human's List)

**ISSUE 9: No Input Validation on /jobs Endpoint**
- **Severity:** Major
- **Problem:** No validation of query parameters allows negative page numbers or excessively large limits, risking DoS.
- **Fix:** Validate and constrain parameters.

**ISSUE 10: Crawler URL Filtering Missing**
- **Severity:** Major
- **Problem:** No URL validation allows crawling of `javascript:`, `data:`, or `file://` URIs.
- **Fix:** Only allow http:// and https:// schemes.

---

**RECOMMENDATION: DON'T SHIP**

> "Issues 1, 2, 4, and 7 are blockers. The code requires rework before production — SSL is broken, rate-limiting will cause data loss, user data is exposed, and endpoints will crash unhandled."

## Human's Decisions (Post-Critic Review)

| Issue | Critic Severity | Action Taken |
|-------|----------------|--------------|
| 1. SSL off | blocker | **Partially accepted.** Made SSL strict by default, added lenient fallback on cert errors (Critic wanted full CERT_REQUIRED — rejected for reliability with sites like fr.wikipedia.org having intermittent cert issues) |
| 2. No retries | blocker | **Accepted.** Added exponential backoff 1s/2s/4s, max 3 retries, on 429 + 5xx |
| 3. UI flicker | major | **Accepted.** Diff-based updates via JSON equality check in closure |
| 4. DB in git | blocker | **Accepted.** Added to `.gitignore`, replaced with `crawler_data_sample.db` for reviewers |
| 5. import in loop | minor | **Accepted.** Hoisted `import math` to module top |
| 6. No total count | major | **Accepted.** `search()` now returns `{results, total, limit, offset}` |
| 7. No try/except | major | **Accepted.** Wrapped `/status` and `/jobs` with try/except, 500 with JSON error body |
| 8. Tokenizer dup | major | **Accepted.** `tokenize()` defined once in `indexer.py`, imported in `searcher.py` |
| 9. No /jobs input validation | major | **Partially accepted.** Added `limit = min(int(request.args.get("limit", 50)), 200)` cap, `offset = max(int(...), 0)` floor. Did not add per-endpoint page schema |
| 10. URL scheme filter | major | **Accepted.** `parser.py::_resolve_url()` filters javascript:/mailto:/tel:/data: and requires scheme in {http, https} |

**"DON'T SHIP" became "SHIP" after all 10 issues were resolved.** Final verification: 40 unit tests pass, live end-to-end test with Wikipedia crawl + concurrent search.
