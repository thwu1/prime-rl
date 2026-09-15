#!/usr/bin/env python3
"""
Oracle Database Performance Diagnostic Analyzer

Processes exported V$ dynamic performance view data to compute Oracle
performance metrics, interpret advisory views, and generate a structured
tuning report with ranked parameter recommendations.
"""


import csv
import json
import os

DATA_DIR = "/app/diagnostic_data"
OUTPUT = "/app/tuning_report.json"


def read_csv(filename):
    path = os.path.join(DATA_DIR, filename)
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def get_sysstat(rows, name):
    for row in rows:
        if row["statistic_name"].strip() == name:
            return float(row["value"])
    raise KeyError(f"Statistic not found: {name}")


def compute_metrics(sysstat, librarycache, pgastat, sgastat):
    # Buffer cache hit ratio:
    # 1 - (physical reads cache / (db block gets from cache + consistent gets from cache))
    phys_reads = get_sysstat(sysstat, "physical reads cache")
    db_block_gets = get_sysstat(sysstat, "db block gets from cache")
    consistent_gets = get_sysstat(sysstat, "consistent gets from cache")
    buffer_cache_hit_ratio = 1.0 - (phys_reads / (db_block_gets + consistent_gets))

    # Library cache hit ratio: sum(pinhits) / sum(pins)
    total_pins = sum(float(r["pins"]) for r in librarycache)
    total_pinhits = sum(float(r["pinhits"]) for r in librarycache)
    library_cache_hit_ratio = total_pinhits / total_pins if total_pins > 0 else 0.0

    # Hard parse ratio: parse count (hard) / parse count (total)
    parse_total = get_sysstat(sysstat, "parse count (total)")
    parse_hard = get_sysstat(sysstat, "parse count (hard)")
    hard_parse_ratio = parse_hard / parse_total if parse_total > 0 else 0.0

    # In-memory sort ratio: sorts (memory) / (sorts (memory) + sorts (disk))
    sorts_mem = get_sysstat(sysstat, "sorts (memory)")
    sorts_disk = get_sysstat(sysstat, "sorts (disk)")
    in_memory_sort_ratio = sorts_mem / (sorts_mem + sorts_disk) if (sorts_mem + sorts_disk) > 0 else 0.0

    # PGA cache hit percentage: directly from V$PGASTAT
    pga_cache_hit = None
    for row in pgastat:
        if "cache hit percentage" in row["name"].lower():
            pga_cache_hit = float(row["value"])
            break
    if pga_cache_hit is None:
        raise ValueError("PGA cache hit percentage not found in V$PGASTAT")

    # Shared pool free percentage: free memory / total shared pool bytes * 100
    sp_total = 0.0
    sp_free = 0.0
    for row in sgastat:
        if row["pool"].strip() == "shared pool":
            b = float(row["bytes"])
            sp_total += b
            if row["name"].strip() == "free memory":
                sp_free = b
    shared_pool_free_pct = (sp_free / sp_total * 100.0) if sp_total > 0 else 0.0

    return {
        "buffer_cache_hit_ratio": round(buffer_cache_hit_ratio, 6),
        "library_cache_hit_ratio": round(library_cache_hit_ratio, 6),
        "hard_parse_ratio": round(hard_parse_ratio, 6),
        "in_memory_sort_ratio": round(in_memory_sort_ratio, 6),
        "pga_cache_hit_pct": round(pga_cache_hit, 2),
        "shared_pool_free_pct": round(shared_pool_free_pct, 4),
    }


def find_optimal_db_cache(cache_advice):
    """Smallest size_for_estimate_mb where estd_physical_read_factor <= 0.50."""
    sorted_rows = sorted(cache_advice, key=lambda r: float(r["size_for_estimate_mb"]))
    for row in sorted_rows:
        if float(row["estd_physical_read_factor"]) <= 0.50:
            return int(float(row["size_for_estimate_mb"]))
    return int(float(sorted_rows[-1]["size_for_estimate_mb"]))


