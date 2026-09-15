#!/usr/bin/env python3
"""
Solve the TiDB triage pipeline task.

"""
import json
import subprocess
import sqlite3


def run_plan_extract():
    """Use the plan-extract CLI to get metrics for all plans."""
    result = subprocess.run(
        ["plan-extract", "--db", "/app/data/monitoring.db", "--all",
         "--format", "json"],
        capture_output=True, text=True, check=True
    )
    return json.loads(result.stdout)


def get_historical_patterns(incidents_db):
    """Query the historical incidents DB to build metric profiles per root cause."""
    conn = sqlite3.connect(incidents_db)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM historical_incidents").fetchall()
    conn.close()

    # Group by root cause
    profiles = {}
    for row in rows:
        rc = row["verified_root_cause"]
        if rc not in profiles:
            profiles[rc] = []
        profiles[rc].append(dict(row))

    return profiles


def classify_plan(metrics, profiles):
    """Classify a plan by matching its metrics against historical patterns."""
    # Check lock_contention: non-zero resolve_lock_time_ms
    if metrics.get("resolve_lock_time_ms", 0) > 0 and metrics.get("backoff_count", 0) > 0:
        if "lock_contention" in profiles:
            lc = profiles["lock_contention"]
            min_rl = min(i["resolve_lock_time_ms"] for i in lc)
            if metrics["resolve_lock_time_ms"] >= min_rl * 0.5:
                return "lock_contention"

    # Check mvcc_tombstone_scan: very high cop_tasks + max_proc_keys + ascending scan
    if "mvcc_tombstone_scan" in profiles:
        mvcc = profiles["mvcc_tombstone_scan"]
        min_cop = min(i["cop_tasks"] for i in mvcc)
        min_mpk = min(i["max_proc_keys"] for i in mvcc)
        if (metrics.get("cop_tasks", 0) >= min_cop * 0.5 and
                metrics.get("max_proc_keys", 0) >= min_mpk * 0.5 and
                metrics.get("scan_direction") == "asc"):
            return "mvcc_tombstone_scan"

    # Check concurrency_bottleneck: index_lookup with low effective vs configured
    if "concurrency_bottleneck" in profiles:
        conc = profiles["concurrency_bottleneck"]
        if (metrics.get("operator_type") == "index_lookup" and
                metrics.get("effective_concurrency", 1) <
                metrics.get("configured_concurrency", 1) and
                metrics.get("cop_tasks", 0) >= 5):
            return "concurrency_bottleneck"

    # Check memory_pressure
    if "memory_pressure" in profiles:
        mem = profiles["memory_pressure"]
        min_cop = min(i["cop_tasks"] for i in mem)
        min_mpk = min(i["max_proc_keys"] for i in mem)
        if (metrics.get("cop_tasks", 0) >= min_cop and
                metrics.get("max_proc_keys", 0) >= min_mpk and
                metrics.get("effective_concurrency", 1) >=
                metrics.get("configured_concurrency", 1) * 0.5):
            return "memory_pressure"

    # Check network_latency
    if "network_latency" in profiles:
        net = profiles["network_latency"]
        max_cop = max(i["cop_tasks"] for i in net)
        if (metrics.get("cop_tasks", 0) <= max_cop and
                metrics.get("resolve_lock_time_ms", 0) == 0 and
                metrics.get("total_time_sec", 0) > 0.5 and
                metrics.get("max_proc_keys", 0) < 1000):
            return "network_latency"

    return "healthy"


def get_remediation_rankings(root_cause, incidents_db):
    """Query remediations for a root cause, return ranked by avg effectiveness."""
    conn = sqlite3.connect(incidents_db)
    rows = conn.execute("""
        SELECT r.strategy, AVG(r.actual_improvement_pct) as avg_eff
        FROM remediations r
        JOIN historical_incidents h ON r.incident_id = h.id
        WHERE h.verified_root_cause = ?
        GROUP BY r.strategy
        ORDER BY avg_eff DESC
    """, (root_cause,)).fetchall()
    conn.close()

    return [
        {"strategy": row[0], "avg_effectiveness": round(row[1], 2)}
        for row in rows
    ]


def find_correlations(plan_metrics, monitoring_db):
    """Identify plans that share the same table/index and may be correlated."""
    conn = sqlite3.connect(monitoring_db)
    plans = conn.execute(
        "SELECT plan_id, source_label, plan_text FROM raw_plans ORDER BY plan_id"
    ).fetchall()
    conn.close()

    # Extract table/index references from source labels
    label_map = {}
    for pid, label, text in plans:
        # Parse "table.index" from source_label like "events.idx_ts ..."
        parts = label.split()
        if parts:
            table_index = parts[0]  # e.g., "events.idx_ts"
            if table_index not in label_map:
                label_map[table_index] = []
            label_map[table_index].append(pid)

    # Find groups with more than one plan
    correlated = []
    for key, pids in label_map.items():
        if len(pids) > 1:
            correlated = sorted(pids)
            break

    return correlated


def main():
    incidents_db = "/app/data/incidents.db"
    monitoring_db = "/app/data/monitoring.db"

    # Step 1: Extract metrics from all plans
    plan_metrics = run_plan_extract()

    # Step 2: Get historical patterns
    profiles = get_historical_patterns(incidents_db)

    # Step 3: Classify each plan
    classifications = {}
    for pm in plan_metrics:
        pid = str(pm["plan_id"])
        classifications[pid] = classify_plan(pm, profiles)

    # Step 4: Get remediation rankings for anomalous plans
    top_remediations = {}
    for pid, root_cause in classifications.items():
        if root_cause != "healthy":
            rankings = get_remediation_rankings(root_cause, incidents_db)
            top_remediations[pid] = rankings

    # Step 5: Identify correlations
    correlated = find_correlations(plan_metrics, monitoring_db)

    # Determine shared root cause from the correlated plans
    shared_root_cause = ""
    for pid in correlated:
        rc = classifications.get(str(pid), "healthy")
        if rc != "healthy":
            shared_root_cause = rc
            break

    # Build report
    report = {
        "classifications": classifications,
        "top_remediations": top_remediations,
        "correlated_plans": correlated,
        "shared_root_cause": shared_root_cause,
    }

    with open("/app/triage_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Triage report written to /app/triage_report.json")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
