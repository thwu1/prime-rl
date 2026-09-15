"""
Tests for KVCache Store Eviction Simulator.

"""

import subprocess
import json
import os
import pytest

CONFIG = {
    "total_capacity_bytes": 1000,
    "lease_ttl_sec": 5,
    "soft_pin_ttl_sec": 20,
    "allow_evict_soft_pinned": True,
}


def run_simulator(config, trace):
    """Run the simulator with the given config and trace, return parsed JSON output."""
    config_path = "/tmp/test_config.json"
    trace_path = "/tmp/test_trace.jsonl"
    with open(config_path, "w") as f:
        json.dump(config, f)
    with open(trace_path, "w") as f:
        for op in trace:
            f.write(json.dumps(op) + "\n")
    try:
        result = subprocess.run(
            ["python3", "/app/simulator.py", "--config", config_path, "--trace", trace_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"Simulator exited with code {result.returncode}.\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
        return json.loads(result.stdout)
    finally:
        for p in (config_path, trace_path):
            if os.path.exists(p):
                os.unlink(p)


# ---------------------------------------------------------------------------
# Basic LRU eviction
# ---------------------------------------------------------------------------


class TestBasicLRU:
    def test_no_eviction_when_under_capacity(self):
        """Objects stored without eviction when total size fits."""
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 300},
            {"t": 1, "op": "PUT", "key": "B", "size": 300},
            {"t": 2, "op": "PUT", "key": "C", "size": 300},
        ]
        r = run_simulator(CONFIG, trace)
        assert r["stats"]["evictions_count"] == 0
        assert r["final_used_bytes"] == 900
        assert set(r["final_state"].keys()) == {"A", "B", "C"}

    def test_lru_eviction_order(self):
        """Oldest object (by last_access_time) is evicted first."""
        # A(400)@0, B(400)@1 -> used=800
        # PUT C(400): 800+400=1200 > 1000. Need 200.
        # LRU: A(0), B(1). Evict A(400).
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 400},
            {"t": 1, "op": "PUT", "key": "B", "size": 400},
            {"t": 2, "op": "PUT", "key": "C", "size": 400},
        ]
        r = run_simulator(CONFIG, trace)
        assert r["stats"]["evictions_count"] == 1
        assert r["stats"]["bytes_evicted"] == 400
        assert "A" not in r["final_state"]
        assert "B" in r["final_state"]
        assert "C" in r["final_state"]
        assert r["final_used_bytes"] == 800
        evictions = [e for e in r["events"] if e["type"] == "eviction"]
        assert evictions[0]["key"] == "A"

    def test_multiple_evictions_single_put(self):
        """Multiple objects evicted by one PUT when needed > single object size."""
        # A(300)@0, B(300)@1, C(300)@2 -> used=900
        # PUT D(500): 900+500=1400 > 1000. Need 400.
        # LRU: A(0), B(1), C(2). Evict A(300) -> 300 < 400. Evict B(300) -> 600 >= 400.
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 300},
            {"t": 1, "op": "PUT", "key": "B", "size": 300},
            {"t": 2, "op": "PUT", "key": "C", "size": 300},
            {"t": 3, "op": "PUT", "key": "D", "size": 500},
        ]
        r = run_simulator(CONFIG, trace)
        assert r["stats"]["evictions_count"] == 2
        assert r["stats"]["bytes_evicted"] == 600
        assert set(r["final_state"].keys()) == {"C", "D"}
        assert r["final_used_bytes"] == 800

    def test_lru_tiebreak_by_key(self):
        """When last_access_time is equal, lower key name is evicted first."""
        # Both put at t=0, same access time. Key "A" < "B" lexicographically.
        trace = [
            {"t": 0, "op": "PUT", "key": "B", "size": 400},
            {"t": 0, "op": "PUT", "key": "A", "size": 400},
            {"t": 1, "op": "PUT", "key": "C", "size": 400},
        ]
        r = run_simulator(CONFIG, trace)
        evictions = [e for e in r["events"] if e["type"] == "eviction"]
        assert len(evictions) == 1
        assert evictions[0]["key"] == "A"  # "A" < "B"


# ---------------------------------------------------------------------------
# Hard pin
# ---------------------------------------------------------------------------


