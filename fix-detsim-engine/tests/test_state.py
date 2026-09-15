
"""Verification tests for the deterministic simulation testing pipeline.

Tests check:
1. Determinism — same seed produces same event trace.
2. Buggify determinism — same seed produces same fault decisions.
3. Partition symmetry — partition(a,b) blocks both a->b and b->a.
4. Checker correctness — safety checker detects missing committed writes.
5. Replication correctness — committed entries survive partition/heal/sync.
6. Campaign config — valid JSON with required fault-injection phases.
7. End-to-end — campaign runs on fixed code with zero violations.
8. Analysis — comprehensive report covering required topics.
"""

import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, "/app")

from detsim.rng import DetRng
from detsim.engine import SimEngine
from detsim.network import Network
from detsim.buggify import Buggify
from detsim.tracer import TraceDB
from replication.protocol import Replica, Entry
from checker.safety import SafetyChecker


# -- helpers -----------------------------------------------------------------

def _make_cluster(seed, n=3, latency=(0.005, 0.050)):
    rng = DetRng(seed)
    eng = SimEngine(rng)
    net = Network(eng, rng, latency=latency)
    nodes = [Replica(i, list(range(n)), net, eng) for i in range(n)]
    return rng, eng, net, nodes


def _run_replication_scenario(seed):
    """Standard partition / heal / sync scenario returning (nodes, committed)."""
    _rng, eng, net, nodes = _make_cluster(seed, n=3)

    # Phase 1: writes committed under original primary (node 0)
    nodes[0].become_primary()
    nodes[0].write("a", "1")
    eng.run(until=0.2)
    nodes[0].write("b", "2")
    eng.run(until=0.5)

    committed = {}
    for k in ("a", "b"):
        v = nodes[0].read(k)
        if v is not None:
            committed[k] = v

    # Phase 2: partition {0} vs {1, 2}
    net.partition(0, 1)
    net.partition(0, 2)

    # Old primary writes (minority => cannot commit)
    nodes[0].write("c", "3")
    eng.run(until=0.7)

    # Phase 3: new primary on majority side
    nodes[1].become_primary()
    nodes[1].write("d", "4")
    eng.run(until=1.2)

    # Phase 4: heal and sync
    net.heal(0, 1)
    net.heal(0, 2)
    nodes[1].initiate_sync()
    eng.run(until=2.5)

    return nodes, committed


# -- Test: Determinism -------------------------------------------------------

class TestDeterminism:
    """Verify that the simulation engine is fully deterministic."""

    def test_same_seed_produces_same_trace(self):
        """Running the same seed twice must yield identical event traces."""
        for seed in range(20):
            traces = []
            for _ in range(2):
                _rng, eng, _net, nodes = _make_cluster(seed)
                nodes[0].become_primary()
                for i in range(5):
                    nodes[0].write(f"k{i}", f"v{i}")
                eng.run(until=2.0)
                traces.append(eng.trace)
            assert traces[0] == traces[1], (
                f"Seed {seed}: traces differ "
                f"(len {len(traces[0])} vs {len(traces[1])}). "
                f"First divergence around entry "
                f"{next((i for i, (a, b) in enumerate(zip(traces[0], traces[1])) if a != b), '?')}"
            )

    def test_different_seeds_produce_different_traces(self):
        """Different seeds should (usually) produce distinct traces."""
        unique = set()
        for seed in range(10):
            _rng, eng, _net, nodes = _make_cluster(seed)
            nodes[0].become_primary()
            nodes[0].write("x", "1")
            eng.run(until=1.0)
            unique.add(tuple(eng.trace))
        assert len(unique) >= 5, (
            f"Only {len(unique)} distinct traces from 10 seeds -- "
            "the RNG may not be wired correctly"
        )


# -- Test: Buggify Determinism -----------------------------------------------

class TestBuggifyDeterminism:
    """Verify that buggify decisions are deterministic for a given seed."""

    def test_should_fault_deterministic(self):
        """should_fault() must return identical results for the same seed."""
        for seed in range(20):
            results = []
            for _ in range(2):
                rng = DetRng(seed)
                bug = Buggify(rng)
                bug.enable()
                decisions = [bug.should_fault() for _ in range(50)]
                results.append(tuple(decisions))
            assert results[0] == results[1], (
                f"Seed {seed}: buggify decisions differ between runs. "
                f"First divergence at index "
                f"{next((i for i, (a, b) in enumerate(zip(results[0], results[1])) if a != b), '?')}"
            )

    def test_maybe_delay_deterministic(self):
        """maybe_delay() must return identical values for the same seed."""
        for seed in range(10):
            delays = []
            for _ in range(2):
                rng = DetRng(seed)
                bug = Buggify(rng)
                bug.enable()
                d = [bug.maybe_delay(0.05) for _ in range(30)]
                delays.append(d)
            assert delays[0] == delays[1], (
                f"Seed {seed}: maybe_delay not deterministic"
            )


