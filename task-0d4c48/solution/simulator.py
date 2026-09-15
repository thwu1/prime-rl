#!/usr/bin/env python3
"""Cascading failure incident replay engine — reference solution."""

import json
import sqlite3
from collections import deque

import yaml


def load_inputs():
    """Read scenario from YAML topology and SQLite incident database."""
    with open("/app/topology.yaml") as f:
        topo = yaml.safe_load(f)

    conn = sqlite3.connect("/app/incident.db")
    params = dict(conn.execute("SELECT key, value FROM parameters").fetchall())

    events = []
    for row in conn.execute(
        "SELECT time_step, event_type, cluster_name, value FROM events ORDER BY id"
    ):
        ev = {"time": int(row[0]), "type": row[1]}
        if row[1] == "capacity_change":
            ev["cluster"] = row[2]
            ev["new_capacity"] = row[3]
        elif row[1] == "load_change":
            ev["new_load_qps"] = row[3]
        events.append(ev)

    meta = dict(conn.execute("SELECT key, value FROM metadata").fetchall())
    conn.close()

    return {
        "simulation": {"duration_steps": int(meta["duration_steps"])},
        "throttling": {
            "K": params["throttle_K"],
            "window_steps": int(params["throttle_window_steps"]),
        },
        "retry": {"budget_fraction": params["retry_budget_fraction"]},
        "crash": {
            "threshold": params["crash_threshold"],
            "consecutive_steps": int(params["crash_consecutive_steps"]),
            "offline_steps": int(params["crash_offline_steps"]),
            "recovery_capacity_fraction": params[
                "crash_recovery_capacity_fraction"
            ],
            "recovery_steps": int(params["crash_recovery_steps"]),
        },
        "clusters": {
            name: {"capacity_qps": props["capacity_qps"], "weight": props["weight"]}
            for name, props in topo["clusters"].items()
        },
        "base_load_qps": float(meta["base_load_qps"]),
        "events": events,
    }