class TestHardPin:
    def test_hard_pin_skipped_during_eviction(self):
        """Hard-pinned objects are never evicted."""
        # A(400, hard_pin)@0, B(400)@1 -> used=800
        # PUT C(400): need 200. A is hard_pinned -> skip. Evict B(400).
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 400, "hard_pin": True},
            {"t": 1, "op": "PUT", "key": "B", "size": 400},
            {"t": 2, "op": "PUT", "key": "C", "size": 400},
        ]
        r = run_simulator(CONFIG, trace)
        assert r["stats"]["evictions_count"] == 1
        assert "A" in r["final_state"]
        assert r["final_state"]["A"]["hard_pin"] is True
        assert "B" not in r["final_state"]
        assert "C" in r["final_state"]

    def test_put_fails_only_hard_pinned_remain(self):
        """PUT fails when only hard-pinned objects exist and capacity is insufficient."""
        # A(600, hard_pin)@0 -> used=600
        # PUT B(500): 600+500=1100 > 1000. Need 100.
        # No evictable objects (A is hard-pinned). PUT FAILS.
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 600, "hard_pin": True},
            {"t": 1, "op": "PUT", "key": "B", "size": 500},
        ]
        r = run_simulator(CONFIG, trace)
        assert r["stats"]["failed_puts"] == 1
        assert "B" not in r["final_state"]
        assert "A" in r["final_state"]
        assert r["final_used_bytes"] == 600

    def test_put_fails_not_enough_evictable(self):
        """Atomic eviction: if can't free enough, nothing is evicted."""
        # A(400, hard_pin)@0, B(200)@1 -> used=600
        # PUT C(800): 600+800=1400 > 1000. Need 400.
        # Evictable: B(200). 200 < 400. Atomic: don't evict. PUT FAILS.
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 400, "hard_pin": True},
            {"t": 1, "op": "PUT", "key": "B", "size": 200},
            {"t": 2, "op": "PUT", "key": "C", "size": 800},
        ]
        r = run_simulator(CONFIG, trace)
        assert r["stats"]["failed_puts"] == 1
        assert r["stats"]["evictions_count"] == 0
        assert "B" in r["final_state"]  # NOT evicted (atomic)
        assert "A" in r["final_state"]
        assert "C" not in r["final_state"]
        assert r["final_used_bytes"] == 600


# ---------------------------------------------------------------------------
# Lease protection
# ---------------------------------------------------------------------------


class TestLease:
    def test_leased_object_protected(self):
        """Oldest object is leased, so next oldest is evicted instead."""
        # old(400)@0. GET old@1 -> lease until 6.
        # new(400)@2 -> used=800
        # PUT newer(400)@3: need 200.
        # LRU: old(1), new(2). old leased (3 < 6) -> skip. Evict new(400).
        trace = [
            {"t": 0, "op": "PUT", "key": "old", "size": 400},
            {"t": 1, "op": "GET", "key": "old"},
            {"t": 2, "op": "PUT", "key": "new", "size": 400},
            {"t": 3, "op": "PUT", "key": "newer", "size": 400},
        ]
        r = run_simulator(CONFIG, trace)
        assert r["stats"]["cache_hits"] == 1
        assert "old" in r["final_state"]
        assert "new" not in r["final_state"]
        assert "newer" in r["final_state"]

    def test_lease_expires_allows_eviction(self):
        """After lease TTL expires, object becomes evictable again."""
        # A(400)@0. GET A@1 -> lease until 6. B(400)@2 -> used=800.
        # PUT C(400)@7: need 200.
        # A: lease_expiry=6, t=7 > 6 -> NOT leased. last_access=1.
        # B: last_access=2.
        # LRU: A(1), B(2). Evict A.
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 400},
            {"t": 1, "op": "GET", "key": "A"},
            {"t": 2, "op": "PUT", "key": "B", "size": 400},
            {"t": 7, "op": "PUT", "key": "C", "size": 400},
        ]
        r = run_simulator(CONFIG, trace)
        assert "A" not in r["final_state"]
        assert "B" in r["final_state"]
        assert "C" in r["final_state"]

    def test_get_refreshes_lease(self):
        """Multiple GETs extend the lease via max semantics."""
        # A(400)@0. GET A@1 -> lease=6. GET A@4 -> lease=max(6,9)=9.
        # B(400)@5 -> used=800.
        # PUT C(400)@7: need 200.
        # A: lease=9, 7 < 9 -> LEASED, skip.
        # B: last_access=5, not leased. Evict B.
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 400},
            {"t": 1, "op": "GET", "key": "A"},
            {"t": 4, "op": "GET", "key": "A"},
            {"t": 5, "op": "PUT", "key": "B", "size": 400},
            {"t": 7, "op": "PUT", "key": "C", "size": 400},
        ]
        r = run_simulator(CONFIG, trace)
        assert "A" in r["final_state"]
        assert "B" not in r["final_state"]
        assert "C" in r["final_state"]

    def test_cache_hit_and_miss(self):
        """GET on existing key is hit; on non-existent key is miss."""
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 300},
            {"t": 1, "op": "GET", "key": "A"},
            {"t": 2, "op": "GET", "key": "B"},
            {"t": 3, "op": "GET", "key": "A"},
        ]
        r = run_simulator(CONFIG, trace)
        assert r["stats"]["cache_hits"] == 2
        assert r["stats"]["cache_misses"] == 1

    def test_get_nonexistent_key(self):
        """GET on empty cache is a miss."""
        trace = [{"t": 0, "op": "GET", "key": "X"}]
        r = run_simulator(CONFIG, trace)
        assert r["stats"]["cache_misses"] == 1
        assert r["stats"]["cache_hits"] == 0


