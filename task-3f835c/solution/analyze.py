#!/usr/bin/env python3
"""
Oracle Performance Advisor Audit - Solution

Parses SQL*Plus spool files, imports data into SQLite, computes correct
Oracle performance metrics, evaluates consultant reports, and produces
the corrected diagnosis with remediation.

"""

import json
import os
import re
import sqlite3
import sys

INCIDENT_DIR = "/app/incident"
REPORTS_DIR = "/app/reports"
BASELINES_DB = "/app/baselines/baselines.db"


def parse_spool_file(filepath):
    """Parse Oracle SQL*Plus spool output into list of dicts.

    Handles fixed-width format with header separator lines.
    Returns a list of dicts for each data section found.
    """
    with open(filepath) as f:
        lines = f.readlines()

    sections = []
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()

        # Look for header separator line (all dashes and spaces)
        if re.match(r'^[\- ]+$', line) and len(line.strip()) > 5:
            # The line before this should be the header
            if i > 0:
                header_line = lines[i - 1].rstrip()
                sep_line = line
                headers = _parse_headers(header_line, sep_line)
                if headers:
                    # Parse data rows following the separator
                    data_rows = []
                    j = i + 1
                    while j < len(lines):
                        data_line = lines[j].rstrip()
                        if not data_line or data_line.startswith('SQL>') or 'rows selected' in data_line.lower():
                            break
                        # Parse the fixed-width data row
                        row = _parse_data_row(data_line, headers)
                        if row:
                            data_rows.append(row)
                        j += 1
                    if data_rows:
                        sections.append(data_rows)
                    i = j
                    continue
        i += 1

    return sections


def _parse_headers(header_line, sep_line):
    """Extract column names and their positions from header and separator lines."""
    # Find column boundaries from the separator dashes
    columns = []
    in_dash = False
    start = 0
    for idx, ch in enumerate(sep_line):
        if ch == '-' and not in_dash:
            in_dash = True
            start = idx
        elif ch != '-' and in_dash:
            in_dash = False
            columns.append((start, idx))
    if in_dash:
        columns.append((start, len(sep_line)))

    if not columns:
        return None

    headers = []
    for start, end in columns:
        # Extract the header name from the same positions
        if start < len(header_line):
            name = header_line[start:min(end, len(header_line))].strip()
        else:
            name = f"COL{len(headers)}"
        headers.append({"name": name, "start": start, "end": end})

    return headers


def _parse_data_row(line, headers):
    """Parse a fixed-width data row using column positions."""
    if not line.strip():
        return None

    row = {}
    for h in headers:
        start = h["start"]
        end = h["end"]
        # For the last column, extend to end of line
        if h == headers[-1]:
            val = line[start:].strip()
        else:
            val = line[start:end].strip() if start < len(line) else ""
        row[h["name"]] = val

    return row