# -- Test: Partition Symmetry -------------------------------------------------

class TestPartitionSymmetry:
    """Verify that partitions are bidirectional."""

    def test_partition_blocks_both_directions(self):
        rng = DetRng(0)
        eng = SimEngine(rng)
        net = Network(eng, rng)
        net.partition(1, 2)
        assert net.is_partitioned(1, 2), "partition(1,2) should block 1->2"
        assert net.is_partitioned(2, 1), "partition(1,2) should also block 2->1"

    def test_heal_restores_both_directions(self):
        rng = DetRng(0)
        eng = SimEngine(rng)
        net = Network(eng, rng)
        net.partition(3, 7)
        net.heal(3, 7)
        assert not net.is_partitioned(3, 7), "heal(3,7) should unblock 3->7"
        assert not net.is_partitioned(7, 3), "heal(3,7) should unblock 7->3"

    def test_partition_does_not_leak_to_unrelated_nodes(self):
        rng = DetRng(0)
        eng = SimEngine(rng)
        net = Network(eng, rng)
        net.partition(1, 2)
        assert not net.is_partitioned(1, 3), "1->3 should not be partitioned"
        assert not net.is_partitioned(3, 2), "3->2 should not be partitioned"

    def test_multiple_partitions_independent(self):
        rng = DetRng(0)
        eng = SimEngine(rng)
        net = Network(eng, rng)
        net.partition(0, 1)
        net.partition(0, 2)
        net.heal(0, 1)
        assert not net.is_partitioned(0, 1)
        assert not net.is_partitioned(1, 0)
        assert net.is_partitioned(0, 2)
        assert net.is_partitioned(2, 0)


# -- Test: Checker Correctness ------------------------------------------------

class TestCheckerCorrectness:
    """Verify the safety checker correctly detects durability violations."""

    def test_checker_detects_missing_committed_write(self):
        """A committed key missing from a node must be flagged as DURABILITY violation."""
        db_path = tempfile.mktemp(suffix=".db")
        try:
            tracer = TraceDB(db_path)

            # Record a committed write for key "x"
            tracer.log_event(0.15, 999, "commit", src=0,
                             detail={"key": "x", "value": "42"})

            # Node 0 has the key
            tracer._conn.execute(
                "INSERT INTO node_states(sim_time,seed,node_id,term,role,"
                "log_length,commit_idx,store_json) VALUES(?,?,?,?,?,?,?,?)",
                (2.5, 999, 0, 2, "follower", 3, 2, json.dumps({"x": "42"})))

            # Node 1 is MISSING the key (data loss)
            tracer._conn.execute(
                "INSERT INTO node_states(sim_time,seed,node_id,term,role,"
                "log_length,commit_idx,store_json) VALUES(?,?,?,?,?,?,?,?)",
                (2.5, 999, 1, 2, "follower", 2, 1, json.dumps({})))

            # Node 2 has the key
            tracer._conn.execute(
                "INSERT INTO node_states(sim_time,seed,node_id,term,role,"
                "log_length,commit_idx,store_json) VALUES(?,?,?,?,?,?,?,?)",
                (2.5, 999, 2, 2, "follower", 3, 2, json.dumps({"x": "42"})))

            tracer.flush()

            checker = SafetyChecker(db_path)
            result = checker.check_seed(999)
            assert not result["passed"], (
                f"Checker must detect missing committed key 'x' on node 1. "
                f"Got: {result}"
            )
            assert any("DURABILITY" in v for v in result["violations"]), (
                f"Expected a DURABILITY violation. Got: {result['violations']}"
            )

            tracer.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_checker_passes_correct_state(self):
        """When all nodes have all committed keys, checker must pass."""
        db_path = tempfile.mktemp(suffix=".db")
        try:
            tracer = TraceDB(db_path)

            tracer.log_event(0.15, 888, "commit", src=0,
                             detail={"key": "y", "value": "99"})

            for nid in range(3):
                tracer._conn.execute(
                    "INSERT INTO node_states(sim_time,seed,node_id,term,role,"
                    "log_length,commit_idx,store_json) VALUES(?,?,?,?,?,?,?,?)",
                    (2.5, 888, nid, 2, "follower", 3, 2,
                     json.dumps({"y": "99"})))

            tracer.flush()

            checker = SafetyChecker(db_path)
            result = checker.check_seed(888)
            assert result["passed"], (
                f"Checker should pass when all nodes agree. Got: {result}"
            )

            tracer.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)


# -- Test: Replication Correctness --------------------------------------------

