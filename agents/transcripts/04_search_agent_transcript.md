# Search Agent — Real Transcript

**Agent:** Search Agent (subagent type: Explore)
**Date:** 2026-04-19

## Prompt Given

> You are the Search Agent in a multi-agent software development workflow.
>
> INPUT FROM ARCHITECT AGENT: SQLite table `inverted_index(token, url, tf, field)`, IDF computed at QUERY time, title matches get 3.0x boost, pagination via limit/offset, must work with SQLite WAL mode during concurrent writes.
>
> Explain 5 things: tokenizer contract, IDF-at-query-time trade-off, scoring formula, WAL-safe read pattern, pagination with total count.

## Agent's Response (verbatim excerpts)

### Tokenizer Contract

> "The tokenizer must be byte-for-byte identical between the Crawler Agent (indexing) and Search Agent (querying) because any deviation creates a fundamental mismatch in the inverted index. If the indexer splits 'machine-learning' into ['machine', 'learning'] but the query tokenizer produces ['machine-learning'], that query token will never match indexed documents even though they exist."

### IDF at Query Time (Justification)

> "If you pre-compute and store IDF in the table, you lock the scoring to a fixed corpus snapshot — the moment you add one new document, all IDF values become stale and incorrect. A term that appeared in 5% of documents when indexed might now appear in 50%, but the stored IDF won't update."

### Scoring Formula (Proposed)

```
score(doc, query) = Σ over query_tokens [
  (1 + log(tf_in_title)) × log(N/df) × 3.0
  + (1 + log(tf_in_body)) × log(N/df) × 1.0
]
```

> "Title gets 3.0x weight because it's typically authored with deliberate keyword choice and much shorter than body text, so a title match is more likely to indicate relevance than a single body mention buried in 10,000 words. A 2.0 boost would undervalue the semantic signal of deliberate titling; a 5.0 boost would over-privilege single title matches."

### WAL-Safe Read Pattern

> "A single long-lived connection may see inconsistent snapshots if the Crawler Agent checkpoints the log mid-query. By opening a fresh connection for each query, you isolate the entire query operation within a single transaction with a consistent view of the database at that moment."

### Pagination Total Count

> "Compute the total result count with a separate aggregation query before pagination: `SELECT COUNT(*) FROM (SELECT DISTINCT url FROM results_query)`. Then fetch only the paginated slice using `LIMIT ? OFFSET ?`."

## Human's Decisions

1. **Tokenizer — accepted.** Critic Agent flagged code duplication (defined in both `indexer.py` and `searcher.py`). Human resolved by defining `tokenize()` in `indexer.py` and importing into `searcher.py`, keeping a single source of truth.

2. **Scoring formula — simplified.** The Search Agent proposed `(1 + log(tf))` saturating TF. The final implementation uses raw TF (no log saturation) because:
   - Log saturation complicates manual verification (students doing homework showed confusion)
   - At the crawl scale (<10K docs), TF saturation doesn't meaningfully improve ranking
   - Simpler formula: `tf × idf × weight` where weight=3.0 for title, 1.0 for body

3. **IDF at query time — accepted.** Per token: `idf = log(total_docs / df)`, computed in `storage.search()`.

4. **WAL read pattern — accepted.** Each call to `storage.search()` opens a fresh connection via `_read_conn()`.

5. **Pagination — partial accept.** Final implementation doesn't use a separate COUNT query. Instead, it materializes all matching (url, score) tuples into a Python dict, sorts, and slices in-memory. Trade-off: works for <100K matching results (our actual scale), but would bottleneck at corpus-size 1M+. Critic Agent flagged this as a future scalability concern — human accepted the trade-off for the exercise scope.
