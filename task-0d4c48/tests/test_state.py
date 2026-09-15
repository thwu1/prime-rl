"""
Tests for cascading failure incident replay engine.

"""
import json
import os
import sqlite3 as sqlite3_mod
from collections import deque

import pytest
import yaml


# ===== Input Loader =====

def load_scenario():
    """Load scenario from YAML topology + SQLite incident database."""
    with open("/app/topology.yaml") as f:
        topo = yaml.safe_load(f)

    conn = sqlite3_mod.connect("/app/incident.db")

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
            name: {
                "capacity_qps": props["capacity_qps"],
                "weight": props["weight"],
            }
            for name, props in topo["clusters"].items()
        },
        "base_load_qps": float(meta["base_load_qps"]),
        "events": events,
    }


# ===== Reference Implementation =====

def reference_simulate(scenario):
    """Reference cascading failure simulator."""
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

        req_win.append(eff_load)
        acc_win.append(total_acc)
        err_rate = total_rej / total_load if total_load > 0 else 0.0

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
        pending_retries = total_rej

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

    return {
        "time_series": time_series,
        "analysis": {
            "first_overload_time": first_ol,
            "first_crash_time": first_crash,
            "peak_error_rate": round(peak_er, 6),
            "peak_error_time": peak_t,
            "total_requests_lost": round(total_lost, 2),
            "clusters_crashed": sorted(list(crashed_set)),
            "max_simultaneous_crashes": max_sim,
            "recovery_time": recov_time,
        },
    }


# ===== Fixtures =====


@pytest.fixture(scope="session")
def scenario():
    return load_scenario()


@pytest.fixture(scope="session")
def reference(scenario):
    return reference_simulate(scenario)


@pytest.fixture(scope="session")
def agent_results():
    path = "/app/results.json"
    assert os.path.exists(path), f"Agent output not found at {path}"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def agent_db():
    conn = sqlite3_mod.connect("/app/incident.db")
    conn.row_factory = sqlite3_mod.Row
    yield conn
    conn.close()


# ===== Structural Tests =====


class TestStructure:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), "results.json must exist at /app/"

    def test_valid_json(self, agent_results):
        assert isinstance(agent_results, dict)

    def test_has_time_series(self, agent_results):
        assert "time_series" in agent_results, "results must contain 'time_series'"
        assert isinstance(agent_results["time_series"], list)

    def test_has_analysis(self, agent_results):
        assert "analysis" in agent_results, "results must contain 'analysis'"
        assert isinstance(agent_results["analysis"], dict)

    def test_time_series_length(self, agent_results, scenario):
        expected = scenario["simulation"]["duration_steps"]
        actual = len(agent_results["time_series"])
        assert actual == expected, f"Expected {expected} steps, got {actual}"

    def test_time_series_fields(self, agent_results):
        step = agent_results["time_series"][0]
        required = [
            "t",
            "total_load",
            "effective_load",
            "throttle_probability",
            "global_error_rate",
            "total_accepted",
            "total_rejected",
            "clusters",
        ]
        for field in required:
            assert field in step, f"Missing field '{field}' in time series step"

    def test_cluster_fields(self, agent_results, scenario):
        step = agent_results["time_series"][0]
        cluster_names = set(scenario["clusters"].keys())
        assert set(step["clusters"].keys()) == cluster_names, (
            f"Cluster names mismatch: expected {cluster_names}"
        )
        for cn, cd in step["clusters"].items():
            for field in [
                "status",
                "capacity",
                "incoming",
                "accepted",
                "rejected",
                "utilization",
            ]:
                assert field in cd, f"Missing field '{field}' in cluster '{cn}'"

    def test_analysis_fields(self, agent_results):
        required = [
            "first_overload_time",
            "first_crash_time",
            "peak_error_rate",
            "peak_error_time",
            "total_requests_lost",
            "clusters_crashed",
            "max_simultaneous_crashes",
            "recovery_time",
        ]
        for field in required:
            assert field in agent_results["analysis"], (
                f"Missing analysis field '{field}'"
            )