# ---------------------------------------------------------------------------
# Soft pin
# ---------------------------------------------------------------------------


class TestSoftPin:
    def test_soft_pin_deprioritized(self):
        """Soft-pinned objects are skipped in phase 1; non-pinned evicted first."""
        # A(300)@0 + SOFT_PIN -> soft_pin until 20.
        # B(300)@1, C(300)@2 -> used=900.
        # PUT D(300)@3: 900+300=1200 > 1000. Need 200.
        # Phase 1: B(1), C(2). A is soft-pinned -> phase 2.
        # Evict B(300). freed=300 >= 200.
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 300},
            {"t": 0, "op": "SOFT_PIN", "key": "A"},
            {"t": 1, "op": "PUT", "key": "B", "size": 300},
            {"t": 2, "op": "PUT", "key": "C", "size": 300},
            {"t": 3, "op": "PUT", "key": "D", "size": 300},
        ]
        r = run_simulator(CONFIG, trace)
        assert "A" in r["final_state"]  # soft-pinned, not evicted
        assert "B" not in r["final_state"]  # evicted (oldest non-soft-pinned)
        assert "C" in r["final_state"]
        assert "D" in r["final_state"]

    def test_soft_pin_evicted_in_phase2(self):
        """When phase 1 isn't enough, soft-pinned objects are evicted in phase 2."""
        # A(400)@0 + SOFT_PIN. B(400)@1 + SOFT_PIN. C(100)@2 -> used=900.
        # PUT D(500)@3: 900+500=1400 > 1000. Need 400.
        # Phase 1: C(2). Select C(100). 100 < 400.
        # Phase 2: A(0), B(1). Select A(400). 100+400=500 >= 400.
        # Evict C, A.
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 400},
            {"t": 0, "op": "SOFT_PIN", "key": "A"},
            {"t": 1, "op": "PUT", "key": "B", "size": 400},
            {"t": 1, "op": "SOFT_PIN", "key": "B"},
            {"t": 2, "op": "PUT", "key": "C", "size": 100},
            {"t": 3, "op": "PUT", "key": "D", "size": 500},
        ]
        r = run_simulator(CONFIG, trace)
        assert "A" not in r["final_state"]
        assert "B" in r["final_state"]
        assert "C" not in r["final_state"]
        assert "D" in r["final_state"]
        assert r["stats"]["evictions_count"] == 2
        assert r["stats"]["bytes_evicted"] == 500
        # Verify order: C (phase 1) before A (phase 2)
        evictions = [e for e in r["events"] if e["type"] == "eviction"]
        assert len(evictions) == 2
        assert evictions[0]["key"] == "C"
        assert evictions[1]["key"] == "A"

    def test_soft_pin_expires(self):
        """After soft pin TTL, object is treated as non-soft-pinned in phase 1."""
        # A(400)@0 + SOFT_PIN (expires at 20). B(400)@1 -> used=800.
        # PUT C(400)@21: need 200.
        # A: soft_pin_expiry=20, t=21 > 20 -> not soft-pinned.
        # Phase 1: A(0), B(1). LRU: A first. Evict A.
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 400},
            {"t": 0, "op": "SOFT_PIN", "key": "A"},
            {"t": 1, "op": "PUT", "key": "B", "size": 400},
            {"t": 21, "op": "PUT", "key": "C", "size": 400},
        ]
        r = run_simulator(CONFIG, trace)
        assert "A" not in r["final_state"]
        assert "B" in r["final_state"]
        assert "C" in r["final_state"]

    def test_get_refreshes_soft_pin(self):
        """GET on a soft-pinned object refreshes its TTL."""
        # A(400)@0 + SOFT_PIN (expires 20). B(400)@1 -> used=800.
        # GET A@15: A is soft-pinned (15 < 20) -> refresh to 35. A.last_access=15.
        # PUT C(400)@21: need 200.
        # A: soft_pin_expiry=35 (21 < 35 -> still soft-pinned). Phase 2 only.
        # Phase 1: B(1). Evict B(400).
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 400},
            {"t": 0, "op": "SOFT_PIN", "key": "A"},
            {"t": 1, "op": "PUT", "key": "B", "size": 400},
            {"t": 15, "op": "GET", "key": "A"},
            {"t": 21, "op": "PUT", "key": "C", "size": 400},
        ]
        r = run_simulator(CONFIG, trace)
        assert "A" in r["final_state"]  # still soft-pinned, protected
        assert "B" not in r["final_state"]  # evicted
        assert "C" in r["final_state"]


