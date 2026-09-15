An LLM inference system at `/app/` implements paged KV-cache block allocation with prefix caching and a scheduler supporting FCFS/priority policies, chunked prefill, and preemption. The type definitions in `/app/kv_types.py` are correct — do not modify that file.

The implementations in `/app/kv_cache_manager.py` and `/app/scheduler.py` contain multiple correctness bugs. Diagnose and fix all bugs so the full test suite passes.

Analyze the workload trace at `/app/workload_trace.json` and produce the following artifacts:

**`/app/analysis.json`** — Trace-level aggregate metrics:
- `"total_preemptions"`: count of preemption events across all steps
- `"peak_active_requests"`: maximum number of requests served (prefill + decode) in any single step
- `"cache_hit_ratio"`: mean of `cached_blocks / (cached_blocks + new_blocks_allocated)` across prefill events that allocated at least one block, rounded to 4 decimal places
- `"total_decode_tokens"`: total decode tokens generated across all steps

**`/app/request_stats.csv`** — Per-request aggregate statistics extracted from the trace using `jq`. CSV with headers: `request_id,total_prefill_tokens,total_decode_tokens,total_cached_blocks,total_new_blocks`. Each row aggregates all prefill and decode events for one request across every step. Rows sorted by request_id.

**`/app/evaluation.json`** — Scheduling quality evaluation derived via SQL queries against a SQLite database at `/app/analysis.db` (created by importing the CSV into a table called `request_stats`):
- `"highest_cache_efficiency_request"`: request_id with maximum `cached_blocks / (cached_blocks + new_blocks)` ratio
- `"avg_decode_tokens"`: mean decode tokens per request, rounded to 2 decimal places
- `"total_blocks_allocated"`: sum of cached_blocks + new_blocks across all requests
- `"fairness_index"`: Jain's fairness index of the decode token distribution across requests (= (sum(x))^2 / (n * sum(x^2))), rounded to 4 decimal places