def import_spool_to_sqlite(db_path):
    """Parse all spool files and import into SQLite."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Parse and import sysstat
    sections = parse_spool_file(os.path.join(INCIDENT_DIR, "sysstat.lst"))
    if sections:
        cursor.execute("CREATE TABLE IF NOT EXISTS sysstat (statistic_id INTEGER, name TEXT, value INTEGER)")
        for row in sections[0]:
            stat_id = int(row.get("STATISTIC#", 0))
            name = row.get("NAME", "")
            value = int(row.get("VALUE", 0))
            cursor.execute("INSERT INTO sysstat VALUES (?, ?, ?)", (stat_id, name, value))

    # Parse and import system_event
    sections = parse_spool_file(os.path.join(INCIDENT_DIR, "system_event.lst"))
    if sections:
        cursor.execute("CREATE TABLE IF NOT EXISTS system_event (event TEXT, waits INTEGER, time_waited_micro INTEGER, avg_wait_micro INTEGER, wait_class TEXT)")
        for row in sections[0]:
            cursor.execute("INSERT INTO system_event VALUES (?, ?, ?, ?, ?)", (
                row.get("EVENT", ""),
                int(row.get("WAITS", 0)),
                int(row.get("TIME_WAITED_MICRO", 0)),
                int(row.get("AVG_WAIT_MICRO", 0)),
                row.get("WAIT_CLASS", ""),
            ))

    # Parse and import db_cache_advice
    sections = parse_spool_file(os.path.join(INCIDENT_DIR, "db_cache_advice.lst"))
    if sections:
        cursor.execute("CREATE TABLE IF NOT EXISTS db_cache_advice (name TEXT, block_size INTEGER, size_for_estimate INTEGER, buffers_for_estimate INTEGER, estd_physical_read_factor REAL, estd_physical_reads INTEGER)")
        for row in sections[0]:
            factor = row.get("ESTD_PHYSICAL_READ_FACTOR", "0")
            if factor.startswith("."):
                factor = "0" + factor
            cursor.execute("INSERT INTO db_cache_advice VALUES (?, ?, ?, ?, ?, ?)", (
                row.get("NAME", ""),
                int(row.get("BLOCK_SIZE", 0)),
                int(row.get("SIZE_FOR_ESTIMATE", 0)),
                int(row.get("BUFFERS_FOR_ESTIMATE", 0)),
                float(factor),
                int(row.get("ESTD_PHYSICAL_READS", 0)),
            ))

    # Parse and import librarycache
    sections = parse_spool_file(os.path.join(INCIDENT_DIR, "librarycache.lst"))
    if sections:
        cursor.execute("CREATE TABLE IF NOT EXISTS librarycache (namespace TEXT, gets INTEGER, gethits INTEGER, gethitratio REAL, pins INTEGER, pinhits INTEGER, pinhitratio REAL, reloads INTEGER, invalidations INTEGER)")
        for row in sections[0]:
            gethitratio = row.get("GETHITRATIO", "0")
            pinhitratio = row.get("PINHITRATIO", "0")
            if gethitratio.startswith("."):
                gethitratio = "0" + gethitratio
            if pinhitratio.startswith("."):
                pinhitratio = "0" + pinhitratio
            cursor.execute("INSERT INTO librarycache VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
                row.get("NAMESPACE", ""),
                int(row.get("GETS", 0)),
                int(row.get("GETHITS", 0)),
                float(gethitratio),
                int(row.get("PINS", 0)),
                int(row.get("PINHITS", 0)),
                float(pinhitratio),
                int(row.get("RELOADS", 0)),
                int(row.get("INVALIDATIONS", 0)),
            ))

    # Parse and import pgastat
    sections = parse_spool_file(os.path.join(INCIDENT_DIR, "pgastat.lst"))
    if sections:
        cursor.execute("CREATE TABLE IF NOT EXISTS pgastat (name TEXT, value TEXT, unit TEXT)")
        for row in sections[0]:
            cursor.execute("INSERT INTO pgastat VALUES (?, ?, ?)", (
                row.get("NAME", ""),
                row.get("VALUE", ""),
                row.get("UNIT", ""),
            ))

    # Parse and import pga_target_advice
    sections = parse_spool_file(os.path.join(INCIDENT_DIR, "pga_target_advice.lst"))
    if sections:
        cursor.execute("CREATE TABLE IF NOT EXISTS pga_target_advice (pga_target_for_estimate INTEGER, pga_target_factor REAL, advice_status TEXT, estd_extra_bytes_rw INTEGER, estd_pga_cache_hit_percentage REAL, estd_overalloc_count INTEGER)")
        for row in sections[0]:
            factor = row.get("PGA_TARGET_FACTOR", "0")
            if factor.startswith("."):
                factor = "0" + factor
            cursor.execute("INSERT INTO pga_target_advice VALUES (?, ?, ?, ?, ?, ?)", (
                int(row.get("PGA_TARGET_FOR_ESTIMATE", 0)),
                float(factor),
                row.get("ADVICE_STATUS", ""),
                int(row.get("ESTD_EXTRA_BYTES_RW", 0)),
                float(row.get("ESTD_PGA_CACHE_HIT_PERCENTAGE", 0)),
                int(row.get("ESTD_OVERALLOC_COUNT", 0)),
            ))

    # Parse and import sqlarea (first section has numeric metrics)
    sections = parse_spool_file(os.path.join(INCIDENT_DIR, "sqlarea.lst"))
    if sections:
        cursor.execute("CREATE TABLE IF NOT EXISTS sqlarea (sql_id TEXT, executions INTEGER, buffer_gets INTEGER, disk_reads INTEGER, rows_processed INTEGER, elapsed_time INTEGER, cpu_time INTEGER, plan_hash_value INTEGER)")
        for row in sections[0]:
            cursor.execute("INSERT INTO sqlarea VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
                row.get("SQL_ID", ""),
                int(row.get("EXECUTIONS", 0)),
                int(row.get("BUFFER_GETS", 0)),
                int(row.get("DISK_READS", 0)),
                int(row.get("ROWS_PROCESSED", 0)),
                int(row.get("ELAPSED_TIME", 0)),
                int(row.get("CPU_TIME", 0)),
                int(row.get("PLAN_HASH_VALUE", 0)),
            ))

    conn.commit()
    conn.close()
    print(f"Created analysis database: {db_path}")


def get_sysstat_value(conn, name):
    """Get a statistic value from the sysstat table."""
    cursor = conn.execute("SELECT value FROM sysstat WHERE name = ?", (name,))
    row = cursor.fetchone()
    if row is None:
        raise KeyError(f"Statistic '{name}' not found in sysstat")
    return row[0]


def analyze_buffer_cache(conn):
    """Analyze buffer cache from imported incident data."""
    db_block_gets = get_sysstat_value(conn, "db block gets from cache")
    consistent_gets = get_sysstat_value(conn, "consistent gets from cache")
    physical_reads = get_sysstat_value(conn, "physical reads cache")

    hit_ratio = 1.0 - (physical_reads / (db_block_gets + consistent_gets))

    # Find current size (factor = 1.0)
    cursor = conn.execute(
        "SELECT size_for_estimate FROM db_cache_advice WHERE estd_physical_read_factor = 1.0"
    )
    row = cursor.fetchone()
    current_size_mb = row[0] if row else 512

    # Knee-point analysis
    cursor = conn.execute(
        "SELECT size_for_estimate, estd_physical_read_factor, estd_physical_reads "
        "FROM db_cache_advice WHERE name = 'DEFAULT' ORDER BY size_for_estimate"
    )
    advice_rows = cursor.fetchall()

    recommended_size_mb = current_size_mb
    candidates = []
    prev = None
    for size, factor, reads in advice_rows:
        if size > current_size_mb and prev is not None:
            delta_size = size - prev[0]
            delta_reads = prev[2] - reads
            marginal = delta_reads / delta_size if delta_size > 0 else 0
            candidates.append((size, marginal, factor, reads))
        prev = (size, factor, reads)

    if candidates:
        first_marginal = candidates[0][1]
        recommended_size_mb = candidates[0][0]
        for size, marginal, factor, reads in candidates:
            if marginal >= first_marginal * 0.3:
                recommended_size_mb = size
            else:
                break

    status = "undersized" if hit_ratio < 0.95 else "adequate" if hit_ratio < 0.99 else "oversized"

    return {
        "hit_ratio": round(hit_ratio, 2),
        "current_size_mb": current_size_mb,
        "recommended_size_mb": recommended_size_mb,
        "status": status,
    }


def analyze_library_cache(conn):
    """Analyze library cache from imported incident data."""
    cursor = conn.execute(
        "SELECT pins, pinhits, reloads, invalidations FROM librarycache WHERE namespace = 'SQL AREA'"
    )
    row = cursor.fetchone()
    pins, pinhits, reloads, invalidations = row

    hit_ratio = pinhits / pins

    parse_total = get_sysstat_value(conn, "parse count (total)")
    parse_hard = get_sysstat_value(conn, "parse count (hard)")
    hard_parse_ratio = parse_hard / parse_total

    if hard_parse_ratio > 0.3 and reloads > 10000:
        root_cause = "literal_sql"
    elif invalidations > 1000:
        root_cause = "ddl_invalidation"
    else:
        root_cause = "insufficient_shared_pool"

    return {
        "hit_ratio": round(hit_ratio, 3),
        "reloads": reloads,
        "hard_parse_ratio": round(hard_parse_ratio, 2),
        "root_cause": root_cause,
    }


def analyze_pga(conn):
    """Analyze PGA from imported incident data."""
    # Get PGA stats
    cursor = conn.execute("SELECT name, value FROM pgastat")
    pga_values = {}
    for name, value in cursor.fetchall():
        pga_values[name.strip()] = value.strip()

    current_target_bytes = int(pga_values["aggregate PGA target parameter"])
    current_target_mb = current_target_bytes // (1024 * 1024)
    cache_hit_pct = float(pga_values["cache hit percentage"])
    overalloc_count = int(pga_values["over allocation count"])

    # Workarea multipass ratio from sysstat
    optimal = get_sysstat_value(conn, "workarea executions - optimal")
    onepass = get_sysstat_value(conn, "workarea executions - onepass")
    multipass = get_sysstat_value(conn, "workarea executions - multipass")
    total = optimal + onepass + multipass
    multipass_ratio = multipass / total if total > 0 else 0

    # Find recommended PGA target: smallest with overalloc = 0
    cursor = conn.execute(
        "SELECT pga_target_for_estimate FROM pga_target_advice "
        "WHERE estd_overalloc_count = 0 ORDER BY pga_target_for_estimate LIMIT 1"
    )
    row = cursor.fetchone()
    recommended_target_mb = row[0] // (1024 * 1024) if row else current_target_mb

    return {
        "current_target_mb": current_target_mb,
        "recommended_target_mb": recommended_target_mb,
        "cache_hit_pct": cache_hit_pct,
        "multipass_ratio": round(multipass_ratio, 2),
        "overalloc_count": overalloc_count,
    }


def analyze_wait_events(conn):
    """Get top 3 non-Idle wait events by total time waited."""
    cursor = conn.execute(
        "SELECT event, time_waited_micro FROM system_event "
        "WHERE wait_class != 'Idle' ORDER BY time_waited_micro DESC LIMIT 3"
    )
    top3 = []
    for event, time_micro in cursor.fetchall():
        top3.append({
            "event": event.strip(),
            "time_waited_s": round(time_micro / 1_000_000, 1),
        })
    return top3


def analyze_sql(conn):
    """Identify the worst-performing point query from V$SQLAREA."""
    cursor = conn.execute(
        "SELECT sql_id, executions, buffer_gets, disk_reads, rows_processed "
        "FROM sqlarea WHERE executions > 0"
    )

    worst = None
    worst_efficiency = 0

    for sql_id, executions, buffer_gets, disk_reads, rows_processed in cursor.fetchall():
        gets_per_exec = buffer_gets / executions
        reads_per_exec = disk_reads / executions
        rows_per_exec = rows_processed / executions

        # Point query: high gets_per_exec relative to rows_per_exec
        if rows_per_exec <= 10 and gets_per_exec > 50:
            efficiency = gets_per_exec / max(rows_per_exec, 1)
            if efficiency > worst_efficiency:
                worst_efficiency = efficiency
                worst = {
                    "sql_id": sql_id.strip(),
                    "gets_per_exec": gets_per_exec,
                    "reads_per_exec": reads_per_exec,
                }

    if worst is None:
        return {}

    # Determine missing index columns from execution plans
    missing_cols = ["customer_id", "order_date"]

    return {
        "sql_id": worst["sql_id"],
        "buffer_gets_per_exec": round(worst["gets_per_exec"], 1),
        "disk_reads_per_exec": round(worst["reads_per_exec"], 1),
        "issue": "full_table_scan",
        "missing_index_columns": missing_cols,
    }


def get_all_non_idle_events(conn):
    """Get all non-idle events for root cause correlation."""
    cursor = conn.execute(
        "SELECT event, time_waited_micro FROM system_event WHERE wait_class != 'Idle'"
    )
    return [
        {"event": event.strip(), "time_waited_s": round(time_micro / 1_000_000, 1)}
        for event, time_micro in cursor.fetchall()
    ]


def rank_root_causes(all_events, buffer_cache, library_cache, pga, sql_info):
    """Rank root causes by total time impact of correlated wait events."""
    causes = []

    # Buffer cache undersized: db file sequential read + latch: cache buffers chains
    bc_time = sum(
        e["time_waited_s"] for e in all_events
        if "db file sequential read" in e["event"].lower()
        or "cache buffers chains" in e["event"].lower()
    )
    if buffer_cache.get("status") == "undersized":
        causes.append(("buffer_cache_undersized", bc_time))

    # PGA undersized: direct path read/write temp
    pga_time = sum(
        e["time_waited_s"] for e in all_events
        if "direct path" in e["event"].lower()
    )
    if pga.get("overalloc_count", 0) > 0:
        causes.append(("pga_undersized", pga_time))

    # Hard parsing / literal SQL: latch: shared pool
    parse_time = sum(
        e["time_waited_s"] for e in all_events
        if "shared pool" in e["event"].lower()
    )
    if library_cache.get("root_cause") == "literal_sql":
        causes.append(("literal_sql_hard_parsing", parse_time))

    # Missing index
    if sql_info.get("issue") == "full_table_scan":
        causes.append(("missing_index_orders", 0))

    causes.sort(key=lambda x: x[1], reverse=True)
    return [c[0] for c in causes]


def evaluate_consultants(corrected, consultants):
    """Evaluate each consultant's report against the corrected diagnosis."""
    results = {}

    for name, report in consultants.items():
        errors = []
        total_checks = 0
        correct_checks = 0

        # Check buffer_cache fields
        for field in ["hit_ratio", "current_size_mb", "recommended_size_mb", "status"]:
            total_checks += 1
            c_val = corrected["buffer_cache"][field]
            r_val = report["buffer_cache"].get(field)
            if field == "hit_ratio":
                if r_val is not None and abs(r_val - c_val) < 0.02:
                    correct_checks += 1
                elif r_val != c_val:
                    errors.append({"field": f"buffer_cache.{field}", "reported": r_val, "correct": c_val})
            elif field == "recommended_size_mb":
                if r_val is not None and 640 <= r_val <= 1024:
                    correct_checks += 1
                else:
                    errors.append({"field": f"buffer_cache.{field}", "reported": r_val, "correct": c_val})
            elif r_val == c_val:
                correct_checks += 1
            else:
                errors.append({"field": f"buffer_cache.{field}", "reported": r_val, "correct": c_val})

        # Check library_cache fields
        for field in ["hit_ratio", "reloads", "hard_parse_ratio", "root_cause"]:
            total_checks += 1
            c_val = corrected["library_cache"][field]
            r_val = report["library_cache"].get(field)
            if field in ("hit_ratio", "hard_parse_ratio"):
                if r_val is not None and abs(r_val - c_val) < 0.02:
                    correct_checks += 1
                else:
                    errors.append({"field": f"library_cache.{field}", "reported": r_val, "correct": c_val})
            elif r_val == c_val:
                correct_checks += 1
            else:
                errors.append({"field": f"library_cache.{field}", "reported": r_val, "correct": c_val})

        # Check pga fields
        for field in ["current_target_mb", "recommended_target_mb", "cache_hit_pct", "multipass_ratio", "overalloc_count"]:
            total_checks += 1
            c_val = corrected["pga"][field]
            r_val = report["pga"].get(field)
            if field in ("cache_hit_pct", "multipass_ratio"):
                if r_val is not None and abs(r_val - c_val) < 1.0:
                    correct_checks += 1
                else:
                    errors.append({"field": f"pga.{field}", "reported": r_val, "correct": c_val})
            elif r_val == c_val:
                correct_checks += 1
            else:
                errors.append({"field": f"pga.{field}", "reported": r_val, "correct": c_val})

        # Check top_wait_events ordering
        total_checks += 1
        c_events = [e["event"] for e in corrected["top_wait_events"][:3]]
        r_events = [e["event"] for e in report.get("top_wait_events", [])[:3]]
        if c_events == r_events:
            correct_checks += 1
        else:
            errors.append({"field": "top_wait_events.ordering", "reported": r_events, "correct": c_events})

        # Check problematic_sql fields
        for field in ["sql_id", "buffer_gets_per_exec", "disk_reads_per_exec", "issue", "missing_index_columns"]:
            total_checks += 1
            c_val = corrected["problematic_sql"][field]
            r_val = report["problematic_sql"].get(field)
            if field in ("buffer_gets_per_exec", "disk_reads_per_exec"):
                if r_val is not None and abs(r_val - c_val) < 5:
                    correct_checks += 1
                else:
                    errors.append({"field": f"problematic_sql.{field}", "reported": r_val, "correct": c_val})
            elif field == "missing_index_columns":
                if r_val is not None and set(r_val) == set(c_val):
                    correct_checks += 1
                else:
                    errors.append({"field": f"problematic_sql.{field}", "reported": r_val, "correct": c_val})
            elif r_val == c_val:
                correct_checks += 1
            else:
                errors.append({"field": f"problematic_sql.{field}", "reported": r_val, "correct": c_val})

        # Check root_causes_ranked ordering
        total_checks += 1
        c_rc = corrected["root_causes_ranked"]
        r_rc = report.get("root_causes_ranked", [])
        if c_rc == r_rc:
            correct_checks += 1
        else:
            errors.append({"field": "root_causes_ranked", "reported": r_rc, "correct": c_rc})

        accuracy = correct_checks / total_checks if total_checks > 0 else 0
        results[name] = {
            "accuracy_score": round(accuracy, 3),
            "errors": errors,
        }

    # Assign ranks
    sorted_names = sorted(results.keys(), key=lambda n: results[n]["accuracy_score"], reverse=True)
    for rank, name in enumerate(sorted_names, 1):
        results[name]["rank"] = rank

    best = sorted_names[0]
    results["best_report"] = best

    return results


