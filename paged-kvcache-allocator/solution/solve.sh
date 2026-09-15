#!/bin/bash

# Fix bugs in the KV-cache manager and scheduler
cp /solution/kv_cache_manager_fixed.py /app/kv_cache_manager.py
cp /solution/scheduler_fixed.py /app/scheduler.py

# Analyze the workload trace (Python — produces analysis.json)
python3 /solution/analyze_trace.py

# Extract per-request stats using jq (produces request_stats.csv)
jq -r '[.steps[] | (.prefills[] | {request_id, pt: .tokens, dt: 0, cb: .cached_blocks, nb: .new_blocks_allocated}), (.decodes[] | {request_id, pt: 0, dt: .tokens, cb: 0, nb: 0})] | group_by(.request_id) | map({request_id: .[0].request_id, total_prefill_tokens: (map(.pt) | add), total_decode_tokens: (map(.dt) | add), total_cached_blocks: (map(.cb) | add), total_new_blocks: (map(.nb) | add)}) | sort_by(.request_id) | (["request_id","total_prefill_tokens","total_decode_tokens","total_cached_blocks","total_new_blocks"]), (.[] | [.request_id, .total_prefill_tokens, .total_decode_tokens, .total_cached_blocks, .total_new_blocks]) | @csv' /app/workload_trace.json > /app/request_stats.csv

# Create SQLite database, import CSV, and run evaluation queries
python3 /solution/evaluate.py
