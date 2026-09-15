#!/usr/bin/env python3
"""
Airflow DAG Scheduling Forensic Analyzer - Reference Solution
"""

import json
import os
import sqlite3
import subprocess
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

DAG_DIR = "/app/dags"
EXEC_LOG = "/app/execution_log.jsonl"
SCHED_LOG = "/app/scheduler_events.jsonl"
CONFIG_PATH = "/app/config.json"
OUTPUT = "/app/results.json"
DB_PATH = "/app/airflow_forensics.db"
DOT_PATH = "/app/dependency_graph.dot"
SVG_PATH = "/app/dependency_graph.svg"

FAR_FUTURE = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)


def parse_ts(ts_str):
    if ts_str is None:
        return None
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))


def format_ts(dt):
    if dt is None:
        return None
    return dt.isoformat()


def load_config():
    with open(CONFIG_PATH) as fh:
        config = json.load(fh)
    assert "zombie_heartbeat_threshold_seconds" in config, (
        f"config.json missing 'zombie_heartbeat_threshold_seconds'. Keys: {list(config.keys())}"
    )
    assert "max_active_scheduler_jobs" in config, (
        f"config.json missing 'max_active_scheduler_jobs'. Keys: {list(config.keys())}"
    )
    return config


# == 1. Build SQLite database ==