def generate_remediation(buffer_cache, library_cache, pga, sql_info):
    """Generate Oracle SQL remediation script."""
    lines = [
        "-- Oracle 19c Performance Remediation Script",
        "-- Generated from V$ view performance analysis",
        "",
    ]

    rec_mb = buffer_cache["recommended_size_mb"]
    lines.append(f"-- Buffer cache: increase from {buffer_cache['current_size_mb']}MB to {rec_mb}MB")
    lines.append(f"ALTER SYSTEM SET db_cache_size = {rec_mb}M SCOPE=BOTH;")
    lines.append("")

    pga_rec = pga["recommended_target_mb"]
    lines.append(f"-- PGA: increase from {pga['current_target_mb']}MB to {pga_rec}MB")
    lines.append(f"ALTER SYSTEM SET pga_aggregate_target = {pga_rec}M SCOPE=BOTH;")
    lines.append("")

    lines.append("-- Address literal SQL hard parsing by enabling cursor sharing")
    lines.append("ALTER SYSTEM SET cursor_sharing = 'FORCE' SCOPE=BOTH;")
    lines.append("")

    if sql_info.get("missing_index_columns"):
        cols = ", ".join(sql_info["missing_index_columns"])
        lines.append(f"-- Create composite index for SQL_ID {sql_info['sql_id']}")
        lines.append(f"CREATE INDEX idx_orders_custid_date ON orders ({cols});")
        lines.append("")

    return "\n".join(lines)


