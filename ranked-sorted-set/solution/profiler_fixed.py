#!/usr/bin/env python3
"""Redis Sorted Set Memory Profiler (fixed version)

Correctly analyses memory usage and overhead of Redis sorted set keys.
"""

import redis
import json


def connect_redis():
    """Connect to local Redis instance."""
    return redis.Redis(host='localhost', port=6379, decode_responses=True)


def get_sorted_sets(r):
    """Retrieve only sorted-set keys from Redis (filter by type)."""
    zset_keys = []
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor, count=200)
        for key in keys:
            if r.type(key) == 'zset':
                zset_keys.append(key)
        if cursor == 0:
            break
    return sorted(zset_keys)


def measure_key(r, key):
    """Measure memory characteristics of a single sorted set key."""
    cardinality = r.zcard(key)
    mem_bytes = r.memory_usage(key)
    encoding = r.object('encoding', key)

    # Per-entry overhead = (total - key_overhead - cardinality * useful) / cardinality
    # useful = 8 (member pointer) + 8 (score double) = 16 bytes
    key_base_overhead = 80  # approximate
    useful_per_entry = 16
    if cardinality > 0:
        per_entry_overhead = (
            mem_bytes - key_base_overhead - cardinality * useful_per_entry
        ) / cardinality
        per_entry_overhead = max(0.0, per_entry_overhead)
    else:
        per_entry_overhead = 0

    return {
        'key': key,
        'cardinality': cardinality,
        'encoding': encoding,
        'memory_bytes': mem_bytes,
        'per_entry_overhead_bytes': round(per_entry_overhead, 2),
    }


def compute_theoretical_skiplist_overhead():
    """Compute theoretical per-entry overhead for Redis skiplist encoding.

    Redis uses ZSKIPLIST_P = 0.25 (not 0.5).
    Node structure:
        member_ptr (8) + score (8) + backward (8) = 24 bytes base
        + levels * (forward(8) + span(8)) = 16 per level
    Average levels = 1 / (1 - 0.25) = 1.3333
    Average node = 24 + 16 * 1.3333 = 45.33
    Overhead = 45.33 - 16 = 29.33 bytes
    """
    p = 0.25
    avg_levels = 1.0 / (1.0 - p)
    avg_node_size = 24 + 16 * avg_levels
    overhead = avg_node_size - 16  # subtract useful (member_ptr + score)
    return round(overhead, 2)


def main():
    r = connect_redis()

    keys = get_sorted_sets(r)
    print(f"Found {len(keys)} sorted set keys")

    results = []
    for key in keys:
        info = measure_key(r, key)
        results.append(info)

    theoretical = compute_theoretical_skiplist_overhead()

    report = {
        'total_keys_analyzed': len(results),
        'sorted_sets': results,
        'theoretical_skiplist_overhead_bytes': theoretical,
    }

    with open('/app/audit_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Wrote audit report with {len(results)} sorted set entries")
    print(f"Theoretical skiplist overhead: {theoretical} bytes/entry")


if __name__ == '__main__':
    main()
