#!/usr/bin/env python3
"""
KVCache Store Eviction Simulator — reference implementation.

"""

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(description="KVCache Store Simulator")
    parser.add_argument("--config", required=True, help="Path to config JSON")
    parser.add_argument("--trace", required=True, help="Path to trace JSONL")
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)
    with open(args.trace) as f:
        trace = [json.loads(line) for line in f if line.strip()]

    total_capacity = cfg["total_capacity_bytes"]
    lease_ttl = cfg["lease_ttl_sec"]
    soft_pin_ttl = cfg["soft_pin_ttl_sec"]
    allow_evict_sp = cfg.get("allow_evict_soft_pinned", True)

    # ---- state ----
    objects = {}  # key -> dict
    used_bytes = 0
    events = []
    stats = {
        "cache_hits": 0,
        "cache_misses": 0,
        "evictions_count": 0,
        "bytes_evicted": 0,
        "failed_puts": 0,
    }

    def _is_leased(obj, t):
        return obj["lease_expiry"] > t

    def _is_soft_pinned(obj, t):
        return obj["soft_pin_expiry"] > t

    def _try_evict(needed, t):
        """Plan and (atomically) execute eviction. Return True if freed enough."""
        nonlocal used_bytes

        # Phase 1: non-hard-pinned, non-leased, non-soft-pinned
        phase1 = []
        phase2 = []
        for key, obj in objects.items():
            if obj["hard_pin"]:
                continue
            if _is_leased(obj, t):
                continue
            if _is_soft_pinned(obj, t):
                phase2.append((key, obj))
            else:
                phase1.append((key, obj))

        phase1.sort(key=lambda x: (x[1]["last_access_time"], x[0]))
        phase2.sort(key=lambda x: (x[1]["last_access_time"], x[0]))

        # Greedy selection
        plan = []
        freed = 0
        for key, obj in phase1:
            plan.append(key)
            freed += obj["size"]
            if freed >= needed:
                break

        if freed < needed and allow_evict_sp:
            for key, obj in phase2:
                plan.append(key)
                freed += obj["size"]
                if freed >= needed:
                    break

        if freed < needed:
            return False  # atomic: don't evict anything

        # Execute evictions
        for key in plan:
            obj = objects.pop(key)
            used_bytes -= obj["size"]
            events.append({"t": t, "type": "eviction", "key": key, "freed": obj["size"]})
            stats["evictions_count"] += 1
            stats["bytes_evicted"] += obj["size"]
        return True

    # ---- process trace ----
    for op in trace:
        t = op["t"]
        op_type = op["op"]

        if op_type == "PUT":
            key = op["key"]
            size = op["size"]
            hard_pin = op.get("hard_pin", False)

            # Step 1: remove existing object with same key (unconditional)
            if key in objects:
                old = objects.pop(key)
                used_bytes -= old["size"]

            # Step 2-4: check capacity, evict if needed
            needed = used_bytes + size - total_capacity
            if needed > 0:
                if not _try_evict(needed, t):
                    stats["failed_puts"] += 1
                    events.append({"t": t, "type": "put_failed", "key": key})
                    continue

            # Step 5: store new object
            objects[key] = {
                "size": size,
                "hard_pin": hard_pin,
                "soft_pin_expiry": 0,
                "lease_expiry": 0,
                "last_access_time": t,
            }
            used_bytes += size

        elif op_type == "GET":
            key = op["key"]
            if key in objects:
                obj = objects[key]
                stats["cache_hits"] += 1
                obj["last_access_time"] = t
                obj["lease_expiry"] = max(obj["lease_expiry"], t + lease_ttl)
                if _is_soft_pinned(obj, t):
                    obj["soft_pin_expiry"] = t + soft_pin_ttl
            else:
                stats["cache_misses"] += 1

        elif op_type == "REMOVE":
            key = op["key"]
            if key in objects:
                obj = objects[key]
                if obj["hard_pin"] or _is_leased(obj, t):
                    events.append({"t": t, "type": "remove_failed", "key": key})
                else:
                    used_bytes -= obj["size"]
                    del objects[key]

        elif op_type == "SOFT_PIN":
            key = op["key"]
            if key in objects:
                objects[key]["soft_pin_expiry"] = t + soft_pin_ttl

    # ---- build output ----
    final_t = trace[-1]["t"] if trace else 0
    final_state = {}
    for key, obj in objects.items():
        final_state[key] = {
            "size": obj["size"],
            "hard_pin": obj["hard_pin"],
            "soft_pinned": _is_soft_pinned(obj, final_t),
            "leased": _is_leased(obj, final_t),
        }

    output = {
        "events": events,
        "stats": stats,
        "final_state": final_state,
        "final_used_bytes": used_bytes,
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