def build_database():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""CREATE TABLE dags (
        dag_id TEXT PRIMARY KEY,
        schedule_interval TEXT,
        retries INTEGER,
        retry_delay_seconds INTEGER,
        execution_timeout_seconds INTEGER
    )""")

    c.execute("""CREATE TABLE tasks (
        dag_id TEXT,
        task_id TEXT,
        operator TEXT,
        external_dag_id TEXT,
        external_task_id TEXT,
        trigger_dag_id TEXT,
        target_dag_id TEXT,
        target_task_id TEXT,
        PRIMARY KEY (dag_id, task_id),
        FOREIGN KEY (dag_id) REFERENCES dags(dag_id)
    )""")

    c.execute("""CREATE TABLE executions (
        dag_id TEXT,
        task_id TEXT,
        run_id TEXT,
        attempt INTEGER,
        state TEXT,
        start_time TEXT,
        end_time TEXT,
        hostname TEXT,
        scheduler_job_id INTEGER,
        PRIMARY KEY (dag_id, task_id, run_id, attempt)
    )""")

    c.execute("""CREATE TABLE scheduler_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT,
        job_id INTEGER,
        timestamp TEXT,
        hostname TEXT
    )""")

    # Load DAGs
    for fname in sorted(os.listdir(DAG_DIR)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(DAG_DIR, fname)) as fh:
            dag = json.load(fh)
        da = dag.get("default_args", {})
        c.execute("INSERT INTO dags VALUES (?, ?, ?, ?, ?)", (
            dag["dag_id"],
            dag.get("schedule_interval"),
            da.get("retries"),
            da.get("retry_delay_seconds"),
            da.get("execution_timeout_seconds"),
        ))
        for task in dag["tasks"]:
            c.execute("INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
                dag["dag_id"],
                task["task_id"],
                task["operator"],
                task.get("external_dag_id"),
                task.get("external_task_id"),
                task.get("trigger_dag_id"),
                task.get("target_dag_id"),
                task.get("target_task_id"),
            ))

    # Load executions
    with open(EXEC_LOG) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            c.execute(
                "INSERT INTO executions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec["dag_id"],
                    rec["task_id"],
                    rec["run_id"],
                    rec["attempt"],
                    rec["state"],
                    rec.get("start_time"),
                    rec.get("end_time"),
                    rec.get("hostname"),
                    rec.get("scheduler_job_id"),
                ),
            )

    # Load scheduler events
    with open(SCHED_LOG) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            c.execute(
                "INSERT INTO scheduler_events"
                " (event_type, job_id, timestamp, hostname)"
                " VALUES (?, ?, ?, ?)",
                (
                    ev["event_type"],
                    ev["job_id"],
                    ev["timestamp"],
                    ev.get("hostname"),
                ),
            )

    conn.commit()
    conn.close()


# == 2. Build cross-DAG dependency graph ==


def build_dependency_graph():
    graph = {}
    for fname in sorted(os.listdir(DAG_DIR)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(DAG_DIR, fname)) as fh:
            dag = json.load(fh)
        dag_id = dag["dag_id"]
        deps = set()
        for task in dag["tasks"]:
            # Only ExternalTaskSensor creates a true blocking dependency.
            # TriggerDagRunOperator is fire-and-forget (no dependency).
            # ExternalTaskMarker marks upstream completion for downstream
            # sensors — it does NOT create a dependency for the containing DAG.
            if task["operator"] == "ExternalTaskSensor":
                deps.add(task["external_dag_id"])
        graph[dag_id] = sorted(deps)
    return graph


# == 3. Find all simple (elementary) cycles ==


def find_simple_cycles(graph):
    nodes = sorted(graph)
    cycles = []

    def _dfs(start, cur, visited, path):
        for nbr in graph.get(cur, []):
            if nbr == start and len(path) > 1:
                cycle = sorted(path)
                if cycle not in cycles:
                    cycles.append(cycle)
            elif nbr not in visited and nbr >= start:
                visited.add(nbr)
                path.append(nbr)
                _dfs(start, nbr, visited, path)
                path.pop()
                visited.remove(nbr)

    for node in nodes:
        _dfs(node, node, {node}, [node])

    return sorted(cycles)


# == 4. Generate graphviz DOT and SVG ==


def generate_graph_visualization(graph, cycles):
    cycle_edges = set()
    for cycle in cycles:
        cycle_set = set(cycle)
        for node in cycle:
            for dep in graph.get(node, []):
                if dep in cycle_set:
                    cycle_edges.add((node, dep))

    lines = [
        "digraph airflow_dependencies {",
        "    rankdir=LR;",
        '    node [shape=box, style=filled, fillcolor="#e8f4fd",'
        ' fontname="Helvetica"];',
        '    edge [fontname="Helvetica"];',
        "",
    ]

    for dag_id in sorted(graph.keys()):
        lines.append(f'    "{dag_id}";')
    lines.append("")

    for dag_id in sorted(graph.keys()):
        for dep in graph[dag_id]:
            if (dag_id, dep) in cycle_edges:
                lines.append(
                    f'    "{dag_id}" -> "{dep}"'
                    f" [color=red, penwidth=2.0];"
                )
            else:
                lines.append(f'    "{dag_id}" -> "{dep}";')

    lines.append("}")

    dot_content = "\n".join(lines) + "\n"

    with open(DOT_PATH, "w") as f:
        f.write(dot_content)

    subprocess.run(
        ["dot", "-Tsvg", DOT_PATH, "-o", SVG_PATH],
        check=True,
        capture_output=True,
    )


# == 5. Detect scheduling anomalies ==


def load_execution_records():
    records = []
    with open(EXEC_LOG) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def load_scheduler_state():
    jobs = {}
    latest = None

    with open(SCHED_LOG) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            jid = ev["job_id"]
            ts = parse_ts(ev["timestamp"])
            if latest is None or ts > latest:
                latest = ts

            if jid not in jobs:
                jobs[jid] = {
                    "hostname": None,
                    "start_time": None,
                    "last_heartbeat": None,
                    "end_time": None,
                    "heartbeats": [],
                }

            etype = ev["event_type"]
            if etype == "job_start":
                jobs[jid]["start_time"] = ts
                if ev.get("hostname"):
                    jobs[jid]["hostname"] = ev["hostname"]
            elif etype == "job_end":
                jobs[jid]["end_time"] = ts
            elif etype == "heartbeat":
                jobs[jid]["heartbeats"].append(ts)
                if jobs[jid]["last_heartbeat"] is None or ts > jobs[jid]["last_heartbeat"]:
                    jobs[jid]["last_heartbeat"] = ts

    return jobs, latest


def detect_anomalies(config, exec_records, jobs, latest_ts):
    threshold = config["zombie_heartbeat_threshold_seconds"]

    # -- concurrent executions --
    groups = defaultdict(list)
    for t in exec_records:
        groups[(t["dag_id"], t["task_id"], t["run_id"])].append(t)

    concurrent = []
    for key, attempts in sorted(groups.items()):
        if len(attempts) < 2:
            continue
        attempts_sorted = sorted(attempts, key=lambda x: x["attempt"])
        for i in range(len(attempts_sorted)):
            for j in range(i + 1, len(attempts_sorted)):
                a, b = attempts_sorted[i], attempts_sorted[j]
                a_start = parse_ts(a["start_time"])
                a_end = parse_ts(a["end_time"]) or FAR_FUTURE
                b_start = parse_ts(b["start_time"])
                b_end = parse_ts(b["end_time"]) or FAR_FUTURE
                if a_start < b_end and b_start < a_end:
                    concurrent.append({
                        "dag_id": key[0],
                        "task_id": key[1],
                        "run_id": key[2],
                        "attempts": sorted([a["attempt"], b["attempt"]]),
                    })

    concurrent.sort(key=lambda x: (x["dag_id"], x["task_id"]))

    # -- zombie & orphaned tasks --
    zombies = []
    orphaned = []
    for t in exec_records:
        if t["state"] != "running" or t["end_time"] is not None:
            continue
        jid = t["scheduler_job_id"]
        entry = {
            "dag_id": t["dag_id"],
            "task_id": t["task_id"],
            "run_id": t["run_id"],
            "attempt": t["attempt"],
            "scheduler_job_id": jid,
        }
        if jid not in jobs:
            orphaned.append(entry)
        else:
            hbs = jobs[jid]["heartbeats"]
            if hbs and latest_ts is not None:
                last_hb = max(hbs)
                if (latest_ts - last_hb).total_seconds() > threshold:
                    zombies.append(entry)

    zombies.sort(key=lambda x: (x["dag_id"], x["task_id"]))
    orphaned.sort(key=lambda x: (x["dag_id"], x["task_id"]))

    return {
        "concurrent_executions": concurrent,
        "zombie_tasks": zombies,
        "orphaned_tasks": orphaned,
    }


# == 6. Build scheduler timeline ==


def build_scheduler_timeline(config, jobs, latest_ts):
    threshold = config["zombie_heartbeat_threshold_seconds"]

    timeline = []
    for jid in sorted(jobs):
        j = jobs[jid]
        if j["end_time"] is not None:
            status = "completed"
        else:
            ref_time = j["last_heartbeat"] or j["start_time"]
            if ref_time is not None and latest_ts is not None:
                gap = (latest_ts - ref_time).total_seconds()
                if gap > threshold:
                    status = "unresponsive"
                else:
                    status = "active"
            else:
                status = "active"

        timeline.append({
            "job_id": jid,
            "hostname": j["hostname"],
            "start_time": format_ts(j["start_time"]),
            "last_heartbeat": format_ts(j["last_heartbeat"]),
            "end_time": format_ts(j["end_time"]),
            "status": status,
            "heartbeat_count": len(j["heartbeats"]),
        })

    return timeline


# == 7. Detect split-brain windows ==


def detect_split_brain(config, jobs, latest_ts):
    threshold = config["zombie_heartbeat_threshold_seconds"]
    max_active = config["max_active_scheduler_jobs"]

    # Compute active period for each job
    periods = []
    for jid in sorted(jobs):
        j = jobs[jid]
        start = j["start_time"]
        if start is None:
            continue
        if j["end_time"] is not None:
            end = j["end_time"]
        elif j["last_heartbeat"] is not None:
            end = j["last_heartbeat"] + timedelta(seconds=threshold)
        else:
            end = start + timedelta(seconds=threshold)
        periods.append((jid, start, end))

    # Find pairwise overlaps
    windows = []
    for i in range(len(periods)):
        for k in range(i + 1, len(periods)):
            jid_a, start_a, end_a = periods[i]
            jid_b, start_b, end_b = periods[k]
            overlap_start = max(start_a, start_b)
            overlap_end = min(end_a, end_b)
            if overlap_start < overlap_end:
                # 2 jobs active simultaneously; violation if max_active < 2
                if 2 > max_active:
                    windows.append({
                        "overlapping_jobs": sorted([jid_a, jid_b]),
                        "window_start": format_ts(overlap_start),
                        "window_end": format_ts(overlap_end),
                        "duration_seconds": int(
                            (overlap_end - overlap_start).total_seconds()
                        ),
                    })

    windows.sort(key=lambda w: w["window_start"])
    return windows


# == 8. Compute downstream impact ==


def compute_downstream_impact(dependency_graph, affected_dag):
    """Find all DAGs that transitively depend on affected_dag."""
    # Build reverse graph: dep -> set of DAGs that depend on it
    reverse = defaultdict(set)
    for dag, deps in dependency_graph.items():
        for dep in deps:
            reverse[dep].add(dag)

    # BFS from affected_dag through reverse graph
    visited = set()
    queue = deque([affected_dag])
    while queue:
        node = queue.popleft()
        for downstream in reverse.get(node, set()):
            if downstream not in visited:
                visited.add(downstream)
                queue.append(downstream)

    visited.discard(affected_dag)
    return sorted(visited)


# == 9. Root cause analysis ==


def build_root_cause_analysis(anomalies, exec_records, jobs, dependency_graph):
    rca = []

    # For concurrent executions, determine if caused by failover overlap
    # or premature retry by same scheduler
    for ce in anomalies["concurrent_executions"]:
        matching = [
            r for r in exec_records
            if r["dag_id"] == ce["dag_id"]
            and r["task_id"] == ce["task_id"]
            and r["run_id"] == ce["run_id"]
            and r["attempt"] in ce["attempts"]
        ]
        scheduler_ids = set(r["scheduler_job_id"] for r in matching)

        if len(scheduler_ids) == 1:
            root_cause = "premature_retry"
            causal_id = scheduler_ids.pop()
        else:
            root_cause = "scheduler_failover_overlap"
            causal_id = None

        rca.append({
            "anomaly_type": "concurrent_execution",
            "dag_id": ce["dag_id"],
            "task_id": ce["task_id"],
            "root_cause": root_cause,
            "causal_scheduler_job_id": causal_id,
            "downstream_impact": compute_downstream_impact(
                dependency_graph, ce["dag_id"]
            ),
        })

    for z in anomalies["zombie_tasks"]:
        rca.append({
            "anomaly_type": "zombie_task",
            "dag_id": z["dag_id"],
            "task_id": z["task_id"],
            "root_cause": "scheduler_unresponsive",
            "causal_scheduler_job_id": z["scheduler_job_id"],
            "downstream_impact": compute_downstream_impact(
                dependency_graph, z["dag_id"]
            ),
        })

    for o in anomalies["orphaned_tasks"]:
        rca.append({
            "anomaly_type": "orphaned_task",
            "dag_id": o["dag_id"],
            "task_id": o["task_id"],
            "root_cause": "unknown_scheduler",
            "causal_scheduler_job_id": o["scheduler_job_id"],
            "downstream_impact": compute_downstream_impact(
                dependency_graph, o["dag_id"]
            ),
        })

    rca.sort(key=lambda r: (r["anomaly_type"], r["dag_id"], r["task_id"]))
    return rca


# == main ==


def main():
    # Read config once upfront
    config = load_config()

    build_database()

    graph = build_dependency_graph()
    cycles = find_simple_cycles(graph)
    generate_graph_visualization(graph, cycles)

    exec_records = load_execution_records()
    jobs, latest_ts = load_scheduler_state()

    anomalies = detect_anomalies(config, exec_records, jobs, latest_ts)
    count = sum(len(v) for v in anomalies.values())

    timeline = build_scheduler_timeline(config, jobs, latest_ts)
    split_brain = detect_split_brain(config, jobs, latest_ts)
    root_cause = build_root_cause_analysis(
        anomalies, exec_records, jobs, graph
    )

    result = {
        "dependency_graph": graph,
        "cycles": cycles,
        "anomalies": anomalies,
        "anomaly_count": count,
        "scheduler_timeline": timeline,
        "split_brain_windows": split_brain,
        "root_cause_analysis": root_cause,
    }
    with open(OUTPUT, "w") as fh:
        json.dump(result, fh, indent=2)


if __name__ == "__main__":
    main()