# ===== Analysis Metric Tests =====


class TestAnalysis:
    def test_first_overload_time(self, agent_results, reference):
        ref = reference["analysis"]["first_overload_time"]
        agent = agent_results["analysis"]["first_overload_time"]
        assert agent == ref, f"first_overload_time: expected {ref}, got {agent}"

    def test_first_crash_time(self, agent_results, reference):
        ref = reference["analysis"]["first_crash_time"]
        agent = agent_results["analysis"]["first_crash_time"]
        assert agent == ref, f"first_crash_time: expected {ref}, got {agent}"

    def test_peak_error_rate(self, agent_results, reference):
        ref = reference["analysis"]["peak_error_rate"]
        agent = agent_results["analysis"]["peak_error_rate"]
        assert abs(agent - ref) < 0.05, (
            f"peak_error_rate: expected ~{ref}, got {agent}"
        )

    def test_peak_error_time(self, agent_results, reference):
        ref = reference["analysis"]["peak_error_time"]
        agent = agent_results["analysis"]["peak_error_time"]
        assert abs(agent - ref) <= 2, (
            f"peak_error_time: expected ~{ref}, got {agent}"
        )

    def test_clusters_crashed(self, agent_results, reference):
        ref = set(reference["analysis"]["clusters_crashed"])
        agent = set(agent_results["analysis"]["clusters_crashed"])
        assert agent == ref, f"clusters_crashed: expected {ref}, got {agent}"

    def test_max_simultaneous_crashes(self, agent_results, reference):
        ref = reference["analysis"]["max_simultaneous_crashes"]
        agent = agent_results["analysis"]["max_simultaneous_crashes"]
        assert agent == ref, (
            f"max_simultaneous_crashes: expected {ref}, got {agent}"
        )

    def test_recovery_time(self, agent_results, reference):
        ref = reference["analysis"]["recovery_time"]
        agent = agent_results["analysis"]["recovery_time"]
        if ref is None:
            assert agent is None, "recovery_time should be null"
        else:
            assert agent is not None, "recovery_time should not be null"
            assert abs(agent - ref) <= 3, (
                f"recovery_time: expected ~{ref}, got {agent}"
            )

    def test_total_requests_lost(self, agent_results, reference):
        ref = reference["analysis"]["total_requests_lost"]
        agent = agent_results["analysis"]["total_requests_lost"]
        tolerance = 0.10 * ref if ref > 0 else 100
        assert abs(agent - ref) < tolerance, (
            f"total_requests_lost: expected ~{ref}, got {agent} (tolerance {tolerance})"
        )


# ===== Behavioral Tests =====


