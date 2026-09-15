
import json
import os
import sqlite3

import pytest

RESULTS_PATH = "/app/results.json"
ORIGINAL_DB = "/app/.cache_state_backup.db"
CONFIG_PATH = "/app/config.json"
TRACE_PATH = "/app/upcoming_requests.json"


@pytest.fixture(scope="session")
def config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def trace():
    with open(TRACE_PATH) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def trace_by_id(trace):
    return {r["request_id"]: r for r in trace}


@pytest.fixture(scope="session")
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


@pytest.fixture(scope="session")
def db():
    assert os.path.exists(ORIGINAL_DB), "Backup DB not found"
    conn = sqlite3.connect(ORIGINAL_DB)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


# ------------------------------------------------------------------
# Ground-truth helpers
# ------------------------------------------------------------------

def get_zombie_ids(db, config):
    threshold = config["current_time_ms"] - config["zombie_timeout_ms"]
    rows = db.execute(
        "SELECT block_id FROM blocks WHERE status='init' AND put_start_time IS NOT NULL AND put_start_time < ?",
        (threshold,),
    ).fetchall()
    return sorted(r["block_id"] for r in rows)


def get_expired_soft_pin_ids(db, config):
    threshold = config["current_time_ms"] - config["soft_pin_ttl_ms"]
    rows = db.execute(
        "SELECT block_id FROM blocks WHERE pin_type='soft' AND last_accessed < ?",
        (threshold,),
    ).fetchall()
    return sorted(r["block_id"] for r in rows)


def get_orphaned_chain_ids(db):
    rows = db.execute("""
        SELECT pc.hash_id FROM prefix_chains pc
        WHERE pc.parent_hash_id IS NOT NULL
          AND pc.parent_hash_id NOT IN (SELECT hash_id FROM prefix_chains)
    """).fetchall()
    return sorted(r["hash_id"] for r in rows)


def get_hard_pin_ids(db):
    rows = db.execute(
        "SELECT block_id FROM blocks WHERE pin_type='hard'"
    ).fetchall()
    return set(r["block_id"] for r in rows)


def node_block_counts(db):
    rows = db.execute(
        "SELECT node_id, COUNT(*) as cnt FROM blocks GROUP BY node_id"
    ).fetchall()
    return {r["node_id"]: r["cnt"] for r in rows}


def node_capacities(db):
    rows = db.execute("SELECT node_id, capacity_blocks FROM nodes").fetchall()
    return {r["node_id"]: r["capacity_blocks"] for r in rows}


def prefill_nodes(db):
    rows = db.execute(
        "SELECT node_id FROM nodes WHERE node_type='prefill'"
    ).fetchall()
    return set(r["node_id"] for r in rows)


def decode_nodes(db):
    rows = db.execute(
        "SELECT node_id FROM nodes WHERE node_type='decode'"
    ).fetchall()
    return set(r["node_id"] for r in rows)


def hash_exists_on_node(db, hash_id, node_id):
    row = db.execute(
        "SELECT 1 FROM blocks WHERE hash_id=? AND node_id=? AND status='complete' LIMIT 1",
        (hash_id, node_id),
    ).fetchone()
    return row is not None


# ==================================================================
# Test classes
# ==================================================================

class TestResultsStructure:
    def test_file_exists(self):
        assert os.path.exists(RESULTS_PATH)

    def test_valid_json(self, results):
        assert isinstance(results, dict)

    def test_has_diagnostic(self, results):
        assert "diagnostic" in results
        d = results["diagnostic"]
        for key in ("zombie_blocks", "expired_soft_pins", "orphaned_chains",
                     "overloaded_nodes", "underloaded_nodes"):
            assert key in d, f"Missing diagnostic key: {key}"

    def test_has_schedule(self, results, trace):
        assert "schedule" in results
        assert isinstance(results["schedule"], list)
        assert len(results["schedule"]) == len(trace), (
            f"Schedule has {len(results['schedule'])} entries, expected {len(trace)}"
        )

    def test_has_metrics(self, results):
        assert "metrics" in results
        m = results["metrics"]
        for key in ("total_requests", "cache_hit_rate",
                     "zombie_blocks_cleaned", "soft_pins_cleared"):
            assert key in m, f"Missing metrics key: {key}"