# ---------------------------------------------------------------------------
# REMOVE
# ---------------------------------------------------------------------------


class TestRemove:
    def test_basic_remove(self):
        """REMOVE deletes an unprotected object and frees space."""
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 300},
            {"t": 1, "op": "PUT", "key": "B", "size": 300},
            {"t": 2, "op": "REMOVE", "key": "A"},
        ]
        r = run_simulator(CONFIG, trace)
        assert "A" not in r["final_state"]
        assert "B" in r["final_state"]
        assert r["final_used_bytes"] == 300

    def test_remove_leased_fails(self):
        """REMOVE on a leased object fails."""
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 300},
            {"t": 1, "op": "GET", "key": "A"},  # lease until 6
            {"t": 2, "op": "REMOVE", "key": "A"},  # fails: leased
        ]
        r = run_simulator(CONFIG, trace)
        assert "A" in r["final_state"]
        assert r["final_used_bytes"] == 300
        failed = [e for e in r["events"] if e["type"] == "remove_failed"]
        assert len(failed) == 1

    def test_remove_hard_pinned_fails(self):
        """REMOVE on a hard-pinned object fails."""
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 300, "hard_pin": True},
            {"t": 1, "op": "REMOVE", "key": "A"},
        ]
        r = run_simulator(CONFIG, trace)
        assert "A" in r["final_state"]
        failed = [e for e in r["events"] if e["type"] == "remove_failed"]
        assert len(failed) == 1


# ---------------------------------------------------------------------------
# PUT overwrite
# ---------------------------------------------------------------------------


class TestPutOverwrite:
    def test_overwrite_existing_key(self):
        """PUT on existing key replaces the object (size changes, space freed)."""
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 300},
            {"t": 1, "op": "PUT", "key": "B", "size": 300},
            {"t": 2, "op": "PUT", "key": "A", "size": 200},
        ]
        r = run_simulator(CONFIG, trace)
        assert r["final_state"]["A"]["size"] == 200
        assert r["final_used_bytes"] == 500

    def test_overwrite_clears_hard_pin(self):
        """Overwriting a hard-pinned key without hard_pin removes the pin."""
        # A(400, hard_pin)@0. Overwrite A(400, no pin)@1.
        # B(400)@2 -> used=800.
        # PUT C(400)@3: need 200. A: no longer hard-pinned, last_access=1. B: last_access=2.
        # LRU: A(1). Evict A.
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 400, "hard_pin": True},
            {"t": 1, "op": "PUT", "key": "A", "size": 400},
            {"t": 2, "op": "PUT", "key": "B", "size": 400},
            {"t": 3, "op": "PUT", "key": "C", "size": 400},
        ]
        r = run_simulator(CONFIG, trace)
        assert "A" not in r["final_state"]  # was hard-pinned, then overwritten
        assert "B" in r["final_state"]
        assert "C" in r["final_state"]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_put_exceeding_total_capacity(self):
        """PUT with size > total_capacity always fails (no objects to evict either)."""
        trace = [{"t": 0, "op": "PUT", "key": "A", "size": 1500}]
        r = run_simulator(CONFIG, trace)
        assert r["stats"]["failed_puts"] == 1
        assert r["final_used_bytes"] == 0
        assert len(r["final_state"]) == 0

    def test_remove_nonexistent_is_noop(self):
        """REMOVE on non-existent key produces no event and no error."""
        trace = [{"t": 0, "op": "REMOVE", "key": "ghost"}]
        r = run_simulator(CONFIG, trace)
        assert len(r["events"]) == 0
        assert r["final_used_bytes"] == 0

    def test_soft_pin_nonexistent_is_noop(self):
        """SOFT_PIN on non-existent key produces no error."""
        trace = [{"t": 0, "op": "SOFT_PIN", "key": "ghost"}]
        r = run_simulator(CONFIG, trace)
        assert len(r["final_state"]) == 0