class TestBehavior:
    def test_normal_operation_no_errors(self, agent_results):
        """Before any failure event (t=0..9), error rate should be 0."""
        for step in agent_results["time_series"][:10]:
            assert step["global_error_rate"] == 0.0, (
                f"Error rate at t={step['t']} should be 0 during normal operation"
            )

    def test_degradation_after_failure(self, agent_results):
        """After alpha goes offline (t=10+), errors should appear."""
        step = agent_results["time_series"][15]
        assert step["global_error_rate"] > 0.05, (
            f"Error rate at t=15 should be > 5% after alpha failure"
        )

    def test_steady_state_before_spike(self, agent_results, reference):
        """Error rate should be roughly stable from t=12 to t=29."""
        ref_step = reference["time_series"][25]
        agent_step = agent_results["time_series"][25]
        assert abs(
            agent_step["global_error_rate"] - ref_step["global_error_rate"]
        ) < 0.05, f"Steady state error rate mismatch at t=25"

    def test_cascade_causes_high_errors(self, agent_results):
        """After cascading crashes, error rate should exceed 80%."""
        max_err = max(
            s["global_error_rate"] for s in agent_results["time_series"][30:45]
        )
        assert max_err > 0.80, (
            f"Peak error rate during cascade should exceed 80%, got {max_err}"
        )

    def test_full_outage_period(self, agent_results):
        """There should be at least one step with ~100% error rate."""
        has_full_outage = any(
            s["global_error_rate"] > 0.95
            for s in agent_results["time_series"]
        )
        assert has_full_outage, (
            "Should have at least one step with >95% error rate"
        )

    def test_recovery_after_intervention(self, agent_results):
        """After operator intervention (t=55+), system should eventually recover."""
        final_steps = agent_results["time_series"][-5:]
        for step in final_steps:
            assert step["global_error_rate"] < 0.01, (
                f"Error rate at t={step['t']} should be ~0 after recovery"
            )

    def test_all_healthy_at_end(self, agent_results):
        """All clusters should be healthy at the end of the simulation."""
        final = agent_results["time_series"][-1]
        for cn, cd in final["clusters"].items():
            assert cd["status"] == "healthy", (
                f"Cluster {cn} should be healthy at end, got {cd['status']}"
            )

    def test_throttle_engages_during_outage(self, agent_results):
        """Adaptive throttling should engage during the crash-loop period."""
        max_throttle = max(
            s["throttle_probability"]
            for s in agent_results["time_series"][35:55]
        )
        assert max_throttle > 0.05, (
            f"Throttle should engage during crash loop, max was {max_throttle}"
        )

    def test_no_throttle_during_normal(self, agent_results):
        """No throttling during normal operation (t=0..9)."""
        for step in agent_results["time_series"][:10]:
            assert step["throttle_probability"] == 0.0, (
                f"Throttle should be 0 at t={step['t']} during normal operation"
            )


# ===== Time Series Consistency Tests =====


class TestConsistency:
    def test_accepted_plus_rejected_equals_effective_load(self, agent_results):
        """For each step, accepted + rejected should equal effective_load."""
        for step in agent_results["time_series"]:
            total = step["total_accepted"] + step["total_rejected"]
            expected = step["effective_load"]
            if expected > 0:
                rel_err = abs(total - expected) / expected
                assert rel_err < 0.01, (
                    f"At t={step['t']}: accepted+rejected={total} "
                    f"!= effective_load={expected}"
                )

    def test_error_rate_consistency(self, agent_results):
        """Error rate should equal rejected / total_load."""
        for step in agent_results["time_series"]:
            if step["total_load"] > 0:
                expected = step["total_rejected"] / step["total_load"]
                assert abs(step["global_error_rate"] - expected) < 0.01, (
                    f"Error rate inconsistency at t={step['t']}"
                )

    def test_cluster_accepted_within_capacity(self, agent_results):
        """No cluster should accept more than its capacity."""
        for step in agent_results["time_series"]:
            for cn, cd in step["clusters"].items():
                if cd["capacity"] > 0:
                    assert cd["accepted"] <= cd["capacity"] + 0.01, (
                        f"Cluster {cn} accepted {cd['accepted']} > "
                        f"capacity {cd['capacity']} at t={step['t']}"
                    )

    def test_utilization_correct(self, agent_results):
        """Utilization should equal incoming / capacity."""
        for step in agent_results["time_series"]:
            for cn, cd in step["clusters"].items():
                if cd["capacity"] > 0 and cd["incoming"] > 0:
                    expected = cd["incoming"] / cd["capacity"]
                    assert abs(cd["utilization"] - expected) < 0.01, (
                        f"Utilization mismatch for {cn} at t={step['t']}"
                    )

    def test_time_series_monotonic_time(self, agent_results):
        """Time steps should be monotonically increasing."""
        times = [s["t"] for s in agent_results["time_series"]]
        assert times == list(range(len(times))), (
            "Time steps should be 0, 1, 2, ..."
        )


# ===== Time Series Value Comparison =====


