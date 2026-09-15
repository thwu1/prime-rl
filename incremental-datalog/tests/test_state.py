"""
Tests for the incremental Datalog evaluator (Python script).

Verifies correctness of fixed-point evaluation, deletion handling,
cycle support, multi-predicate programs, multi-way joins, and
stratified negation.
"""

import subprocess
import json
import pytest

DATALOG = ["python3", "/app/datalog.py"]


def run_datalog(scenario, query):
    """Run the evaluator on a given scenario and return parsed output."""
    base = f"/data/{scenario}"
    result = subprocess.run(
        DATALOG + [
            "--rules", f"{base}/rules.dl",
            "--facts", f"{base}/facts.dl",
            "--updates", f"{base}/updates.dl",
            "--query", query,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"Process exited with code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    outputs = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line:
            outputs.append(json.loads(line))
    return outputs


# ---------------------------------------------------------------------------
# Scenario 1: Basic reachability with insertions and deletions
# ---------------------------------------------------------------------------
# Rules:
#   reach(X, Y) :- edge(X, Y).
#   reach(X, Y) :- reach(X, Z), edge(Z, Y).
# Facts: edge(1,2), edge(2,3), edge(3,4), edge(2,5)
# Updates:
#   batch 1: +edge(5,4)
#   batch 2: -edge(2,3)
#   batch 3: -edge(2,5)


class TestReachability:
    """Reachability: insertions, deletions with alternative paths, cascading."""

    def test_initial_state(self):
        outputs = run_datalog("reach", "reach")
        assert outputs[0]["batch"] == 0
        assert outputs[0]["tuples"] == [
            [1, 2], [1, 3], [1, 4], [1, 5],
            [2, 3], [2, 4], [2, 5],
            [3, 4],
        ]

    def test_insertion_adds_reachable_pair(self):
        """Batch 1: +edge(5,4) adds reach(5,4); existing paths unchanged."""
        outputs = run_datalog("reach", "reach")
        assert outputs[1]["batch"] == 1
        assert outputs[1]["tuples"] == [
            [1, 2], [1, 3], [1, 4], [1, 5],
            [2, 3], [2, 4], [2, 5],
            [3, 4],
            [5, 4],
        ]

    def test_deletion_preserves_alternative_paths(self):
        """Batch 2: -edge(2,3) removes paths via 2->3 but reach(1,4) and
        reach(2,4) survive via alternative path 2->5->4."""
        outputs = run_datalog("reach", "reach")
        assert outputs[2]["batch"] == 2
        assert outputs[2]["tuples"] == [
            [1, 2], [1, 4], [1, 5],
            [2, 4], [2, 5],
            [3, 4],
            [5, 4],
        ]

    def test_cascading_deletion(self):
        """Batch 3: -edge(2,5) removes the last alternative path from 1/2."""
        outputs = run_datalog("reach", "reach")
        assert outputs[3]["batch"] == 3
        assert outputs[3]["tuples"] == [
            [1, 2],
            [3, 4],
            [5, 4],
        ]


# ---------------------------------------------------------------------------
# Scenario 2: Reachability with cycles
# ---------------------------------------------------------------------------
# Facts: edge(1,2), edge(2,3), edge(3,1), edge(3,4)
# Updates:
#   batch 1: -edge(3,1) -- breaks the 1-2-3 cycle
#   batch 2: +edge(4,2) -- forms a new 2-3-4 cycle


class TestCycles:
    """Cycle creation and destruction in transitive closure."""

    def test_initial_cycle_creates_self_loops(self):
        """Cycle 1->2->3->1 produces self-reachability for all three nodes."""
        outputs = run_datalog("cycle", "reach")
        assert outputs[0]["batch"] == 0
        assert outputs[0]["tuples"] == [
            [1, 1], [1, 2], [1, 3], [1, 4],
            [2, 1], [2, 2], [2, 3], [2, 4],
            [3, 1], [3, 2], [3, 3], [3, 4],
        ]

    def test_cycle_break_removes_self_loops(self):
        """Batch 1: -edge(3,1) breaks cycle; linear chain 1->2->3->4."""
        outputs = run_datalog("cycle", "reach")
        assert outputs[1]["batch"] == 1
        assert outputs[1]["tuples"] == [
            [1, 2], [1, 3], [1, 4],
            [2, 3], [2, 4],
            [3, 4],
        ]

    def test_new_cycle_formation(self):
        """Batch 2: +edge(4,2) creates cycle 2->3->4->2;
        self-reachability for {2,3,4} but not 1."""
        outputs = run_datalog("cycle", "reach")
        assert outputs[2]["batch"] == 2
        assert outputs[2]["tuples"] == [
            [1, 2], [1, 3], [1, 4],
            [2, 2], [2, 3], [2, 4],
            [3, 2], [3, 3], [3, 4],
            [4, 2], [4, 3], [4, 4],
        ]


# ---------------------------------------------------------------------------
# Scenario 3: Multi-predicate SCC detection
# ---------------------------------------------------------------------------
# Rules:
#   path(X, Y) :- link(X, Y).
#   path(X, Y) :- path(X, Z), link(Z, Y).
#   scc(X, Y) :- path(X, Y), path(Y, X).
# Facts: link(1,2), link(2,3), link(3,1), link(4,5), link(5,4)
# Updates:
#   batch 1: +link(3,4) -- bridge, does not merge SCCs
#   batch 2: -link(3,1) -- dissolves SCC {1,2,3}


class TestSCC:
    """SCC detection: multi-predicate dependency, component splitting."""

    def test_initial_two_sccs(self):
        """Two SCCs: {1,2,3} and {4,5}."""
        outputs = run_datalog("scc", "scc")
        assert outputs[0]["batch"] == 0
        assert outputs[0]["tuples"] == [
            [1, 1], [1, 2], [1, 3],
            [2, 1], [2, 2], [2, 3],
            [3, 1], [3, 2], [3, 3],
            [4, 4], [4, 5],
            [5, 4], [5, 5],
        ]

    def test_one_way_bridge_does_not_merge(self):
        """Batch 1: +link(3,4) is a one-way bridge; SCCs unchanged."""
        outputs = run_datalog("scc", "scc")
        assert outputs[1]["batch"] == 1
        assert outputs[1]["tuples"] == [
            [1, 1], [1, 2], [1, 3],
            [2, 1], [2, 2], [2, 3],
            [3, 1], [3, 2], [3, 3],
            [4, 4], [4, 5],
            [5, 4], [5, 5],
        ]

    def test_scc_dissolves_on_cycle_break(self):
        """Batch 2: -link(3,1) breaks cycle in {1,2,3}; only {4,5} SCC remains."""
        outputs = run_datalog("scc", "scc")
        assert outputs[2]["batch"] == 2
        assert outputs[2]["tuples"] == [
            [4, 4], [4, 5],
            [5, 4], [5, 5],
        ]


# ---------------------------------------------------------------------------
# Scenario 4: Triangle detection (3-body rule, multi-way join)
# ---------------------------------------------------------------------------
# Rules:
#   triangle(X, Y, Z) :- edge(X, Y), edge(Y, Z), edge(X, Z).
# Facts: K4 directed (all 6 edges among {1,2,3,4} with i < j)
# Updates:
#   batch 1: -edge(2,4)
#   batch 2: +edge(2,4) -- restore


class TestTriangle:
    """Triangle enumeration via 3-body rule (multi-way join)."""

    def test_initial_k4_triangles(self):
        """K4 directed has 4 triangles."""
        outputs = run_datalog("triangle", "triangle")
        assert outputs[0]["batch"] == 0
        assert outputs[0]["tuples"] == [
            [1, 2, 3], [1, 2, 4], [1, 3, 4], [2, 3, 4],
        ]

    def test_edge_removal_drops_triangles(self):
        """Batch 1: -edge(2,4) removes triangles (1,2,4) and (2,3,4)."""
        outputs = run_datalog("triangle", "triangle")
        assert outputs[1]["batch"] == 1
        assert outputs[1]["tuples"] == [
            [1, 2, 3], [1, 3, 4],
        ]

    def test_edge_restoration_restores_triangles(self):
        """Batch 2: +edge(2,4) restores all 4 triangles."""
        outputs = run_datalog("triangle", "triangle")
        assert outputs[2]["batch"] == 2
        assert outputs[2]["tuples"] == [
            [1, 2, 3], [1, 2, 4], [1, 3, 4], [2, 3, 4],
        ]


# ---------------------------------------------------------------------------
# Scenario 5: Stratified negation (unreachable pairs)
# ---------------------------------------------------------------------------
# Rules:
#   reach(X, Y) :- edge(X, Y).
#   reach(X, Y) :- reach(X, Z), edge(Z, Y).
#   disconnected(X, Y) :- node(X), node(Y), not reach(X, Y).
# Facts: node(1..4), edge(1,2), edge(2,3)
# Updates:
#   batch 1: +edge(3,1) -- creates cycle, adds self-reachability
#   batch 2: +edge(3,4) -- extends reachability to node 4
#   batch 3: -edge(3,1) -- breaks cycle, removes self-reachability


class TestNegation:
    """Stratified negation: disconnected pairs via not-reachable."""

    def test_initial_disconnected_pairs(self):
        """Initial graph 1->2->3 with 4 isolated.
        reach = {(1,2),(1,3),(2,3)}.
        disconnected = all 16 node pairs minus reach = 13 pairs."""
        outputs = run_datalog("negation", "disconnected")
        assert outputs[0]["batch"] == 0
        assert outputs[0]["tuples"] == [
            [1, 1], [1, 4],
            [2, 1], [2, 2], [2, 4],
            [3, 1], [3, 2], [3, 3], [3, 4],
            [4, 1], [4, 2], [4, 3], [4, 4],
        ]

    def test_cycle_reduces_disconnected(self):
        """Batch 1: +edge(3,1) creates cycle 1->2->3->1.
        Self-reachability added for {1,2,3}. reach has 9 pairs.
        disconnected drops to 7 pairs (only involving node 4)."""
        outputs = run_datalog("negation", "disconnected")
        assert outputs[1]["batch"] == 1
        assert outputs[1]["tuples"] == [
            [1, 4],
            [2, 4],
            [3, 4],
            [4, 1], [4, 2], [4, 3], [4, 4],
        ]

    def test_extended_reach_further_reduces(self):
        """Batch 2: +edge(3,4) makes 4 reachable from {1,2,3}.
        reach has 12 pairs. disconnected drops to 4 pairs."""
        outputs = run_datalog("negation", "disconnected")
        assert outputs[2]["batch"] == 2
        assert outputs[2]["tuples"] == [
            [4, 1], [4, 2], [4, 3], [4, 4],
        ]

    def test_cycle_break_restores_disconnected(self):
        """Batch 3: -edge(3,1) breaks cycle. Linear chain 1->2->3->4.
        reach has 6 pairs. disconnected rises to 10 pairs."""
        outputs = run_datalog("negation", "disconnected")
        assert outputs[3]["batch"] == 3
        assert outputs[3]["tuples"] == [
            [1, 1],
            [2, 1], [2, 2],
            [3, 1], [3, 2], [3, 3],
            [4, 1], [4, 2], [4, 3], [4, 4],
        ]
