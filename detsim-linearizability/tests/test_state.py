
import json
import os
import sqlite3
import subprocess
import sys
import tempfile

import pytest

# Expected classifications for all 16 pre-generated runs.
# Determined by running a reference linearizability checker on the traces.
EXPECTED = {
    "1":  {"linearizable": True,  "violation": "none",        "has_multi_primary": False},
    "2":  {"linearizable": True,  "violation": "none",        "has_multi_primary": False},
    "3":  {"linearizable": True,  "violation": "none",        "has_multi_primary": False},
    "4":  {"linearizable": True,  "violation": "none",        "has_multi_primary": False},
    "5":  {"linearizable": False, "violation": "split_brain",  "has_multi_primary": True},
    "6":  {"linearizable": True,  "violation": "none",        "has_multi_primary": True},
    "7":  {"linearizable": True,  "violation": "none",        "has_multi_primary": True},
    "8":  {"linearizable": True,  "violation": "none",        "has_multi_primary": False},
    "9":  {"linearizable": False, "violation": "split_brain",  "has_multi_primary": True},
    "10": {"linearizable": True,  "violation": "none",        "has_multi_primary": False},
    "11": {"linearizable": False, "violation": "split_brain",  "has_multi_primary": True},
    "12": {"linearizable": True,  "violation": "none",        "has_multi_primary": False},
    "13": {"linearizable": False, "violation": "split_brain",  "has_multi_primary": True},
    "14": {"linearizable": False, "violation": "split_brain",  "has_multi_primary": True},
    "15": {"linearizable": True,  "violation": "none",        "has_multi_primary": False},
    "16": {"linearizable": False, "violation": "split_brain",  "has_multi_primary": True},
}


class TestResultsJSON:
    """Verify /app/results.json matches expected classifications."""

    @pytest.fixture(autouse=True)
    def load_results(self):
        path = "/app/results.json"
        assert os.path.exists(path), "results.json not found at /app/results.json"
        with open(path) as f:
            self.results = json.load(f)

    def test_all_runs_present(self):
        for rid in EXPECTED:
            assert rid in self.results, f"Missing run {rid} in results.json"

    @pytest.mark.parametrize("run_id", list(EXPECTED.keys()))
    def test_linearizability(self, run_id):
        expected = EXPECTED[run_id]["linearizable"]
        got = self.results[run_id]["linearizable"]
        assert got == expected, (
            f"Run {run_id}: expected linearizable={expected}, got {got}"
        )

    @pytest.mark.parametrize("run_id", list(EXPECTED.keys()))
    def test_violation_type(self, run_id):
        expected = EXPECTED[run_id]["violation"]
        got = self.results[run_id]["violation"]
        assert got == expected, (
            f"Run {run_id}: expected violation={expected}, got {got}"
        )

    @pytest.mark.parametrize("run_id", list(EXPECTED.keys()))
    def test_multi_primary_detection(self, run_id):
        expected = EXPECTED[run_id]["has_multi_primary"]
        got = self.results[run_id]["has_multi_primary"]
        assert got == expected, (
            f"Run {run_id}: expected has_multi_primary={expected}, got {got}"
        )


class TestPipelineExecution:
    """Verify pipeline.py can be executed and produces correct output."""

    def test_pipeline_runs_successfully(self):
        """pipeline.py must execute without error and produce results.json."""
        # Remove existing results to force regeneration
        if os.path.exists("/app/results.json"):
            os.remove("/app/results.json")
        result = subprocess.run(
            [sys.executable, "/app/pipeline.py"],
            capture_output=True, text=True, cwd="/app", timeout=180,
        )
        assert result.returncode == 0, f"pipeline.py failed:\n{result.stderr}"
        assert os.path.exists("/app/results.json"), "pipeline.py did not create results.json"
        with open("/app/results.json") as f:
            data = json.load(f)
        # Verify all 16 runs are present and correct
        for rid in EXPECTED:
            assert rid in data, f"pipeline.py output missing run {rid}"
            assert data[rid]["linearizable"] == EXPECTED[rid]["linearizable"], (
                f"pipeline.py wrong for run {rid}"
            )