class TestTimeSeriesValues:
    """Compare specific time series values against reference."""

    def test_error_rate_t0(self, agent_results, reference):
        assert abs(
            agent_results["time_series"][0]["global_error_rate"]
            - reference["time_series"][0]["global_error_rate"]
        ) < 0.001

    def test_error_rate_t10(self, agent_results, reference):
        assert abs(
            agent_results["time_series"][10]["global_error_rate"]
            - reference["time_series"][10]["global_error_rate"]
        ) < 0.02

    def test_error_rate_t20(self, agent_results, reference):
        assert abs(
            agent_results["time_series"][20]["global_error_rate"]
            - reference["time_series"][20]["global_error_rate"]
        ) < 0.02

    def test_error_rate_t30(self, agent_results, reference):
        assert abs(
            agent_results["time_series"][30]["global_error_rate"]
            - reference["time_series"][30]["global_error_rate"]
        ) < 0.05

    def test_error_rate_t36(self, agent_results, reference):
        """Full outage step."""
        assert abs(
            agent_results["time_series"][36]["global_error_rate"]
            - reference["time_series"][36]["global_error_rate"]
        ) < 0.05

    def test_error_rate_t79(self, agent_results, reference):
        """End of simulation - should be fully recovered."""
        assert abs(
            agent_results["time_series"][79]["global_error_rate"]
            - reference["time_series"][79]["global_error_rate"]
        ) < 0.001

    def test_effective_load_t5(self, agent_results, reference):
        ref = reference["time_series"][5]["effective_load"]
        agent = agent_results["time_series"][5]["effective_load"]
        assert abs(agent - ref) / ref < 0.02, (
            f"effective_load at t=5: expected ~{ref}, got {agent}"
        )

    def test_effective_load_t30(self, agent_results, reference):
        ref = reference["time_series"][30]["effective_load"]
        agent = agent_results["time_series"][30]["effective_load"]
        assert abs(agent - ref) / ref < 0.05, (
            f"effective_load at t=30: expected ~{ref}, got {agent}"
        )

    def test_cluster_status_t32(self, agent_results, reference):
        """Beta and gamma should crash at t=32."""
        ref_statuses = {
            cn: cd["status"]
            for cn, cd in reference["time_series"][32]["clusters"].items()
        }
        agent_statuses = {
            cn: cd["status"]
            for cn, cd in agent_results["time_series"][32]["clusters"].items()
        }
        assert ref_statuses["beta"] == "crashed"
        assert agent_statuses["beta"] == "crashed", (
            f"Beta should be crashed at t=32, got {agent_statuses['beta']}"
        )
        assert agent_statuses["gamma"] == "crashed", (
            f"Gamma should be crashed at t=32, got {agent_statuses['gamma']}"
        )


# ===== SQLite Output Tests =====