def find_optimal_pga_target(pga_advice):
    """Smallest pga_target_for_estimate_mb where estd_overalloc_count == 0."""
    sorted_rows = sorted(pga_advice, key=lambda r: float(r["pga_target_for_estimate_mb"]))
    for row in sorted_rows:
        if int(float(row["estd_overalloc_count"])) == 0:
            return int(float(row["pga_target_for_estimate_mb"]))
    return int(float(sorted_rows[-1]["pga_target_for_estimate_mb"]))


def get_top_wait_events(events, top_n=5):
    """Top N non-idle wait events by time_waited_micro, converted to seconds."""
    non_idle = [r for r in events if r["wait_class"].strip() != "Idle"]
    by_time = sorted(non_idle, key=lambda r: float(r["time_waited_micro"]), reverse=True)
    return [
        {
            "event": row["event"].strip(),
            "time_waited_seconds": float(row["time_waited_micro"]) / 1_000_000,
        }
        for row in by_time[:top_n]
    ]


def get_param(params, name):
    for row in params:
        if row["name"].strip().lower() == name.lower():
            return row["value"].strip()
    return "unknown"


def generate_recommendations(metrics, params, optimal_cache_mb, optimal_pga_mb):
    recs = []

    # 1. Hard parse ratio > 0.5 + shared pool latch contention -> CURSOR_SHARING
    if metrics["hard_parse_ratio"] > 0.5:
        recs.append({
            "rank": 1,
            "parameter": "cursor_sharing",
            "current_value": get_param(params, "cursor_sharing"),
            "recommended_value": "FORCE",
        })

    # 2. Shared pool free < 10% -> increase SHARED_POOL_SIZE
    if metrics["shared_pool_free_pct"] < 10.0:
        cur_bytes = float(get_param(params, "shared_pool_size"))
        cur_mb = int(cur_bytes) // (1024 * 1024)
        new_mb = cur_mb * 2
        recs.append({
            "rank": 2,
            "parameter": "shared_pool_size",
            "current_value": f"{cur_mb}M",
            "recommended_value": f"{new_mb}M",
        })

    # 3. Buffer cache undersized -> increase DB_CACHE_SIZE
    cur_cache_bytes = float(get_param(params, "db_cache_size"))
    cur_cache_mb = int(cur_cache_bytes) // (1024 * 1024)
    if optimal_cache_mb > cur_cache_mb:
        recs.append({
            "rank": 3,
            "parameter": "db_cache_size",
            "current_value": f"{cur_cache_mb}M",
            "recommended_value": f"{optimal_cache_mb}M",
        })

    # 4. PGA undersized -> increase PGA_AGGREGATE_TARGET
    cur_pga_bytes = float(get_param(params, "pga_aggregate_target"))
    cur_pga_mb = int(cur_pga_bytes) // (1024 * 1024)
    if optimal_pga_mb > cur_pga_mb:
        recs.append({
            "rank": 4,
            "parameter": "pga_aggregate_target",
            "current_value": f"{cur_pga_mb}M",
            "recommended_value": f"{optimal_pga_mb}M",
        })

    return recs


def main():
    sysstat = read_csv("v_sysstat.csv")
    librarycache = read_csv("v_librarycache.csv")
    cache_advice = read_csv("v_db_cache_advice.csv")
    pga_advice = read_csv("v_pga_target_advice.csv")
    pgastat = read_csv("v_pgastat.csv")
    sgastat = read_csv("v_sgastat.csv")
    events = read_csv("v_system_event.csv")
    params = read_csv("v_parameter.csv")

    metrics = compute_metrics(sysstat, librarycache, pgastat, sgastat)
    optimal_cache = find_optimal_db_cache(cache_advice)
    optimal_pga = find_optimal_pga_target(pga_advice)
    top_waits = get_top_wait_events(events)
    recommendations = generate_recommendations(metrics, params, optimal_cache, optimal_pga)

    report = {
        "metrics": metrics,
        "optimal_db_cache_size_mb": optimal_cache,
        "optimal_pga_target_mb": optimal_pga,
        "top_wait_events": top_waits,
        "recommendations": recommendations,
    }

    with open(OUTPUT, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to {OUTPUT}")


if __name__ == "__main__":
    main()