class TestDiagnostics:
    def test_zombie_block_recall(self, results, db, config):
        """Solver must find at least 90% of actual zombie blocks."""
        expected = set(get_zombie_ids(db, config))
        reported = set(results["diagnostic"]["zombie_blocks"])
        found = expected & reported
        recall = len(found) / len(expected) if expected else 1.0
        assert recall >= 0.90, (
            f"Zombie recall {recall:.2f} < 0.90 "
            f"(found {len(found)}/{len(expected)})"
        )

    def test_no_false_zombie_positives(self, results, db, config):
        """Recent init blocks must NOT appear in zombie list."""
        threshold = config["current_time_ms"] - config["zombie_timeout_ms"]
        recent = db.execute(
            "SELECT block_id FROM blocks WHERE status='init' AND put_start_time IS NOT NULL AND put_start_time >= ?",
            (threshold,),
        ).fetchall()
        recent_ids = set(r["block_id"] for r in recent)
        reported = set(results["diagnostic"]["zombie_blocks"])
        false_pos = recent_ids & reported
        assert len(false_pos) == 0, f"False zombie positives: {false_pos}"

    def test_expired_soft_pin_recall(self, results, db, config):
        """Solver must find at least 90% of expired soft pins."""
        expected = set(get_expired_soft_pin_ids(db, config))
        reported = set(results["diagnostic"]["expired_soft_pins"])
        found = expected & reported
        recall = len(found) / len(expected) if expected else 1.0
        assert recall >= 0.90, (
            f"Expired pin recall {recall:.2f} < 0.90 "
            f"(found {len(found)}/{len(expected)})"
        )

    def test_no_active_pin_false_positives(self, results, db, config):
        """Active soft pins must NOT appear in expired list."""
        threshold = config["current_time_ms"] - config["soft_pin_ttl_ms"]
        active = db.execute(
            "SELECT block_id FROM blocks WHERE pin_type='soft' AND last_accessed >= ?",
            (threshold,),
        ).fetchall()
        active_ids = set(r["block_id"] for r in active)
        reported = set(results["diagnostic"]["expired_soft_pins"])
        false_pos = active_ids & reported
        assert len(false_pos) == 0, f"False expired-pin positives: {false_pos}"

    def test_orphaned_chains(self, results, db):
        """At least 80% of orphaned chains identified."""
        expected = set(get_orphaned_chain_ids(db))
        reported = set(results["diagnostic"]["orphaned_chains"])
        found = expected & reported
        recall = len(found) / len(expected) if expected else 1.0
        assert recall >= 0.80, (
            f"Orphan recall {recall:.2f} < 0.80 "
            f"(found {len(found)}/{len(expected)})"
        )

    def test_overloaded_nodes_identified(self, results, db, config):
        """Nodes above target_max_node_utilization must be reported."""
        counts = node_block_counts(db)
        caps = node_capacities(db)
        threshold = config["target_max_node_utilization"]
        expected = {n for n in counts if counts[n] / caps.get(n, 1) > threshold}
        reported = set(results["diagnostic"]["overloaded_nodes"])
        assert expected <= reported, (
            f"Missing overloaded nodes: {expected - reported}"
        )

    def test_underloaded_nodes_identified(self, results, db):
        """Nodes below 40% utilization should be reported as underloaded."""
        counts = node_block_counts(db)
        caps = node_capacities(db)
        expected = {n for n in caps
                    if counts.get(n, 0) / caps[n] < 0.40
                    and caps[n] > 0}
        reported = set(results["diagnostic"]["underloaded_nodes"])
        # Must report at least the clearly underloaded ones
        clearly_under = {n for n in expected
                         if counts.get(n, 0) / caps[n] < 0.35}
        assert clearly_under <= reported, (
            f"Missing underloaded nodes: {clearly_under - reported}"
        )