def _run_dessim_and_check(config_path, seed):
    """Run dessim with a config, return (linearizable, ops_by_node, multi)."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_db = tmp.name
    try:
        result = subprocess.run(
            ["dessim", "run", "--config", config_path, "--db", tmp_db, "--seed", str(seed)],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"dessim run failed: {result.stderr}"

        conn = sqlite3.connect(tmp_db)
        run_id = conn.execute("SELECT MAX(run_id) FROM runs").fetchone()[0]

        # Extract operations
        rows = conn.execute(
            "SELECT op_type, arg, invoke_time, response_time, response_value, target_node "
            "FROM operations WHERE run_id=? ORDER BY invoke_time",
            (run_id,),
        ).fetchall()

        ops = []
        ops_by_node = {}
        for r in rows:
            rval = r[4]
            if rval is not None:
                rval = json.loads(rval)
            op = {
                "op_type": r[0], "arg": r[1], "invoke_time": r[2],
                "response_time": r[3], "response_value": rval, "target_node": r[5],
            }
            ops.append(op)
            node = r[5]
            if node is not None:
                ops_by_node.setdefault(node, []).append(op)

        # Check multi-primary
        multi = conn.execute(
            "SELECT COUNT(*) FROM ("
            "  SELECT time FROM node_states WHERE run_id=? AND role='primary'"
            "  GROUP BY time HAVING COUNT(DISTINCT node_id) > 1"
            ")",
            (run_id,),
        ).fetchone()[0] > 0

        conn.close()

        # Simple linearizability check (DFS)
        lin = _is_linearizable(ops)
        return lin, ops_by_node, multi
    finally:
        if os.path.exists(tmp_db):
            os.unlink(tmp_db)


def _is_linearizable(ops):
    from itertools import combinations
    completed = [o for o in ops if o["response_time"] is not None]
    crashed = [o for o in ops if o["response_time"] is None]
    for r in range(len(crashed) + 1):
        for subset in combinations(crashed, r):
            all_ops = completed + list(subset)
            if _check_lin(all_ops, 0):
                return True
    return False


def _check_lin(ops, init_val):
    if not ops:
        return True
    n = len(ops)
    return _dfs(ops, init_val, [False] * n, 0, n)


def _dfs(ops, state, done, count, total):
    if count == total:
        return True
    for i in range(total):
        if done[i]:
            continue
        op = ops[i]
        can_go = True
        for j in range(total):
            if done[j] or j == i:
                continue
            other = ops[j]
            other_resp = other["response_time"] if other["response_time"] is not None else float("inf")
            if other_resp < op["invoke_time"]:
                can_go = False
                break
        if not can_go:
            continue
        ns, m = _apply_op(op, state)
        if m:
            done[i] = True
            if _dfs(ops, ns, done, count + 1, total):
                return True
            done[i] = False
    return False


def _apply_op(op, state):
    if op["op_type"] == "write":
        return op["arg"], True
    elif op["op_type"] == "read":
        rval = op["response_value"]
        if rval is None:
            return state, True
        return state, rval == state
    return state, False


class TestFaultConfigSplitBrain:
    """Verify trigger_split_brain.toml produces a non-linearizable trace."""

    def test_config_exists(self):
        assert os.path.exists("/app/fault_configs/trigger_split_brain.toml"), \
            "trigger_split_brain.toml not found"

    def test_triggers_split_brain(self):
        lin, ops_by_node, multi = _run_dessim_and_check(
            "/app/fault_configs/trigger_split_brain.toml", 7777
        )
        assert not lin, "Config with seed 7777 should produce non-linearizable trace"
        assert multi, "Config should cause multiple simultaneous primaries"


class TestFaultConfigExtendedSplit:
    """Verify trigger_extended_split.toml produces extended split-brain."""

    def test_config_exists(self):
        assert os.path.exists("/app/fault_configs/trigger_extended_split.toml"), \
            "trigger_extended_split.toml not found"

    def test_triggers_extended_split(self):
        lin, ops_by_node, multi = _run_dessim_and_check(
            "/app/fault_configs/trigger_extended_split.toml", 8888
        )
        assert not lin, "Config with seed 8888 should produce non-linearizable trace"
        assert multi, "Config should cause multiple simultaneous primaries"

        # Find partition period - check that multiple nodes served ops
        primary_nodes = [n for n, ol in ops_by_node.items() if len(ol) >= 5]
        assert len(primary_nodes) >= 2, (
            f"Expected at least 2 nodes with >= 5 ops each during split, "
            f"got nodes with ops: {{{', '.join(f'{n}: {len(ol)}' for n, ol in sorted(ops_by_node.items()))}}}"
        )


class TestDeterminism:
    """Verify the pipeline produces deterministic results."""

    def test_deterministic_across_runs(self):
        """Running pipeline.py twice should produce identical results."""
        result1 = subprocess.run(
            [sys.executable, "/app/pipeline.py"],
            capture_output=True, text=True, cwd="/app", timeout=180,
        )
        assert result1.returncode == 0
        with open("/app/results.json") as f:
            data1 = json.load(f)

        result2 = subprocess.run(
            [sys.executable, "/app/pipeline.py"],
            capture_output=True, text=True, cwd="/app", timeout=180,
        )
        assert result2.returncode == 0
        with open("/app/results.json") as f:
            data2 = json.load(f)

        assert data1 == data2, "Pipeline produced different results on second run"
