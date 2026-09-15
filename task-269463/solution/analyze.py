#!/usr/bin/env python3
"""
Oracle Database Performance Diagnostic Analyzer

Parses V$ view exports, execution plans, and alert log from /app/diagnostics/
and produces structured diagnosis JSON and SQL recommendations.
"""

import csv
import json
import os
import re

DIAG_DIR = "/app/diagnostics"
OUTPUT_DIR = "/app/analysis"

IDLE_WAIT_CLASSES = {"Idle"}


def parse_csv(filename):
    """Parse a CSV file and return list of dicts."""
    path = os.path.join(DIAG_DIR, filename)
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def compute_buffer_cache_hit_ratio(sysstat_rows):
    """1 - (physical reads cache / (consistent gets from cache + db block gets from cache))"""
    stats = {}
    for row in sysstat_rows:
        stats[row["name"].strip()] = int(row["value"])

    consistent_gets = stats["consistent gets from cache"]
    db_block_gets = stats["db block gets from cache"]
    physical_reads = stats["physical reads cache"]

    return 1.0 - (physical_reads / (consistent_gets + db_block_gets))


def compute_hard_parse_ratio(sysstat_rows):
    """parse count (hard) / parse count (total)"""
    stats = {}
    for row in sysstat_rows:
        stats[row["name"].strip()] = int(row["value"])

    hard = stats["parse count (hard)"]
    total = stats["parse count (total)"]
    return hard / total


def compute_disk_sort_ratio(sysstat_rows):
    """sorts (disk) / (sorts (memory) + sorts (disk))"""
    stats = {}
    for row in sysstat_rows:
        stats[row["name"].strip()] = int(row["value"])

    disk = stats["sorts (disk)"]
    memory = stats["sorts (memory)"]
    return disk / (memory + disk)


def compute_library_cache_hit_ratio(libcache_rows):
    """sum(pinhits) / sum(pins) across all namespaces"""
    total_pins = 0
    total_pinhits = 0
    for row in libcache_rows:
        total_pins += int(row["pins"])
        total_pinhits += int(row["pinhits"])

    if total_pins == 0:
        return 0.0
    return total_pinhits / total_pins


def get_top_wait_events(system_event_rows, top_n=5):
    """Get top N non-idle wait events by total wait time."""
    non_idle = []
    for row in system_event_rows:
        wait_class = row["wait_class"].strip()
        if wait_class in IDLE_WAIT_CLASSES:
            continue
        event = row["event"].strip()
        total_wait_cs = int(row["time_waited_cs"])
        waits = int(row["total_waits"])
        avg_wait_cs = round(float(row["average_wait_cs"]), 2)
        non_idle.append({
            "event": event,
            "total_wait_time_cs": total_wait_cs,
            "waits": waits,
            "avg_wait_cs": avg_wait_cs,
        })

    non_idle.sort(key=lambda x: x["total_wait_time_cs"], reverse=True)
    return non_idle[:top_n]


def analyze_db_cache_advice(advice_rows):
    """Find optimal cache size from knee-of-curve analysis.

    Uses a diminishing-returns heuristic: walk the advisory points above
    the current size and stop when the step-to-step improvement in
    estd_physical_read_factor drops below 0.05.  The knee is the last
    size whose marginal improvement is still worthwhile.
    """
    points = []
    for row in advice_rows:
        if row["name"].strip() != "DEFAULT":
            continue
        size_mb = int(row["size_for_estimate"])
        factor = float(row["estd_physical_read_factor"])
        reads = int(row["estd_physical_reads"])
        points.append((size_mb, factor, reads))

    points.sort(key=lambda x: x[0])

    # Find the current size (factor closest to 1.00)
    current_idx = 0
    for i, (size, factor, _) in enumerate(points):
        if abs(factor - 1.0) < 0.01:
            current_idx = i
            break

    # Walk sizes above current; find where improvement flattens
    best_size = points[current_idx][0]
    for i in range(current_idx + 1, len(points) - 1):
        curr_factor = points[i][1]
        next_factor = points[i + 1][1]
        improvement = curr_factor - next_factor

        # The knee: marginal improvement drops below threshold
        if improvement < 0.05:
            best_size = points[i][0]
            break
    else:
        best_size = points[-1][0]

    return best_size