def simulate(scenario):
    """Run the cascading failure simulation."""
    sim = scenario["simulation"]
    throttle_cfg = scenario["throttling"]
    retry_cfg = scenario["retry"]
    crash_cfg = scenario["crash"]

    duration = sim["duration_steps"]
    K = float(throttle_cfg["K"])
    win_size = int(throttle_cfg["window_steps"])
    retry_budget = float(retry_cfg["budget_fraction"])
    crash_thresh = float(crash_cfg["threshold"])
    crash_consec = int(crash_cfg["consecutive_steps"])
    offline_dur = int(crash_cfg["offline_steps"])
    recov_frac = float(crash_cfg["recovery_capacity_fraction"])
    recov_dur = int(crash_cfg["recovery_steps"])

    clusters = {}
    for name, props in scenario["clusters"].items():
        clusters[name] = {
            "base_cap": float(props["capacity_qps"]),
            "cap": float(props["capacity_qps"]),
            "weight": float(props["weight"]),
            "status": "healthy",
            "overload_ctr": 0,
            "offline_timer": 0,
            "recov_timer": 0,
        }

    current_load = float(scenario["base_load_qps"])
    events_map = {}
    for ev in scenario["events"]:
        events_map.setdefault(ev["time"], []).append(ev)

    req_win = deque(maxlen=win_size)
    acc_win = deque(maxlen=win_size)
    pending_retries = 0.0

    time_series = []
    cascade_events = []

    for t in range(duration):
        # Phase 1: Events
        for ev in events_map.get(t, []):
            etype = ev["type"]
            if etype == "capacity_change":
                cn = ev["cluster"]
                nc = float(ev["new_capacity"])
                clusters[cn]["base_cap"] = nc
                if clusters[cn]["status"] == "healthy":
                    clusters[cn]["cap"] = nc
                cascade_events.append({"t": t, "type": etype, "cluster": cn})
            elif etype == "load_change":
                current_load = float(ev["new_load_qps"])
                cascade_events.append({"t": t, "type": etype})

        # Phase 2: State transitions
        for nm, c in clusters.items():
            if c["status"] == "crashed":
                c["offline_timer"] += 1
                if c["offline_timer"] >= offline_dur:
                    c["status"] = "recovering"
                    c["cap"] = c["base_cap"] * recov_frac
                    c["offline_timer"] = 0
                    c["recov_timer"] = 0
            elif c["status"] == "recovering":
                c["recov_timer"] += 1
                if c["recov_timer"] >= recov_dur:
                    c["status"] = "healthy"
                    c["cap"] = c["base_cap"]
                    c["recov_timer"] = 0

        # Phase 3: Load computation
        active = {
            nm: c
            for nm, c in clusters.items()
            if c["status"] != "crashed" and c["cap"] > 0
        }
        total_weight = sum(c["weight"] for c in active.values())

        if len(req_win) > 0:
            wr = sum(req_win)
            wa = sum(acc_win)
            throttle_p = max(0.0, (wr - K * wa) / (wr + 1.0))
        else:
            throttle_p = 0.0

        retries = min(pending_retries, retry_budget * current_load)
        total_load = current_load + retries
        eff_load = total_load * (1.0 - throttle_p)

        # Phase 4: Distribute and process
        step_c = {}
        total_acc = 0.0
        total_rej = 0.0

        if total_weight > 0:
            for nm, c in clusters.items():
                if nm not in active:
                    step_c[nm] = {
                        "status": c["status"],
                        "capacity": c["cap"],
                        "incoming": 0.0,
                        "accepted": 0.0,
                        "rejected": 0.0,
                        "utilization": 0.0,
                    }
                    continue
                inc = eff_load * c["weight"] / total_weight
                acc = min(inc, c["cap"])
                rej = max(0.0, inc - c["cap"])
                util = inc / c["cap"]
                total_acc += acc
                total_rej += rej
                step_c[nm] = {
                    "status": c["status"],
                    "capacity": c["cap"],
                    "incoming": round(inc, 4),
                    "accepted": round(acc, 4),
                    "rejected": round(rej, 4),
                    "utilization": round(util, 6),
                }
        else:
            total_rej = eff_load
            for nm, c in clusters.items():
                step_c[nm] = {
                    "status": c["status"],
                    "capacity": c["cap"],
                    "incoming": 0.0,
                    "accepted": 0.0,
                    "rejected": 0.0,
                    "utilization": 0.0,
                }

        # Phase 5: Window update
        req_win.append(eff_load)
        acc_win.append(total_acc)

        err_rate = total_rej / total_load if total_load > 0 else 0.0

        # Phase 6: Crash detection
        for nm, c in clusters.items():
            if c["status"] != "crashed" and c["cap"] > 0:
                u = step_c[nm]["utilization"]
                if u > crash_thresh:
                    c["overload_ctr"] += 1
                else:
                    c["overload_ctr"] = 0
                if c["overload_ctr"] >= crash_consec:
                    c["status"] = "crashed"
                    c["cap"] = 0
                    c["overload_ctr"] = 0
                    c["offline_timer"] = 0
                    step_c[nm]["status"] = "crashed"
                    cascade_events.append(
                        {"t": t, "type": "cluster_crash", "cluster": nm}
                    )

        # Phase 7: Record
        time_series.append(
            {
                "t": t,
                "current_load": current_load,
                "total_load": round(total_load, 4),
                "effective_load": round(eff_load, 4),
                "throttle_probability": round(throttle_p, 6),
                "global_error_rate": round(err_rate, 6),
                "total_accepted": round(total_acc, 4),
                "total_rejected": round(total_rej, 4),
                "clusters": step_c,
            }
        )

        # Phase 8: Pending retries
        pending_retries = total_rej

    # === Analysis ===
    first_ol = None
    first_crash = None
    peak_er = 0.0
    peak_t = 0
    total_lost = 0.0
    crashed_set = set()
    max_sim = 0

    for s in time_series:
        er = s["global_error_rate"]
        if er > peak_er:
            peak_er = er
            peak_t = s["t"]
        total_lost += s["total_rejected"]

        cc = 0
        for cn, cd in s["clusters"].items():
            if cd["utilization"] > 1.0 and first_ol is None:
                first_ol = s["t"]
            if cd["status"] == "crashed":
                crashed_set.add(cn)
                cc += 1
        max_sim = max(max_sim, cc)

    for ev in cascade_events:
        if ev["type"] == "cluster_crash":
            first_crash = ev["t"]
            break

    recov_time = None
    if first_crash is not None:
        for s in time_series:
            if s["t"] <= first_crash:
                continue
            if all(cd["status"] == "healthy" for cd in s["clusters"].values()):
                recov_time = s["t"]
                break

    analysis = {
        "first_overload_time": first_ol,
        "first_crash_time": first_crash,
        "peak_error_rate": round(peak_er, 6),
        "peak_error_time": peak_t,
        "total_requests_lost": round(total_lost, 2),
        "clusters_crashed": sorted(list(crashed_set)),
        "max_simultaneous_crashes": max_sim,
        "recovery_time": recov_time,
    }

    return {"time_series": time_series, "analysis": analysis}