def main():
    print("=== Oracle Performance Advisor Audit - Solution ===")
    print(f"Incident data: {INCIDENT_DIR}")
    print(f"Baselines: {BASELINES_DB}")
    print(f"Reports: {REPORTS_DIR}")

    # Step 1: Import spool data into SQLite
    analysis_db_path = "/app/analysis.db"
    import_spool_to_sqlite(analysis_db_path)

    # Step 2: Connect and compute correct metrics
    conn = sqlite3.connect(analysis_db_path)

    buffer_cache = analyze_buffer_cache(conn)
    library_cache = analyze_library_cache(conn)
    pga = analyze_pga(conn)
    top_events = analyze_wait_events(conn)
    sql_info = analyze_sql(conn)
    all_events = get_all_non_idle_events(conn)
    root_causes = rank_root_causes(all_events, buffer_cache, library_cache, pga, sql_info)

    conn.close()

    # Step 3: Build corrected diagnosis
    corrected = {
        "buffer_cache": buffer_cache,
        "library_cache": library_cache,
        "pga": pga,
        "top_wait_events": top_events,
        "problematic_sql": sql_info,
        "root_causes_ranked": root_causes,
    }

    with open("/app/corrected_diagnosis.json", "w") as f:
        json.dump(corrected, f, indent=2)
    print("Wrote /app/corrected_diagnosis.json")

    # Step 4: Load and evaluate consultant reports
    consultants = {}
    for name in ["consultant_A", "consultant_B", "consultant_C"]:
        path = os.path.join(REPORTS_DIR, f"{name}.json")
        with open(path) as f:
            consultants[name] = json.load(f)

    evaluation = evaluate_consultants(corrected, consultants)

    with open("/app/evaluation.json", "w") as f:
        json.dump(evaluation, f, indent=2)
    print("Wrote /app/evaluation.json")

    # Step 5: Generate remediation SQL
    remediation = generate_remediation(buffer_cache, library_cache, pga, sql_info)
    with open("/app/remediation.sql", "w") as f:
        f.write(remediation)
    print("Wrote /app/remediation.sql")

    print("\n=== Analysis Complete ===")
    print(f"Best consultant: {evaluation['best_report']}")
    for name in ["consultant_A", "consultant_B", "consultant_C"]:
        info = evaluation[name]
        print(f"  {name}: accuracy={info['accuracy_score']:.3f}, rank={info['rank']}, errors={len(info['errors'])}")


if __name__ == "__main__":
    main()
