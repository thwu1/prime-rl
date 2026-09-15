#!/usr/bin/env python3
"""Tests for protocol state machine inference, minimization, coverage, and visualization."""

import json
import os
import re
import sqlite3
import subprocess
import pytest


@pytest.fixture(scope="session", autouse=True)
def run_analyzer():
    """Run the analyzer before all tests."""
    result = subprocess.run(
        ["python3", "/app/analyzer.py"],
        capture_output=True, text=True, timeout=120, cwd="/app"
    )
    if result.returncode != 0:
        print("STDOUT:", result.stdout)
        print("STDERR:", result.stderr)
    assert result.returncode == 0, f"analyzer.py failed with code {result.returncode}: {result.stderr}"


# ---- Output file existence ----

class TestOutputFiles:
    def test_fsm_json_exists(self):
        assert os.path.isfile("/app/output/fsm.json")

    def test_minimized_fsm_json_exists(self):
        assert os.path.isfile("/app/output/minimized_fsm.json")

    def test_coverage_analysis_json_exists(self):
        assert os.path.isfile("/app/output/coverage_analysis.json")


# ---- FSM inference ----

class TestFSMInference:
    @pytest.fixture(autouse=True)
    def load_fsm(self):
        with open("/app/output/fsm.json") as f:
            self.fsm = json.load(f)

    def test_num_states(self):
        assert self.fsm["num_states"] == 10

    def test_num_transitions(self):
        assert self.fsm["num_transitions"] == 27

    def test_states_are_correct(self):
        assert set(self.fsm["states"]) == {0, 10, 21, 22, 24, 25, 30, 40, 41, 50}

    def test_states_sorted(self):
        assert self.fsm["states"] == sorted(self.fsm["states"])

    def test_connect_ok_transition(self):
        trans = {(t["from"], t["command"], t["to"]) for t in self.fsm["transitions"]}
        assert (0, 1, 10) in trans

    def test_connect_error_transition(self):
        trans = {(t["from"], t["command"], t["to"]) for t in self.fsm["transitions"]}
        assert (0, 1, 50) in trans

    def test_auth_ok_transition(self):
        trans = {(t["from"], t["command"], t["to"]) for t in self.fsm["transitions"]}
        assert (10, 2, 21) in trans

    def test_auth_fail_transition(self):
        trans = {(t["from"], t["command"], t["to"]) for t in self.fsm["transitions"]}
        assert (10, 2, 41) in trans

    def test_retr_read_transition(self):
        trans = {(t["from"], t["command"], t["to"]) for t in self.fsm["transitions"]}
        assert (22, 4, 24) in trans

    def test_stor_write_transition(self):
        trans = {(t["from"], t["command"], t["to"]) for t in self.fsm["transitions"]}
        assert (22, 5, 25) in trans

    def test_retr_error_transition(self):
        trans = {(t["from"], t["command"], t["to"]) for t in self.fsm["transitions"]}
        assert (22, 4, 50) in trans

    def test_self_loop_xfer_read(self):
        trans = {(t["from"], t["command"], t["to"]) for t in self.fsm["transitions"]}
        assert (24, 4, 24) in trans

    def test_self_loop_auth_fail(self):
        trans = {(t["from"], t["command"], t["to"]) for t in self.fsm["transitions"]}
        assert (41, 2, 41) in trans

    def test_no_outgoing_from_terminal(self):
        outgoing = [t for t in self.fsm["transitions"] if t["from"] == 30]
        assert len(outgoing) == 0

    def test_cross_transfer_type(self):
        """RETR from XFER_WRITE and STOR from XFER_READ should be observed."""
        trans = {(t["from"], t["command"], t["to"]) for t in self.fsm["transitions"]}
        assert (25, 4, 24) in trans
        assert (24, 5, 25) in trans

    def test_bad_request_recovery(self):
        trans = {(t["from"], t["command"], t["to"]) for t in self.fsm["transitions"]}
        assert (40, 3, 22) in trans


# ---- Bisimulation minimization ----

class TestMinimization:
    @pytest.fixture(autouse=True)
    def load_minimized(self):
        with open("/app/output/minimized_fsm.json") as f:
            self.min_fsm = json.load(f)

    def test_num_states_before(self):
        assert self.min_fsm["num_states_before"] == 10

    def test_num_states_after(self):
        assert self.min_fsm["num_states_after"] == 8

    def test_two_merges(self):
        assert len(self.min_fsm["merged_states"]) == 2

    def test_xfer_states_merged(self):
        """States 24 (XFER_READ) and 25 (XFER_WRITE) are behaviorally equivalent."""
        merged_sets = [set(m) for m in self.min_fsm["merged_states"]]
        assert {24, 25} in merged_sets

    def test_conn_authfail_merged(self):
        """States 10 (CONN_OK) and 41 (AUTH_FAIL) are behaviorally equivalent."""
        merged_sets = [set(m) for m in self.min_fsm["merged_states"]]
        assert {10, 41} in merged_sets

    def test_equivalence_classes_cover_all(self):
        all_states = set()
        for cls in self.min_fsm["equivalence_classes"]:
            all_states.update(cls)
        assert all_states == {0, 10, 21, 22, 24, 25, 30, 40, 41, 50}

    def test_equivalence_classes_partition(self):
        """No state appears in more than one equivalence class."""
        all_states = []
        for cls in self.min_fsm["equivalence_classes"]:
            all_states.extend(cls)
        assert len(all_states) == len(set(all_states))

    def test_singletons_not_merged(self):
        """States 0, 21, 22, 30, 40, 50 should each be in their own class."""
        singleton_states = {0, 21, 22, 30, 40, 50}
        for cls in self.min_fsm["equivalence_classes"]:
            if len(cls) == 1 and cls[0] in singleton_states:
                singleton_states.discard(cls[0])
        assert len(singleton_states) == 0, f"Missing singletons: {singleton_states}"


