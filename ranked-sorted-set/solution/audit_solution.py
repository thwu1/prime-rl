#!/usr/bin/env python3
"""Complete audit solution: diagnoses memory anomaly, fixes config,
re-encodes affected sets, and produces the audit report.
"""

import json
import redis as redis_lib


def get_all_zset_keys(r):
    """Scan for all sorted-set keys."""
    keys = []
    cursor = 0
    while True:
        cursor, batch = r.scan(cursor, count=200)
        for k in batch:
            if r.type(k) == 'zset':
                keys.append(k)
        if cursor == 0:
            break
    return sorted(keys)


def compute_theoretical_skiplist_overhead():
    """Derive per-entry overhead from the Redis skiplist node struct.

    Redis skiplist node (64-bit):
        sds ele           — 8 bytes (member pointer)
        double score       — 8 bytes
        *backward          — 8 bytes
        level[] with each entry:
            *forward       — 8 bytes
            unsigned long span — 8 bytes  (16 bytes per level)

    Every node has >= 1 level.
    ZSKIPLIST_P = 0.25 → average levels = 1 / (1 - 0.25) = 1.3333

    Raw average node size  = 24 + 16 * 1.3333 = 45.33 bytes
    Useful data per entry  = 8 (member ptr) + 8 (score) = 16 bytes
    Raw overhead           = 45.33 - 16 = 29.33 bytes

    With jemalloc rounding (to size-class boundaries):
      1-level node: 40 → 48 bytes
      2-level node: 56 → 64 bytes
      3-level node: 72 → 80 bytes
      ...
    Weighted average with p=0.25:
      0.75*48 + 0.1875*64 + 0.046875*80 + 0.015625*96 + ...
      ≈ 36 + 12 + 3.75 + 1.5 + ... ≈ 53-54 bytes
    Allocator-adjusted overhead ≈ 37-38 bytes

    We report the raw theoretical value; allocator rounding is noted separately.
    """
    p = 0.25  # ZSKIPLIST_P
    avg_levels = 1.0 / (1.0 - p)  # 1.3333
    # node = member_ptr(8) + score(8) + backward(8) + levels * 16
    raw_node = 8 + 8 + 8 + 16 * avg_levels  # 24 + 21.33 = 45.33
    useful = 16  # member_ptr + score
    overhead = raw_node - useful  # 29.33

    # Allocator-adjusted estimate (jemalloc)
    adjusted = 0.0
    for lvl in range(1, 33):
        prob = (1 - p) * (p ** (lvl - 1))
        raw_size = 24 + 16 * lvl
        # jemalloc rounds to next 16-byte boundary for small allocs
        rounded = ((raw_size + 15) // 16) * 16
        adjusted += prob * rounded
    adjusted_overhead = adjusted - useful

    return {
        'raw_bytes': round(overhead, 2),
        'allocator_adjusted_bytes': round(adjusted_overhead, 2),
        'promotion_probability': p,
        'average_levels': round(avg_levels, 4),
        'useful_data_per_entry': useful,
    }


def main():
    r = redis_lib.Redis(host='localhost', port=6379, decode_responses=True)
    r.ping()

    # ---- 1. Discover current config ----
    cfg = r.config_get('zset-max-listpack-entries')
    current_threshold = int(cfg.get('zset-max-listpack-entries', 128))

    # ---- 2. Analyse every sorted set ----
    keys = get_all_zset_keys(r)
    sorted_sets = []
    suboptimal_keys = []
    total_mem_before = 0

    for key in keys:
        card = r.zcard(key)
        mem = r.memory_usage(key)
        enc = r.object('encoding', key)
        total_mem_before += mem

        # Per-entry overhead above the 16-byte minimum (member_ptr + score)
        key_base = 80  # approximate Redis key object overhead
        useful_per_entry = 16
        raw_overhead = (
            (mem - key_base - card * useful_per_entry) / card
            if card > 0 else 0
        )
        raw_overhead = max(0.0, raw_overhead)

        # Determine if encoding is optimal
        is_optimal = True
        if enc in ('listpack', 'ziplist') and card > 128:
            is_optimal = False
            suboptimal_keys.append(key)

        sorted_sets.append({
            'key': key,
            'cardinality': card,
            'encoding': enc,
            'memory_bytes': mem,
            'per_entry_overhead_bytes': round(raw_overhead, 2),
            'encoding_optimal': is_optimal,
            'recommendation': (
                'Convert to skiplist: lower zset-max-listpack-entries to 128'
                if not is_optimal else None
            ),
        })

    # ---- 3. Theoretical overhead ----
    theory = compute_theoretical_skiplist_overhead()

    # ---- 4. Fix configuration ----
    r.config_set('zset-max-listpack-entries', 128)

    # ---- 5. Trigger re-encoding of suboptimal sets ----
    dummy = '__audit_reencoding_trigger__'
    for key in suboptimal_keys:
        r.zadd(key, {dummy: 0.0})
        r.zrem(key, dummy)

    # ---- 6. Measure memory after fix ----
    total_mem_after = 0
    for key in keys:
        total_mem_after += r.memory_usage(key)

    # ---- 7. Build report ----
    report = {
        'sorted_sets': sorted_sets,
        'total_sorted_sets': len(sorted_sets),
        'theoretical_skiplist_overhead_bytes': theory['raw_bytes'],
        'theoretical_details': theory,
        'suboptimal_sets': suboptimal_keys,
        'current_max_listpack_entries': current_threshold,
        'recommended_max_listpack_entries': 128,
        'root_cause': (
            f'zset-max-listpack-entries was configured to {current_threshold}, '
            f'far above the default of 128. This caused {len(suboptimal_keys)} '
            f'sorted sets with 129-{current_threshold} entries to remain in '
            f'listpack encoding. Listpack is designed for small collections and '
            f'becomes inefficient for larger sets: O(N) per operation and higher '
            f'memory overhead per entry compared to skiplist at these sizes.'
        ),
        'config_fixed': True,
        'total_memory_before_bytes': total_mem_before,
        'total_memory_after_bytes': total_mem_after,
        'memory_savings_bytes': total_mem_before - total_mem_after,
    }

    with open('/app/audit_report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Audit complete: {len(sorted_sets)} sorted sets analysed")
    print(f"Suboptimal sets found: {len(suboptimal_keys)}")
    print(f"Theoretical skiplist overhead: {theory['raw_bytes']} bytes/entry "
          f"(allocator-adjusted: {theory['allocator_adjusted_bytes']})")
    print(f"Config fixed: zset-max-listpack-entries = 128")
    print(f"Memory before: {total_mem_before}, after: {total_mem_after}, "
          f"savings: {total_mem_before - total_mem_after}")
    print(f"Report written to /app/audit_report.json")


if __name__ == '__main__':
    main()