def analyze_pga_advice(pga_rows):
    """Find minimum PGA target where overalloc_count = 0."""
    for row in pga_rows:
        overalloc = int(row["estd_overalloc_count"])
        if overalloc == 0:
            target_bytes = int(row["pga_target_for_estimate"])
            return target_bytes // (1024 * 1024)
    # If none found, return the largest
    return int(pga_rows[-1]["pga_target_for_estimate"]) // (1024 * 1024)


def count_ora_04031(alert_log_path):
    """Count ORA-04031 errors in alert log."""
    count = 0
    with open(alert_log_path) as f:
        for line in f:
            if "ORA-04031:" in line:
                count += 1
    return count


def identify_problematic_sql(exec_plans_path):
    """Identify SQL IDs with problematic execution plans."""
    problematic = []
    with open(exec_plans_path) as f:
        content = f.read()

    # Split into individual plan sections
    sections = re.split(r"--- SQL_ID: (\S+) ---", content)

    for i in range(1, len(sections), 2):
        sql_id = sections[i]
        plan_text = sections[i + 1] if i + 1 < len(sections) else ""

        is_problematic = False

        # Full table scan on a large table with filter predicates
        if "TABLE ACCESS FULL" in plan_text and "filter(" in plan_text.lower():
            for line in plan_text.split("\n"):
                if "TABLE ACCESS FULL" in line:
                    nums = re.findall(r"\d+", line)
                    for n in nums:
                        if int(n) >= 10000:
                            is_problematic = True
                            break
                    if is_problematic:
                        break

        # Cartesian join
        if "CARTESIAN" in plan_text:
            is_problematic = True

        if is_problematic:
            problematic.append(sql_id)

    return problematic


def determine_cursor_sharing(sysstat_rows):
    """Determine recommended CURSOR_SHARING based on hard parse ratio."""
    ratio = compute_hard_parse_ratio(sysstat_rows)
    # High hard parse ratio (>20%) suggests literal SQL; recommend FORCE
    if ratio > 0.20:
        return "FORCE"
    return "EXACT"