class TestReplicationCorrectness:
    """Verify that committed writes survive partition / heal / sync."""

    def test_committed_writes_survive_partition(self):
        """Committed entries must be present on ALL nodes after sync."""
        for seed in range(50):
            nodes, committed = _run_replication_scenario(seed)
            assert committed, f"Seed {seed}: no committed data recorded"
            for node in nodes:
                for key, expected in committed.items():
                    actual = node.read(key)
                    assert actual == expected, (
                        f"Seed {seed}, node {node.nid}: "
                        f"committed key '{key}' expected '{expected}' "
                        f"got '{actual}'. store={node.store} "
                        f"log={[repr(e) for e in node.log]}"
                    )

    def test_new_primary_writes_visible_after_sync(self):
        """Writes committed by the new primary should be on all nodes."""
        for seed in range(20):
            nodes, _ = _run_replication_scenario(seed)
            for node in nodes:
                assert node.read("d") == "4", (
                    f"Seed {seed}, node {node.nid}: "
                    f"new-primary write 'd'='4' missing. store={node.store}"
                )

    def test_uncommitted_write_overwritten(self):
        """The old primary's uncommitted write ('c') should NOT survive."""
        for seed in range(20):
            nodes, _ = _run_replication_scenario(seed)
            for node in nodes:
                assert node.read("c") is None, (
                    f"Seed {seed}, node {node.nid}: "
                    f"uncommitted key 'c' should not survive. store={node.store}"
                )


# -- Test: Campaign Config ----------------------------------------------------

class TestCampaignConfig:
    """Verify the campaign config is valid and meaningful."""

    def test_config_exists_and_valid_json(self):
        path = "/app/campaign_config.json"
        assert os.path.isfile(path), f"{path} does not exist"
        with open(path) as f:
            config = json.load(f)
        assert "seeds" in config, "Config must have 'seeds' field"
        assert "phases" in config, "Config must have 'phases' field"
        assert "nodes" in config or config.get("phases"), "Config must specify nodes"

    def test_config_has_fault_injection_phases(self):
        with open("/app/campaign_config.json") as f:
            config = json.load(f)
        actions = [p["action"] for p in config["phases"]]
        assert "partition" in actions, "Campaign must include partition phases"
        assert "heal" in actions, "Campaign must include heal phases"
        assert "write" in actions, "Campaign must include write phases"
        assert "sync" in actions, "Campaign must include sync phases"
        assert "elect" in actions, "Campaign must include elect phases"

    def test_config_runs_enough_seeds(self):
        with open("/app/campaign_config.json") as f:
            config = json.load(f)
        seed_range = config["seeds"]["end"] - config["seeds"]["start"] + 1
        assert seed_range >= 30, (
            f"Campaign must test at least 30 seeds, got {seed_range}"
        )

    def test_campaign_runs_clean_on_fixed_code(self):
        """The campaign must produce zero violations on the fixed protocol."""
        result = subprocess.run(
            ["python3", "/app/campaign.py",
             "--config", "/app/campaign_config.json",
             "--db", "/tmp/test_campaign.db",
             "--report", "/tmp/test_report.json"],
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, (
            f"Campaign failed on fixed code:\nstdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
        with open("/tmp/test_report.json") as f:
            report = json.load(f)
        assert report["safety_check"]["seeds_with_violations"] == 0, (
            f"Fixed protocol must have 0 violations, "
            f"got {report['safety_check']['seeds_with_violations']}"
        )


# -- Test: Analysis -----------------------------------------------------------

class TestAnalysis:
    """Check that the analysis report is comprehensive."""

    def test_analysis_exists_and_sufficient_length(self):
        path = "/app/results/analysis.md"
        assert os.path.isfile(path), f"{path} does not exist"
        with open(path) as f:
            content = f.read()
        assert len(content) >= 500, (
            f"analysis.md is too short ({len(content)} chars); "
            "expected a comprehensive report"
        )

    def test_analysis_covers_key_topics(self):
        with open("/app/results/analysis.md") as f:
            content = f.read()
        cl = content.lower()
        assert any(w in cl for w in ["determinism", "deterministic",
                                      "nondeterministic", "non-deterministic"]), \
            "Analysis must discuss determinism"
        assert any(w in cl for w in ["buggify", "fault injection",
                                      "fault-injection"]), \
            "Analysis must discuss buggify / fault injection"
        assert "partition" in cl, \
            "Analysis must discuss network partitions"
        assert any(w in cl for w in ["durability", "safety", "committed",
                                      "data loss"]), \
            "Analysis must discuss safety / durability properties"

    def test_analysis_includes_sql_queries(self):
        with open("/app/results/analysis.md") as f:
            content = f.read()
        assert "SELECT" in content or "select" in content.lower(), \
            "Analysis must include SQL queries used for trace analysis"
