#!/usr/bin/env python3
"""Analyze workload trace and write metrics to /app/analysis.json."""

import json

with open('/app/workload_trace.json') as f:
    trace = json.load(f)

total_preemptions = 0
peak_active = 0
cache_ratios = []
total_decode_tokens = 0

for step in trace['steps']:
    total_preemptions += len(step['preemptions'])

    active = len(step['prefills']) + len(step['decodes'])
    peak_active = max(peak_active, active)

    for p in step['prefills']:
        cached = p['cached_blocks']
        new = p['new_blocks_allocated']
        total = cached + new
        if total > 0:
            cache_ratios.append(cached / total)

    for d in step['decodes']:
        total_decode_tokens += d['tokens']

cache_hit_ratio = round(sum(cache_ratios) / len(cache_ratios), 4) if cache_ratios else 0.0

result = {
    "total_preemptions": total_preemptions,
    "peak_active_requests": peak_active,
    "cache_hit_ratio": cache_hit_ratio,
    "total_decode_tokens": total_decode_tokens
}

with open('/app/analysis.json', 'w') as f:
    json.dump(result, f, indent=2)