# ---------------------------------------------------------------------------
# Combined scenario
# ---------------------------------------------------------------------------


class TestCombined:
    def test_all_mechanisms(self):
        """Complex scenario exercising hard pin, soft pin, lease, and LRU together."""
        trace = [
            # System prompt: hard-pinned
            {"t": 0, "op": "PUT", "key": "sys", "size": 200, "hard_pin": True},
            # User session: soft-pinned
            {"t": 1, "op": "PUT", "key": "usr1", "size": 150},
            {"t": 1, "op": "SOFT_PIN", "key": "usr1"},
            # Another user session
            {"t": 2, "op": "PUT", "key": "usr2", "size": 150},
            # Temporary objects
            {"t": 3, "op": "PUT", "key": "tmp1", "size": 100},
            {"t": 4, "op": "PUT", "key": "tmp2", "size": 100},
            # Access usr2 -> leased until 10
            {"t": 5, "op": "GET", "key": "usr2"},
            # Another temp
            {"t": 6, "op": "PUT", "key": "tmp3", "size": 100},
            # used = 200+150+150+100+100+100 = 800
            # PUT big(400): 800+400=1200 > 1000. Need 200.
            # Phase 1 (non-soft-pinned, non-leased, non-hard-pinned):
            #   sys: hard_pin -> excluded
            #   usr1: soft_pin(7 < 21) -> excluded (phase 2)
            #   usr2: leased(7 < 10) -> excluded
            #   tmp1(3), tmp2(4), tmp3(6): all eligible
            # LRU: tmp1(3), tmp2(4), tmp3(6).
            # Select tmp1(100) -> 100 < 200. Select tmp2(100) -> 200 >= 200.
            # Evict tmp1, tmp2. PUT big.
            {"t": 7, "op": "PUT", "key": "big", "size": 400},
        ]
        r = run_simulator(CONFIG, trace)
        assert r["stats"]["cache_hits"] == 1  # GET usr2
        assert r["stats"]["evictions_count"] == 2
        assert r["stats"]["bytes_evicted"] == 200

        assert "sys" in r["final_state"]
        assert r["final_state"]["sys"]["hard_pin"] is True
        assert "usr1" in r["final_state"]
        assert "usr2" in r["final_state"]
        assert "tmp1" not in r["final_state"]
        assert "tmp2" not in r["final_state"]
        assert "tmp3" in r["final_state"]
        assert "big" in r["final_state"]
        assert r["final_used_bytes"] == 1000

        # Verify eviction order
        evictions = [e for e in r["events"] if e["type"] == "eviction"]
        assert evictions[0]["key"] == "tmp1"
        assert evictions[1]["key"] == "tmp2"

    def test_lease_and_soft_pin_interaction(self):
        """Object that is both leased and soft-pinned is double-protected."""
        # A(400)@0, SOFT_PIN A. GET A@1 -> leased until 6, soft_pin refreshed to 21.
        # B(400)@2 -> used=800.
        # PUT C(400)@3: need 200.
        # A: leased(3 < 6) AND soft-pinned(3 < 21) -> excluded from both phases.
        # Phase 1: B(2). Evict B(400).
        trace = [
            {"t": 0, "op": "PUT", "key": "A", "size": 400},
            {"t": 0, "op": "SOFT_PIN", "key": "A"},
            {"t": 1, "op": "GET", "key": "A"},
            {"t": 2, "op": "PUT", "key": "B", "size": 400},
            {"t": 3, "op": "PUT", "key": "C", "size": 400},
        ]
        r = run_simulator(CONFIG, trace)
        assert "A" in r["final_state"]
        assert "B" not in r["final_state"]
        assert "C" in r["final_state"]