class TestSQLiteStructure:
    """Verify SQLite tables and views exist with correct schemas."""

    def test_simulation_results_table_exists(self, agent_db):
        tables = [
            row[0]
            for row in agent_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "simulation_results" in tables, (
            "Table 'simulation_results' must exist in incident.db"
        )

    def test_cluster_states_table_exists(self, agent_db):
        tables = [
            row[0]
            for row in agent_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "cluster_states" in tables, (
            "Table 'cluster_states' must exist in incident.db"
        )

    def test_analysis_summary_table_exists(self, agent_db):
        tables = [
            row[0]
            for row in agent_db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        assert "analysis_summary" in tables, (
            "Table 'analysis_summary' must exist in incident.db"
        )

    def test_capacity_headroom_view_exists(self, agent_db):
        views = [
            row[0]
            for row in agent_db.execute(
                "SELECT name FROM sqlite_master WHERE type='view'"
            ).fetchall()
        ]
        assert "capacity_headroom" in views, (
            "View 'capacity_headroom' must exist in incident.db"
        )

    def test_simulation_results_columns(self, agent_db):
        cols = [
            row[1]
            for row in agent_db.execute(
                "PRAGMA table_info(simulation_results)"
            ).fetchall()
        ]
        expected = [
            "time_step", "base_load", "total_load", "effective_load",
            "throttle_probability", "error_rate", "total_accepted",
            "total_rejected",
        ]
        for col in expected:
            assert col in cols, (
                f"Column '{col}' missing from simulation_results"
            )

    def test_cluster_states_columns(self, agent_db):
        cols = [
            row[1]
            for row in agent_db.execute(
                "PRAGMA table_info(cluster_states)"
            ).fetchall()
        ]
        expected = [
            "time_step", "cluster_name", "status", "capacity",
            "incoming", "accepted", "rejected", "utilization",
        ]
        for col in expected:
            assert col in cols, (
                f"Column '{col}' missing from cluster_states"
            )


class TestSQLiteData:
    """Verify SQLite data correctness."""

    def test_simulation_results_row_count(self, agent_db, scenario):
        count = agent_db.execute(
            "SELECT COUNT(*) FROM simulation_results"
        ).fetchone()[0]
        expected = scenario["simulation"]["duration_steps"]
        assert count == expected, f"Expected {expected} rows, got {count}"

    def test_cluster_states_row_count(self, agent_db, scenario):
        count = agent_db.execute(
            "SELECT COUNT(*) FROM cluster_states"
        ).fetchone()[0]
        n_clusters = len(scenario["clusters"])
        n_steps = scenario["simulation"]["duration_steps"]
        expected = n_clusters * n_steps
        assert count == expected, f"Expected {expected} rows, got {count}"

    def test_simulation_results_matches_json_start(self, agent_db, agent_results):
        """Verify first few ticks match between SQLite and JSON."""
        for step in agent_results["time_series"][:5]:
            row = agent_db.execute(
                "SELECT * FROM simulation_results WHERE time_step=?",
                (step["t"],),
            ).fetchone()
            assert row is not None, f"Missing row for time_step={step['t']}"
            assert abs(row["total_load"] - step["total_load"]) < 0.1
            assert abs(row["error_rate"] - step["global_error_rate"]) < 0.001

    def test_simulation_results_matches_json_end(self, agent_db, agent_results):
        """Verify last few ticks match between SQLite and JSON."""
        for step in agent_results["time_series"][-5:]:
            row = agent_db.execute(
                "SELECT * FROM simulation_results WHERE time_step=?",
                (step["t"],),
            ).fetchone()
            assert row is not None, f"Missing row for time_step={step['t']}"
            assert abs(row["total_load"] - step["total_load"]) < 0.1
            assert abs(row["error_rate"] - step["global_error_rate"]) < 0.001

    def test_cluster_states_matches_json(self, agent_db, agent_results):
        """Spot-check cluster states at key time steps."""
        check_ticks = [0, 15, 25, 32, 55, 79]
        for t_idx in check_ticks:
            step = agent_results["time_series"][t_idx]
            for cn, cd in step["clusters"].items():
                row = agent_db.execute(
                    "SELECT * FROM cluster_states "
                    "WHERE time_step=? AND cluster_name=?",
                    (step["t"], cn),
                ).fetchone()
                assert row is not None, (
                    f"Missing cluster_states row for t={step['t']}, {cn}"
                )
                assert row["status"] == cd["status"], (
                    f"Status mismatch at t={step['t']}, {cn}: "
                    f"SQL={row['status']}, JSON={cd['status']}"
                )
                assert abs(row["capacity"] - cd["capacity"]) < 0.1, (
                    f"Capacity mismatch at t={step['t']}, {cn}"
                )

    def test_analysis_summary_first_crash_time(self, agent_db, reference):
        row = agent_db.execute(
            "SELECT value FROM analysis_summary "
            "WHERE metric='first_crash_time'"
        ).fetchone()
        assert row is not None, (
            "Missing analysis_summary row for first_crash_time"
        )
        ref_val = reference["analysis"]["first_crash_time"]
        assert row[0] == str(ref_val), (
            f"first_crash_time: expected {ref_val}, got {row[0]}"
        )

    def test_analysis_summary_clusters_crashed(self, agent_db, reference):
        row = agent_db.execute(
            "SELECT value FROM analysis_summary "
            "WHERE metric='clusters_crashed'"
        ).fetchone()
        assert row is not None, (
            "Missing analysis_summary row for clusters_crashed"
        )
        ref_val = ",".join(reference["analysis"]["clusters_crashed"])
        assert row[0] == ref_val, (
            f"clusters_crashed: expected {ref_val}, got {row[0]}"
        )

    def test_analysis_summary_max_simultaneous(self, agent_db, reference):
        row = agent_db.execute(
            "SELECT value FROM analysis_summary "
            "WHERE metric='max_simultaneous_crashes'"
        ).fetchone()
        assert row is not None, (
            "Missing analysis_summary row for max_simultaneous_crashes"
        )
        ref_val = reference["analysis"]["max_simultaneous_crashes"]
        assert row[0] == str(ref_val), (
            f"max_simultaneous_crashes: expected {ref_val}, got {row[0]}"
        )


class TestCapacityHeadroom:
    """Verify the capacity_headroom SQL view."""

    def test_view_returns_all_clusters(self, agent_db, scenario):
        rows = agent_db.execute(
            "SELECT cluster_name FROM capacity_headroom"
        ).fetchall()
        cluster_names = {row[0] for row in rows}
        expected = set(scenario["clusters"].keys())
        assert cluster_names == expected, (
            f"View should cover all clusters: expected {expected}, "
            f"got {cluster_names}"
        )

    def test_view_columns_present(self, agent_db):
        row = agent_db.execute(
            "SELECT * FROM capacity_headroom LIMIT 1"
        ).fetchone()
        assert row is not None, "capacity_headroom view returned no rows"
        keys = row.keys()
        for col in ["cluster_name", "min_headroom", "avg_headroom",
                     "overload_ticks"]:
            assert col in keys, (
                f"Column '{col}' missing from capacity_headroom view"
            )

    def test_headroom_has_overloaded_clusters(self, agent_db):
        """At least one cluster should have overload ticks > 0."""
        rows = agent_db.execute(
            "SELECT cluster_name, overload_ticks FROM capacity_headroom"
        ).fetchall()
        has_overloaded = any(row["overload_ticks"] > 0 for row in rows)
        assert has_overloaded, (
            "At least one cluster should have overload_ticks > 0"
        )

    def test_headroom_values_reasonable(self, agent_db):
        """Min headroom should be <= avg headroom for every cluster."""
        rows = agent_db.execute(
            "SELECT cluster_name, min_headroom, avg_headroom "
            "FROM capacity_headroom"
        ).fetchall()
        for row in rows:
            assert row["min_headroom"] <= row["avg_headroom"] + 0.01, (
                f"Cluster {row['cluster_name']}: min_headroom "
                f"({row['min_headroom']}) > avg_headroom "
                f"({row['avg_headroom']})"
            )

    def test_headroom_excludes_crashed_ticks(self, agent_db, reference):
        """Verify the view excludes crashed-status ticks from computation."""
        # Count total non-crashed ticks for beta from reference
        beta_noncrushed = sum(
            1
            for s in reference["time_series"]
            if s["clusters"]["beta"]["status"] != "crashed"
        )
        # The view's aggregation should be based on this count
        total_cs_rows = agent_db.execute(
            "SELECT COUNT(*) FROM cluster_states "
            "WHERE cluster_name='beta' AND status != 'crashed'"
        ).fetchone()[0]
        assert total_cs_rows == beta_noncrushed, (
            f"Expected {beta_noncrushed} non-crashed ticks for beta, "
            f"got {total_cs_rows} in cluster_states"
        )