def write_json(results, path):
    """Write simulation results as JSON."""
    with open(path, "w") as f:
        json.dump(results, f, indent=2)


def write_sqlite(results, db_path):
    """Write simulation results to SQLite tables and create views."""
    conn = sqlite3.connect(db_path)

    conn.execute(
        "CREATE TABLE IF NOT EXISTS simulation_results ("
        "time_step INTEGER PRIMARY KEY, "
        "base_load REAL, total_load REAL, effective_load REAL, "
        "throttle_probability REAL, error_rate REAL, "
        "total_accepted REAL, total_rejected REAL)"
    )

    conn.execute(
        "CREATE TABLE IF NOT EXISTS cluster_states ("
        "time_step INTEGER, cluster_name TEXT, "
        "status TEXT, capacity REAL, incoming REAL, "
        "accepted REAL, rejected REAL, utilization REAL, "
        "PRIMARY KEY (time_step, cluster_name))"
    )

    conn.execute(
        "CREATE TABLE IF NOT EXISTS analysis_summary ("
        "metric TEXT PRIMARY KEY, value TEXT)"
    )

    for step in results["time_series"]:
        conn.execute(
            "INSERT INTO simulation_results VALUES (?,?,?,?,?,?,?,?)",
            (
                step["t"],
                step["current_load"],
                step["total_load"],
                step["effective_load"],
                step["throttle_probability"],
                step["global_error_rate"],
                step["total_accepted"],
                step["total_rejected"],
            ),
        )
        for cn, cd in step["clusters"].items():
            conn.execute(
                "INSERT INTO cluster_states VALUES (?,?,?,?,?,?,?,?)",
                (
                    step["t"],
                    cn,
                    cd["status"],
                    cd["capacity"],
                    cd["incoming"],
                    cd["accepted"],
                    cd["rejected"],
                    cd["utilization"],
                ),
            )

    analysis = results["analysis"]
    for metric, value in analysis.items():
        if isinstance(value, list):
            str_val = ",".join(str(v) for v in value)
        elif value is None:
            str_val = "null"
        else:
            str_val = str(value)
        conn.execute(
            "INSERT INTO analysis_summary VALUES (?,?)", (metric, str_val)
        )

    conn.execute(
        "CREATE VIEW IF NOT EXISTS capacity_headroom AS "
        "SELECT cluster_name, "
        "MIN(capacity - incoming) as min_headroom, "
        "AVG(capacity - incoming) as avg_headroom, "
        "SUM(CASE WHEN incoming > capacity THEN 1 ELSE 0 END) "
        "as overload_ticks "
        "FROM cluster_states "
        "WHERE status != 'crashed' "
        "GROUP BY cluster_name"
    )

    conn.commit()
    conn.close()


def main():
    scenario = load_inputs()
    results = simulate(scenario)
    write_json(results, "/app/results.json")
    write_sqlite(results, "/app/incident.db")


if __name__ == "__main__":
    main()