# ---- Coverage analysis ----

class TestCoverageAnalysis:
    @pytest.fixture(autouse=True)
    def load_coverage(self):
        with open("/app/output/coverage_analysis.json") as f:
            self.cov = json.load(f)

    def test_transition_coverage_ratio(self):
        assert abs(self.cov["transition_coverage"] - 0.9) < 0.01

    def test_uncovered_count(self):
        assert len(self.cov["uncovered_transitions"]) == 3

    def test_uncovered_stor_without_list(self):
        uncov = {(t["from"], t["command"], t["to"])
                 for t in self.cov["uncovered_transitions"]}
        assert (21, 5, 40) in uncov

    def test_uncovered_relist(self):
        uncov = {(t["from"], t["command"], t["to"])
                 for t in self.cov["uncovered_transitions"]}
        assert (22, 3, 22) in uncov

    def test_uncovered_reauth_bad_request(self):
        uncov = {(t["from"], t["command"], t["to"])
                 for t in self.cov["uncovered_transitions"]}
        assert (40, 2, 21) in uncov

    def test_total_unique_blocks_positive(self):
        assert self.cov["total_unique_blocks"] > 0

    def test_total_unique_blocks_bounded(self):
        assert self.cov["total_unique_blocks"] <= 500

    def test_total_blocks_matches_database(self):
        """Cross-check total_unique_blocks against coverage SQLite database."""
        conn = sqlite3.connect("/app/coverage.db")
        cursor = conn.execute("SELECT COUNT(DISTINCT block_id) FROM basic_block_coverage")
        expected = cursor.fetchone()[0]
        conn.close()
        assert self.cov["total_unique_blocks"] == expected

    def test_per_state_trace_count_exists(self):
        assert "per_state_trace_count" in self.cov

    def test_per_state_initial(self):
        assert self.cov["per_state_trace_count"]["0"] == 20

    def test_per_state_terminal(self):
        assert self.cov["per_state_trace_count"]["30"] == 20

    def test_per_state_conn_ok(self):
        assert self.cov["per_state_trace_count"]["10"] == 19

    def test_per_state_auth_ok(self):
        assert self.cov["per_state_trace_count"]["21"] == 17

    def test_per_state_list_ok(self):
        assert self.cov["per_state_trace_count"]["22"] == 15

    def test_per_state_xfer_read(self):
        assert self.cov["per_state_trace_count"]["24"] == 9

    def test_per_state_xfer_write(self):
        assert self.cov["per_state_trace_count"]["25"] == 7

    def test_per_state_bad_request(self):
        assert self.cov["per_state_trace_count"]["40"] == 2

    def test_per_state_auth_fail(self):
        assert self.cov["per_state_trace_count"]["41"] == 3

    def test_per_state_error(self):
        assert self.cov["per_state_trace_count"]["50"] == 3


# ---- Visualization output ----

class TestVisualization:
    def test_fsm_dot_exists(self):
        assert os.path.isfile("/app/output/fsm.dot")

    def test_fsm_svg_exists(self):
        assert os.path.isfile("/app/output/fsm.svg")

    def test_minimized_dot_exists(self):
        assert os.path.isfile("/app/output/minimized_fsm.dot")

    def test_minimized_svg_exists(self):
        assert os.path.isfile("/app/output/minimized_fsm.svg")

    def test_fsm_dot_structure(self):
        with open("/app/output/fsm.dot") as f:
            content = f.read()
        assert "digraph" in content
        assert "->" in content

    def test_fsm_svg_valid(self):
        with open("/app/output/fsm.svg") as f:
            content = f.read()
        assert "<svg" in content
        assert len(content) > 500

    def test_minimized_svg_valid(self):
        with open("/app/output/minimized_fsm.svg") as f:
            content = f.read()
        assert "<svg" in content
        assert len(content) > 500

    def test_fsm_svg_node_count(self):
        """Inferred FSM visualization should have exactly 10 state nodes."""
        with open("/app/output/fsm.svg") as f:
            content = f.read()
        node_count = content.count('class="node"')
        assert node_count == 10, f"Expected 10 nodes, got {node_count}"

    def test_minimized_svg_node_count(self):
        """Minimized FSM visualization should have exactly 8 state nodes."""
        with open("/app/output/minimized_fsm.svg") as f:
            content = f.read()
        node_count = content.count('class="node"')
        assert node_count == 8, f"Expected 8 nodes, got {node_count}"

    def test_minimized_fewer_edges(self):
        """Minimized FSM should have fewer edges than the original."""
        with open("/app/output/fsm.svg") as f:
            fsm = f.read()
        with open("/app/output/minimized_fsm.svg") as f:
            mini = f.read()
        fsm_edges = fsm.count('class="edge"')
        mini_edges = mini.count('class="edge"')
        assert mini_edges < fsm_edges, (
            f"Minimized edges ({mini_edges}) should be less than original ({fsm_edges})"
        )

    def test_fsm_dot_renders_cleanly(self):
        """The inferred FSM DOT file should render without graphviz errors."""
        result = subprocess.run(
            ["dot", "-Tsvg", "/app/output/fsm.dot"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"dot rendering failed: {result.stderr}"

    def test_minimized_dot_renders_cleanly(self):
        """The minimized FSM DOT file should render without graphviz errors."""
        result = subprocess.run(
            ["dot", "-Tsvg", "/app/output/minimized_fsm.dot"],
            capture_output=True, text=True, timeout=30
        )
        assert result.returncode == 0, f"dot rendering failed: {result.stderr}"