def generate_recommendations(diagnosis, params):
    """Generate ALTER SYSTEM SET commands."""
    lines = [
        "-- Oracle Database Performance Tuning Recommendations",
        "-- Generated from diagnostic data analysis",
        "",
    ]

    db_cache_mb = diagnosis["recommended_db_cache_size_mb"]
    db_cache_bytes = db_cache_mb * 1024 * 1024
    lines.append(
        f"ALTER SYSTEM SET db_cache_size = {db_cache_bytes} SCOPE=SPFILE;"
    )
    lines.append(
        f"-- Increase buffer cache from 256MB to {db_cache_mb}MB (current hit ratio: "
        f"{diagnosis['buffer_cache_hit_ratio']:.4f}, target: >0.95)"
    )
    lines.append("")

    pga_mb = diagnosis["recommended_pga_target_mb"]
    pga_bytes = pga_mb * 1024 * 1024
    lines.append(
        f"ALTER SYSTEM SET pga_aggregate_target = {pga_bytes} SCOPE=SPFILE;"
    )
    lines.append(
        f"-- Increase PGA from 192MB to {pga_mb}MB (eliminate overallocation, "
        f"reduce disk sorts from {diagnosis['disk_sort_ratio']:.1%})"
    )
    lines.append("")

    lines.append(
        "ALTER SYSTEM SET cursor_sharing = 'FORCE' SCOPE=SPFILE;"
    )
    lines.append(
        f"-- Enable cursor sharing to reduce hard parse ratio from "
        f"{diagnosis['hard_parse_ratio']:.1%} (target: <5%)"
    )
    lines.append("")

    # Recommend increasing shared pool to address ORA-04031
    lines.append(
        "ALTER SYSTEM SET shared_pool_size = 536870912 SCOPE=SPFILE;"
    )
    lines.append(
        f"-- Increase shared pool from 320MB to 512MB to address "
        f"{diagnosis['ora_04031_count']} ORA-04031 errors"
    )
    lines.append("")

    # Recommend increasing session_cached_cursors
    lines.append(
        "ALTER SYSTEM SET session_cached_cursors = 200 SCOPE=SPFILE;"
    )
    lines.append(
        "-- Increase session cursor cache to reduce soft parse overhead"
    )
    lines.append("")

    # Recommend enabling SGA_TARGET for automatic SGA management
    lines.append(
        "ALTER SYSTEM SET sga_target = 1073741824 SCOPE=SPFILE;"
    )
    lines.append(
        "-- Enable Automatic Shared Memory Management with 1GB SGA target"
    )

    return "\n".join(lines)


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Parse all diagnostic files
    sysstat = parse_csv("v_sysstat.csv")
    libcache = parse_csv("v_librarycache.csv")
    system_event = parse_csv("v_system_event.csv")
    db_cache_advice = parse_csv("v_db_cache_advice.csv")
    pga_advice = parse_csv("v_pga_target_advice.csv")
    params = parse_csv("instance_parameters.csv")

    # Compute metrics
    buffer_hit = compute_buffer_cache_hit_ratio(sysstat)
    hard_parse = compute_hard_parse_ratio(sysstat)
    lib_cache_hit = compute_library_cache_hit_ratio(libcache)
    disk_sort = compute_disk_sort_ratio(sysstat)
    top_events = get_top_wait_events(system_event)
    db_cache_rec = analyze_db_cache_advice(db_cache_advice)
    pga_rec = analyze_pga_advice(pga_advice)
    cursor_sharing = determine_cursor_sharing(sysstat)
    ora_count = count_ora_04031(os.path.join(DIAG_DIR, "alert_log.txt"))
    problematic = identify_problematic_sql(
        os.path.join(DIAG_DIR, "execution_plans.txt")
    )

    diagnosis = {
        "buffer_cache_hit_ratio": round(buffer_hit, 6),
        "hard_parse_ratio": round(hard_parse, 6),
        "library_cache_hit_ratio": round(lib_cache_hit, 6),
        "disk_sort_ratio": round(disk_sort, 6),
        "top_wait_events": top_events,
        "recommended_db_cache_size_mb": db_cache_rec,
        "recommended_pga_target_mb": pga_rec,
        "recommended_cursor_sharing": cursor_sharing,
        "ora_04031_count": ora_count,
        "problematic_sql_ids": problematic,
    }

    # Write diagnosis.json
    with open(os.path.join(OUTPUT_DIR, "diagnosis.json"), "w") as f:
        json.dump(diagnosis, f, indent=2)

    # Write recommendations.sql
    recs = generate_recommendations(diagnosis, params)
    with open(os.path.join(OUTPUT_DIR, "recommendations.sql"), "w") as f:
        f.write(recs)

    print("Analysis complete.")
    print(f"  Buffer cache hit ratio: {buffer_hit:.4f}")
    print(f"  Hard parse ratio: {hard_parse:.4f}")
    print(f"  Library cache hit ratio: {lib_cache_hit:.4f}")
    print(f"  Disk sort ratio: {disk_sort:.4f}")
    print(f"  Recommended DB cache: {db_cache_rec}MB")
    print(f"  Recommended PGA target: {pga_rec}MB")
    print(f"  Recommended cursor sharing: {cursor_sharing}")
    print(f"  ORA-04031 count: {ora_count}")
    print(f"  Problematic SQL IDs: {problematic}")


if __name__ == "__main__":
    main()
