# Crawler Agent — Real Transcript

**Agent:** Crawler Agent (subagent type: Explore)
**Date:** 2026-04-19

## Prompt Given

> You are the Crawler Agent in a multi-agent software development workflow.
>
> INPUT FROM ARCHITECT AGENT: MAX_WORKERS=10, MAX_QUEUE_DEPTH=10000, RATE_PER_DOMAIN=2 req/sec, SQLite tables pages/crawl_jobs/frontier/inverted_index, Python stdlib only, frontier flushed every 50 pages, 3 retries with exponential backoff on 429/5xx.
>
> Explain how you will implement the crawler. Cover 6 topics: worker coordination, visited thread-safety, token-bucket internals, SSL strategy, retry policy, shutdown sequence.

## Agent's Response (verbatim excerpts)

### Worker Coordination Pattern (Challenge to Architect)

> "Workers cannot simply stop when the queue is empty because the frontier is being continuously refilled by crawl jobs that discover new URLs. We implement a **graceful shutdown sentinel** mechanism: when MAX_QUEUE_DEPTH is reached or the crawler is commanded to stop, we inject exactly N special sentinel objects (where N equals MAX_WORKERS) into the work queue."

### Visited Set Thread-Safety

> "The critical race condition is the 'check-then-act' problem: two workers simultaneously check if a URL exists in the visited set, both find it absent, and both proceed to crawl the same URL. We prevent this by using a lock-protected operation that atomically checks membership and inserts in a single critical section."

### Token-Bucket Pseudocode

```
class TokenBucket:
  tokens = RATE_PER_DOMAIN
  last_refill = current_time()
  lock = Lock()

  function acquire_token():
    lock.acquire()
    elapsed = current_time() - last_refill
    refill_amount = elapsed * RATE_PER_DOMAIN
    tokens = min(tokens + refill_amount, RATE_PER_DOMAIN)
    last_refill = current_time()
    if tokens >= 1:
      tokens -= 1
      lock.release()
      return true
    else:
      lock.release()
      sleep(1.0 / RATE_PER_DOMAIN)
      return acquire_token()
```

### SSL Handling (Rejected by Human)

> "When a site presents a bad certificate (expired, self-signed, hostname mismatch), urllib raises an `ssl.SSLError`. Rather than crash or skip the domain entirely, we treat SSL errors as non-retryable failures."

### Retry Policy

> "We retry on HTTP 429 (rate limit), 500, 502, 503, 504. We do not retry on 4xx codes (except 429): 404 means the page is gone, 403 means forbidden. Each retry backs off exponentially: 1 second, then 2 seconds, then 4 seconds."

### Shutdown Sequence

> "When SIGINT is received, the signal handler sets a `shutdown_flag` boolean. Workers detect the shutdown flag and, upon encountering a sentinel, flush the frontier state to SQLite, release locks, and exit gracefully. No in-flight requests are abandoned."

## Human's Decisions

1. **Worker coordination — rejected sentinel pattern.** Simpler `in_flight` counter + queue empty check was used instead. Rationale: sentinels require careful ordering (all N sentinels must arrive after all real URLs), adding complexity. `in_flight` counter with Lock is unambiguous.

2. **Token-bucket — accepted with change.** The recursive `return acquire_token()` in the pseudocode risks stack overflow under sustained contention. Final implementation uses a `while` loop (iterative).

3. **SSL — partially rejected.** Crawler Agent said "treat as non-retryable failure." Human kept strict verification but added a **lenient fallback** for cert errors, because many valid-content Wikipedia sister sites had bad certs and blanket-failing them lost too much data. This contradicts Critic Agent's "must be CERT_REQUIRED" — human chose reliability > strictness for an educational crawler.

4. **Retry policy — accepted as-is.** Exponential backoff 1s, 2s, 4s implemented exactly as described.

5. **Shutdown — accepted.** SIGINT handler calls `indexer.save_state()` which flushes frontier state. Workers are daemon threads so process exits cleanly after state is persisted.
