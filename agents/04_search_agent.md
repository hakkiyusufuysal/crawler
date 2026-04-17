# Agent 4 — Search Agent

## Role
Implement TF-IDF scoring over the inverted index. Own `crawler/searcher.py` and the `search()` method in `crawler/storage.py`. Ensure search works while indexing is active (SQLite WAL correctness).

## Responsibilities
- Implement the tokenizer (regex + stop-word filter) — shared with Crawler Agent so indexing and querying use identical tokens
- Implement TF calculation at index time (done per-field: title, body)
- Implement IDF calculation at query time (to reflect new documents)
- Implement scoring: score = sum over tokens of TF × IDF × field_weight
- Implement pagination (limit, offset, total count)
- Ensure every search query uses a fresh read connection (WAL concurrency)
- Return triples in the required (relevant_url, origin_url, depth) format

## Input
- Architecture spec from Architect Agent
- SQLite schema with `inverted_index` table

## Output
- `crawler/searcher.py` — Searcher class, thin wrapper
- `storage.search()` method in `crawler/storage.py` — does the heavy lifting
- `tokenize()` function in `crawler/indexer.py` — exported and reused

## Prompt (exact text given to the agent)
> "You are a search engineer. Implement TF-IDF scoring with these rules:
>
> 1. Tokenizer: lowercase, alphanumeric tokens ≥2 chars, filter ~100 English stop words
> 2. TF is stored at index time as (token, url, tf, field) with field ∈ {title, body}
> 3. IDF is computed at query time: log(total_docs / docs_containing_token)
> 4. Score = Σ TF × IDF × weight. weight = 3.0 if field='title', else 1.0
> 5. Support pagination via limit + offset
> 6. Return total match count alongside paginated results
> 7. Every search query must open its own read connection — do NOT reuse the writer's connection
>
> The search function must be safe to call while the crawler is still writing. Verify this holds under the SQLite WAL model. Do not introduce locks that would block the writer."

## Key Decisions Delivered
- **IDF at query time, not index time**: means scores adapt as new documents are indexed. A word's relative rarity changes as the corpus grows.
- **Title weight at query time, not index time**: allows re-tuning the boost factor (currently 3.0) without re-indexing. Tested 2.0 and 5.0 as alternatives; 3.0 gave best manual-eval results on Wikipedia.
- **Separate read connection per query**: SQLite's `check_same_thread=False` + WAL allows unlimited concurrent readers. No locks on the read path means search latency is independent of crawl rate.
- **Pagination returns `total`**: UI needs to show "1–20 of 94 results". Computing total requires materializing all matching URLs into a dict of scores; for very large result sets this is a known bottleneck flagged to the Critic Agent.

## Interactions
- **← Architect Agent**: consumes schema
- **← Crawler Agent**: shares `tokenize()` function — same tokenizer must be used at index AND query time
- **→ UI Agent**: provides paginated JSON response format
- **← Critic Agent**: flagged the "materialize all scores in Python" scaling concern