class TestConstraints:
    def test_no_hard_pin_eviction(self, results, db):
        """Hard-pinned blocks must NOT appear in eviction or cleanup."""
        hard = get_hard_pin_ids(db)
        evicted = set()
        for action in results.get("rebalance_plan", []):
            if action.get("action") == "evict":
                evicted.add(action.get("block_id"))
        for action in results.get("cleanup_actions", []):
            evicted.add(action.get("block_id"))
        violations = hard & evicted
        assert len(violations) == 0, (
            f"Hard-pinned blocks in eviction plan: {violations}"
        )

    def test_schedule_uses_valid_prefill_nodes(self, results, db):
        pnodes = prefill_nodes(db)
        for entry in results["schedule"]:
            assert entry["prefill_node"] in pnodes, (
                f"Request {entry['request_id']} assigned to non-prefill "
                f"node {entry['prefill_node']}"
            )

    def test_schedule_uses_valid_decode_nodes(self, results, db):
        dnodes = decode_nodes(db)
        for entry in results["schedule"]:
            assert entry["decode_node"] in dnodes, (
                f"Request {entry['request_id']} assigned to non-decode "
                f"node {entry['decode_node']}"
            )

    def test_all_requests_scheduled(self, results, trace):
        scheduled_ids = {e["request_id"] for e in results["schedule"]}
        trace_ids = {r["request_id"] for r in trace}
        assert trace_ids == scheduled_ids, (
            f"Missing: {trace_ids - scheduled_ids}, "
            f"Extra: {scheduled_ids - trace_ids}"
        )

    def test_capacity_after_cleanup(self, results, db):
        """After removing zombies, no node must exceed capacity."""
        counts = dict(node_block_counts(db))
        caps = node_capacities(db)
        # Subtract cleanup removals
        removed_ids = set()
        for action in results.get("cleanup_actions", []):
            bid = action.get("block_id")
            if bid:
                removed_ids.add(bid)
        for bid in removed_ids:
            row = db.execute(
                "SELECT node_id FROM blocks WHERE block_id=?", (bid,)
            ).fetchone()
            if row:
                counts[row["node_id"]] = counts.get(row["node_id"], 0) - 1
        # Subtract evictions from rebalance
        for action in results.get("rebalance_plan", []):
            if action.get("action") == "evict":
                bid = action.get("block_id")
                row = db.execute(
                    "SELECT node_id FROM blocks WHERE block_id=?", (bid,)
                ).fetchone()
                if row and bid not in removed_ids:
                    counts[row["node_id"]] = counts.get(row["node_id"], 0) - 1
                    removed_ids.add(bid)
        # Apply moves
        for action in results.get("rebalance_plan", []):
            if action.get("action") == "move":
                fn = action.get("from_node")
                tn = action.get("to_node")
                if fn and tn:
                    counts[fn] = counts.get(fn, 0) - 1
                    counts[tn] = counts.get(tn, 0) + 1

        for nid, cap in caps.items():
            cnt = counts.get(nid, 0)
            assert cnt <= cap, (
                f"Node {nid} exceeds capacity after plan: {cnt}/{cap}"
            )


class TestPerformance:
    def test_cache_hit_rate_meets_target(self, results, db, config, trace_by_id):
        """Compute actual cache hit rate from original placement + routing."""
        total_hits = 0
        total_blocks = 0
        for entry in results["schedule"]:
            req = trace_by_id[entry["request_id"]]
            node = entry["prefill_node"]
            for hid in req["hash_ids"]:
                total_blocks += 1
                if hash_exists_on_node(db, hid, node):
                    total_hits += 1

        hit_rate = total_hits / total_blocks if total_blocks > 0 else 0
        target = config["target_cache_hit_rate"]
        assert hit_rate >= target, (
            f"Cache hit rate {hit_rate:.4f} < target {target}"
        )

    def test_hit_miss_consistency(self, results, trace_by_id):
        """Each request's hits + misses must equal total hash count."""
        for entry in results["schedule"]:
            req = trace_by_id[entry["request_id"]]
            total = len(req["hash_ids"])
            reported = entry["cache_hits"] + entry["cache_misses"]
            assert reported == total, (
                f"Request {entry['request_id']}: "
                f"hits({entry['cache_hits']})+misses({entry['cache_misses']})="
                f"{reported} != {total} hash_ids"
            )


class TestMetricsConsistency:
    def test_total_requests(self, results, trace):
        assert results["metrics"]["total_requests"] == len(trace)

    def test_zombie_count_matches_diagnostic(self, results):
        assert results["metrics"]["zombie_blocks_cleaned"] == len(
            results["diagnostic"]["zombie_blocks"]
        )

    def test_soft_pin_count_matches_diagnostic(self, results):
        assert results["metrics"]["soft_pins_cleared"] == len(
            results["diagnostic"]["expired_soft_pins"]
        )

    def test_cache_hit_rate_matches_schedule(self, results):
        total_hits = sum(e["cache_hits"] for e in results["schedule"])
        total = sum(
            e["cache_hits"] + e["cache_misses"] for e in results["schedule"]
        )
        reported = results["metrics"]["cache_hit_rate"]
        computed = total_hits / total if total > 0 else 0
        assert abs(reported - computed) < 0.02, (
            f"Reported hit rate {reported} != computed {computed:.4f}"
        )
