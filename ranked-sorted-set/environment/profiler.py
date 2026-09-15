#!/usr/bin/env python3
"""Redis Sorted Set Memory Profiler
Analyzes memory usage and overhead of Redis sorted set keys.

Author: previous SRE (incomplete, known issues)
"""
import redis
import json
import math


def connect_redis():
    """Connect to local Redis instance."""
    return redis.Redis(host='localhost', port=6379, decode_responses=True)


def get_sorted_sets(r):
    """Retrieve all sorted set keys from Redis."""
    # Collects all keys without filtering by type
    all_keys = list(r.keys('*'))
    return sorted(all_keys)


def measure_key(r, key):
    """Measure memory characteristics of a single sorted set key."""
    cardinality = r.zcard(key)
    mem_bytes = r.memory_usage(key)
    encoding = r.object('encoding', key)

    # Per-entry overhead: total memory divided by number of entries
    per_entry = mem_bytes / cardinality if cardinality > 0 else 0

    return {
        'key': key,
        'cardinality': cardinality,
        'encoding': encoding,
        'memory_bytes': mem_bytes,
        'per_entry_overhead_bytes': round(per_entry, 2),
    }


def compute_theoretical_skiplist_overhead():
    """Compute theoretical per-entry overhead for Redis skiplist encoding.

    Based on the skiplist node structure:
      - member pointer (sds): 8 bytes
      - score (double): 8 bytes
      - backward pointer: 8 bytes
      - per level: forward pointer (8) + span (8) = 16 bytes

    Each node has at least 1 level, with a promotion probability
    determining how many additional levels a node occupies.
    """
    # Promotion probability for Redis skiplist
    promotion_probability = 0.5

    # Base node size without level array
    # member_ptr(8) + score(8) + 1_level_forward(8) + 1_level_span(8)
    base_node_bytes = 32
    per_level_bytes = 16

    # Average number of levels per node: 1 / (1 - p)
    avg_levels = 1.0 / (1.0 - promotion_probability)

    # Average total node size
    avg_node_size = base_node_bytes + per_level_bytes * (avg_levels - 1)

    # Overhead = total node size - useful data (member_ptr + score = 16 bytes)
    overhead = avg_node_size - 16

    return round(overhead, 2)


def main():
    r = connect_redis()

    keys = get_sorted_sets(r)
    print(f"Found {len(keys)} keys to analyze")

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

    print(f"Wrote audit report with {len(results)} entries")
    print(f"Theoretical skiplist overhead: {theoretical} bytes/entry")


if __name__ == '__main__':
    main()
