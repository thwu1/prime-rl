#!/usr/bin/env python3
"""
Reference solver for the KVCache System Optimization task.
"""
import json
import sqlite3
from collections import defaultdict

DB_PATH = "/app/cache_state.db"
CONFIG_PATH = "/app/config.json"
TRACE_PATH = "/app/upcoming_requests.json"
RESULTS_PATH = "/app/results.json"


def main():
    # Load config
    with open(CONFIG_PATH) as f:
        config = json.load(f)

    NOW = config["current_time_ms"]
    ZOMBIE_TIMEOUT = config["zombie_timeout_ms"]
    SOFT_PIN_TTL = config["soft_pin_ttl_ms"]
    MAX_UTIL = config["target_max_node_utilization"]

    # Load trace
    with open(TRACE_PATH) as f:
        trace = json.load(f)

    # Connect to DB (read-only via backup)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # ----------------------------------------------------------------
    # 1. Diagnostics
    # ----------------------------------------------------------------

    # Zombie blocks: status='init' with put_start_time older than timeout
    zombie_threshold = NOW - ZOMBIE_TIMEOUT
    zombies = conn.execute(
        "SELECT block_id, node_id FROM blocks "
        "WHERE status='init' AND put_start_time IS NOT NULL AND put_start_time < ?",
        (zombie_threshold,),
    ).fetchall()
    zombie_ids = sorted(r["block_id"] for r in zombies)

    # Expired soft pins
    pin_threshold = NOW - SOFT_PIN_TTL
    expired_pins = conn.execute(
        "SELECT block_id, node_id FROM blocks "
        "WHERE pin_type='soft' AND last_accessed < ?",
        (pin_threshold,),
    ).fetchall()
    expired_pin_ids = sorted(r["block_id"] for r in expired_pins)

    # Orphaned prefix chains
    orphans = conn.execute("""
        SELECT pc.hash_id FROM prefix_chains pc
        WHERE pc.parent_hash_id IS NOT NULL
          AND pc.parent_hash_id NOT IN (SELECT hash_id FROM prefix_chains)
    """).fetchall()
    orphan_ids = sorted(r["hash_id"] for r in orphans)

    # Node utilisation
    nodes = conn.execute("SELECT node_id, node_type, capacity_blocks FROM nodes").fetchall()
    node_info = {r["node_id"]: dict(r) for r in nodes}
    counts = {}
    for nid in node_info:
        cnt = conn.execute(
            "SELECT COUNT(*) as c FROM blocks WHERE node_id=?", (nid,)
        ).fetchone()["c"]
        counts[nid] = cnt

    overloaded = sorted(
        n for n in node_info
        if counts.get(n, 0) / node_info[n]["capacity_blocks"] > MAX_UTIL
    )
    underloaded = sorted(
        n for n in node_info
        if counts.get(n, 0) / node_info[n]["capacity_blocks"] < 0.40
    )

    # ----------------------------------------------------------------
    # 2. Cleanup actions
    # ----------------------------------------------------------------
    cleanup = []
    for bid in zombie_ids:
        cleanup.append({"action": "remove_zombie", "block_id": bid})
    for bid in expired_pin_ids:
        cleanup.append({"action": "clear_soft_pin", "block_id": bid})

    # ----------------------------------------------------------------
    # 3. Rebalance plan
    # ----------------------------------------------------------------
    rebalance = []

    # Evict duplicate replicas on the same node (keep newest, evict rest)
    dupes = conn.execute("""
        SELECT hash_id, node_id, COUNT(*) as cnt
        FROM blocks
        WHERE status='complete'
        GROUP BY hash_id, node_id
        HAVING cnt > 1
    """).fetchall()

    for d in dupes:
        extras = conn.execute(
            "SELECT block_id FROM blocks "
            "WHERE hash_id=? AND node_id=? AND status='complete' "
            "ORDER BY last_accessed DESC LIMIT -1 OFFSET 1",
            (d["hash_id"], d["node_id"]),
        ).fetchall()
        for e in extras:
            rebalance.append({"action": "evict", "block_id": e["block_id"]})

    # ----------------------------------------------------------------
    # 4. Build cache-hit index for scheduling
    # ----------------------------------------------------------------
    # Map: (hash_id, node_id) -> exists as complete block
    prefill_nodes = sorted(
        n for n in node_info if node_info[n]["node_type"] == "prefill"
    )
    decode_node_list = sorted(
        n for n in node_info if node_info[n]["node_type"] == "decode"
    )

    # Build hash->set(nodes) index for complete blocks
    hash_node_rows = conn.execute(
        "SELECT DISTINCT hash_id, node_id FROM blocks WHERE status='complete'"
    ).fetchall()
    hash_to_nodes = defaultdict(set)
    for r in hash_node_rows:
        hash_to_nodes[r["hash_id"]].add(r["node_id"])

    # ----------------------------------------------------------------
    # 5. Schedule requests to maximise cache hits
    # ----------------------------------------------------------------
    schedule = []
    decode_idx = 0

    for req in trace:
        hash_ids = req["hash_ids"]
        best_node = None
        best_hits = -1

        for pn in prefill_nodes:
            hits = sum(1 for h in hash_ids if pn in hash_to_nodes.get(h, set()))
            if hits > best_hits:
                best_hits = hits
                best_node = pn

        misses = len(hash_ids) - best_hits
        dn = decode_node_list[decode_idx % len(decode_node_list)]
        decode_idx += 1

        schedule.append({
            "request_id": req["request_id"],
            "prefill_node": best_node,
            "decode_node": dn,
            "cache_hits": best_hits,
            "cache_misses": misses,
        })

    # ----------------------------------------------------------------
    # 6. Compute metrics
    # ----------------------------------------------------------------
    total_hits = sum(s["cache_hits"] for s in schedule)
    total_blocks = sum(s["cache_hits"] + s["cache_misses"] for s in schedule)
    hit_rate = total_hits / total_blocks if total_blocks > 0 else 0.0

    results = {
        "diagnostic": {
            "zombie_blocks": zombie_ids,
            "expired_soft_pins": expired_pin_ids,
            "orphaned_chains": orphan_ids,
            "overloaded_nodes": overloaded,
            "underloaded_nodes": underloaded,
        },
        "cleanup_actions": cleanup,
        "rebalance_plan": rebalance,
        "schedule": schedule,
        "metrics": {
            "total_requests": len(schedule),
            "cache_hit_rate": round(hit_rate, 4),
            "zombie_blocks_cleaned": len(zombie_ids),
            "soft_pins_cleared": len(expired_pin_ids),
        },
    }

    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2)

    print(f"Results written to {RESULTS_PATH}")
    print(f"  Zombies: {len(zombie_ids)}")
    print(f"  Expired pins: {len(expired_pin_ids)}")
    print(f"  Orphaned chains: {len(orphan_ids)}")
    print(f"  Overloaded: {overloaded}")
    print(f"  Underloaded: {underloaded}")
    print(f"  Duplicates evicted: {len(rebalance)}")
    print(f"  Cache hit rate: {hit_rate:.4f}")

    conn.close()


if __name__ == "__main__":
    main()
