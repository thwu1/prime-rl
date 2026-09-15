#!/usr/bin/env python3

"""
Fix bugs in the C cache simulator and generate answers.json.

The simulator has four bugs:
1. cache.c get_tag(): shifts by n_offset_bits + n_index_bits + 1 (should be without +1)
2. cache.c cache_access() hit path: missing last_used timestamp update
3. cache.c cache_access() miss install: sets dirty=0 instead of dirty=is_write
4. cachesim.c print_stats(): write-through traffic uses block_size instead of 4
"""

import json
import os
import subprocess
import sys


def fix_source_files():
    """Apply targeted fixes to the buggy C source code."""

    # --- Fix cache.c (bugs 1, 2, 3) ---
    with open('/app/cache.c', 'r') as f:
        code = f.read()

    # Bug 1: Tag extraction off-by-one
    old_tag = 'c->n_offset_bits + c->n_index_bits + 1'
    new_tag = 'c->n_offset_bits + c->n_index_bits'
    assert old_tag in code, "Bug 1 pattern not found in cache.c"
    code = code.replace(old_tag, new_tag)

    # Bug 2: Missing LRU update on hit
    # Insert set[w].last_used = c->time; after c->hits++;
    old_hit = '            c->hits++;\n            if (is_write)'
    new_hit = '            c->hits++;\n            set[w].last_used = c->time;\n            if (is_write)'
    assert old_hit in code, "Bug 2 pattern not found in cache.c"
    code = code.replace(old_hit, new_hit)

    # Bug 3: Dirty bit not set on write-miss install
    old_dirty = 'set[vw].dirty = 0;'
    new_dirty = 'set[vw].dirty = is_write;'
    assert old_dirty in code, "Bug 3 pattern not found in cache.c"
    code = code.replace(old_dirty, new_dirty)

    with open('/app/cache.c', 'w') as f:
        f.write(code)
    print("Fixed cache.c (bugs 1, 2, 3)")

    # --- Fix cachesim.c (bug 4) ---
    with open('/app/cachesim.c', 'r') as f:
        code = f.read()

    # Bug 4: Write-through traffic uses block_size instead of 4
    old_wt = 'c->n_stores * c->block_size'
    new_wt = 'c->n_stores * 4'
    assert old_wt in code, "Bug 4 pattern not found in cachesim.c"
    code = code.replace(old_wt, new_wt)

    with open('/app/cachesim.c', 'w') as f:
        f.write(code)
    print("Fixed cachesim.c (bug 4)")


def build():
    """Rebuild the simulator."""
    subprocess.run(['make', '-C', '/app', 'clean'], check=True)
    result = subprocess.run(['make', '-C', '/app'], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    print("Rebuild successful")


def run_cachesim(trace, capacity, block_size, assoc):
    """Run the corrected binary and parse its key-value output."""
    result = subprocess.run(
        ['/app/cachesim', trace, str(capacity), str(block_size), str(assoc)],
        capture_output=True, text=True, check=True
    )
    stats = {}
    for line in result.stdout.strip().split('\n'):
        parts = line.split()
        if len(parts) == 2:
            key = parts[0]
            try:
                if '.' in parts[1]:
                    stats[key] = round(float(parts[1]), 2)
                else:
                    stats[key] = int(parts[1])
            except ValueError:
                pass
    return stats


STAT_FIELDS = [
    'hits', 'misses', 'writebacks', 'hit_rate', 'n_stores',
    'bus_to_cache', 'cache_to_bus_wb', 'total_traffic_wb',
    'cache_to_bus_wt', 'total_traffic_wt',
]


def main():
    fix_source_files()
    build()

    trace_a = '/app/traces/trace_a.txt'
    trace_b = '/app/traces/trace_b.txt'
    trace_c = '/app/traces/trace_c.txt'

    # Verify reference trace
    ref = run_cachesim('/app/traces/trace_ref.txt', 64, 32, 1)
    assert ref['hits'] == 2, f"Reference check failed: hits={ref['hits']}, expected 2"
    assert ref['misses'] == 4, f"Reference check failed: misses={ref['misses']}, expected 4"
    assert ref['writebacks'] == 1, f"Reference check failed: writebacks={ref['writebacks']}, expected 1"
    assert ref['cache_to_bus_wt'] == 4, f"Reference check failed: cache_to_bus_wt={ref['cache_to_bus_wt']}, expected 4"
    print("Reference trace verification passed")

    # Q1: trace_a, C=512, B=32, A=1
    q1_raw = run_cachesim(trace_a, 512, 32, 1)
    q1 = {k: q1_raw[k] for k in STAT_FIELDS}

    # Q2: trace_b, C=4096, B=64, A=4
    q2_raw = run_cachesim(trace_b, 4096, 64, 4)
    q2 = {k: q2_raw[k] for k in STAT_FIELDS}

    # Q3: trace_c, C=2048, B=32, A in {1,2,4,8}
    q3_results = {}
    best_miss_rate = float('inf')
    best_a = None
    for a in [1, 2, 4, 8]:
        s = run_cachesim(trace_c, 2048, 32, a)
        q3_results[str(a)] = {
            "miss_rate": s['miss_rate'],
            "total_traffic_wb": s['total_traffic_wb'],
        }
        if s['miss_rate'] < best_miss_rate:
            best_miss_rate = s['miss_rate']
            best_a = a
    q3 = {"results": q3_results, "best_associativity": best_a}

    # Q4: AMAT for 5 configs on trace_a
    q4_params = [
        (256, 16, 1), (512, 32, 1), (512, 32, 2),
        (1024, 32, 2), (1024, 64, 4),
    ]
    q4_configs = []
    best_amat = float('inf')
    best_idx = None
    for i, (c, b, a) in enumerate(q4_params):
        s = run_cachesim(trace_a, c, b, a)
        total = s['hits'] + s['misses']
        miss_frac = s['misses'] / total if total > 0 else 0
        amat = round(1 + miss_frac * 100, 2)
        q4_configs.append({"amat": amat})
        if amat < best_amat:
            best_amat = amat
            best_idx = i
    q4 = {"configs": q4_configs, "best_config_index": best_idx}

    # Q5: minimize total_traffic_wb on trace_b over 36 configs
    best_traffic = float('inf')
    best_config = None
    for c in [512, 1024, 2048, 4096]:
        for b in [16, 32, 64]:
            for a in [1, 2, 4]:
                s = run_cachesim(trace_b, c, b, a)
                t = s['total_traffic_wb']
                if t < best_traffic:
                    best_traffic = t
                    best_config = (c, b, a)
    q5 = {
        "best_config": {
            "capacity": best_config[0],
            "block_size": best_config[1],
            "associativity": best_config[2],
        },
        "min_traffic": best_traffic,
    }

    answers = {"q1": q1, "q2": q2, "q3": q3, "q4": q4, "q5": q5}
    with open('/app/answers.json', 'w') as f:
        json.dump(answers, f, indent=2)
    print("answers.json written successfully")


if __name__ == '__main__':
    main()
