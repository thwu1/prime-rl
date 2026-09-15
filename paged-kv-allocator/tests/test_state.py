"""Tests for KV cache block allocator -- bug fixes, prefix caching, and eviction."""

import json
import os
import sqlite3
import subprocess

import pytest

ALLOCATOR = "/app/allocator.py"
CONFIG = "/app/config.json"
WORKLOAD_DB = "/app/workload.db"
RESULTS = "/app/results.json"

DEFAULT_CONFIG = {
    "num_layers": 4,
    "num_kv_heads": 4,
    "head_dim": 64,
    "dtype_bytes": 2,
    "block_size": 4,
    "num_gpu_blocks": 50,
}


def write_config(cfg):
    """Overwrite the config file."""
    with open(CONFIG, "w") as f:
        json.dump(cfg, f)


def write_workload_db(workload):
    """Write a workload to the SQLite database."""
    if os.path.exists(WORKLOAD_DB):
        os.remove(WORKLOAD_DB)
    conn = sqlite3.connect(WORKLOAD_DB)
    conn.execute(
        "CREATE TABLE operations ("
        "  step_id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  op_type TEXT NOT NULL,"
        "  seq_id TEXT,"
        "  prompt_length INTEGER,"
        "  num_tokens INTEGER,"
        "  source_seq_id TEXT,"
        "  new_seq_id TEXT"
        ")"
    )
    conn.execute(
        "CREATE TABLE block_hashes ("
        "  step_id INTEGER NOT NULL,"
        "  position INTEGER NOT NULL,"
        "  block_hash TEXT NOT NULL,"
        "  PRIMARY KEY (step_id, position),"
        "  FOREIGN KEY (step_id) REFERENCES operations(step_id)"
        ")"
    )
    for entry in workload:
        cursor = conn.execute(
            "INSERT INTO operations "
            "(op_type, seq_id, prompt_length, num_tokens, "
            "source_seq_id, new_seq_id) VALUES (?, ?, ?, ?, ?, ?)",
            (
                entry.get("op"),
                entry.get("seq_id"),
                entry.get("prompt_length"),
                entry.get("num_tokens"),
                entry.get("source_seq_id"),
                entry.get("new_seq_id"),
            ),
        )
        if "block_hashes" in entry:
            for pos, h in enumerate(entry["block_hashes"]):
                conn.execute(
                    "INSERT INTO block_hashes "
                    "(step_id, position, block_hash) VALUES (?, ?, ?)",
                    (cursor.lastrowid, pos, h),
                )
    conn.commit()
    conn.close()


def run_allocator():
    """Run the allocator and return parsed results."""
    if os.path.exists(RESULTS):
        os.remove(RESULTS)
    result = subprocess.run(
        ["python3", ALLOCATOR],
        cwd="/app",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Allocator exited with code {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert os.path.exists(RESULTS), "results.json was not created"
    with open(RESULTS) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Workload 1: nested forks, 3 CoW copies, peak 14
# ---------------------------------------------------------------------------
# Tests bug fixes: fork copy semantics, CoW fill level, block reclamation,
# and peak tracking during decode.

WORKLOAD_1 = [
    {"op": "prefill", "seq_id": "s0", "prompt_length": 10},
    {"op": "prefill", "seq_id": "s1", "prompt_length": 7},
    {"op": "fork", "source_seq_id": "s0", "new_seq_id": "s0_a"},
    {"op": "fork", "source_seq_id": "s0", "new_seq_id": "s0_b"},
    {"op": "decode", "seq_id": "s0", "num_tokens": 6},
    {"op": "decode", "seq_id": "s0_a", "num_tokens": 2},
    {"op": "fork", "source_seq_id": "s0_a", "new_seq_id": "s0_a1"},
    {"op": "decode", "seq_id": "s0_a", "num_tokens": 4},
    {"op": "decode", "seq_id": "s0_a1", "num_tokens": 4},
    {"op": "decode", "seq_id": "s0_b", "num_tokens": 6},
    {"op": "fork", "source_seq_id": "s1", "new_seq_id": "s1_a"},
    {"op": "decode", "seq_id": "s1", "num_tokens": 3},
    {"op": "decode", "seq_id": "s1_a", "num_tokens": 3},
    {"op": "free", "seq_id": "s0"},
    {"op": "free", "seq_id": "s0_a"},
    {"op": "free", "seq_id": "s0_a1"},
    {"op": "free", "seq_id": "s0_b"},
    {"op": "free", "seq_id": "s1"},
    {"op": "free", "seq_id": "s1_a"},
]

EXPECTED_1 = {
    "per_token_kv_bytes": 4096,
    "total_blocks_allocated": 14,
    "total_cow_copies": 3,
    "peak_blocks_used": 14,
    "final_blocks_used": 0,
    "wasted_slots_at_peak": 5,
    "prefix_cache_hits": 0,
    "prefix_cache_misses": 0,
    "evictions_performed": 0,
}


# ---------------------------------------------------------------------------
# Workload 2: full-block fork -- 0 CoW, peak 5
# ---------------------------------------------------------------------------
# When last block is full AND shared, decode must allocate a new block
# (not copy-on-write). Tests correct CoW trigger condition.

WORKLOAD_2 = [
    {"op": "prefill", "seq_id": "x", "prompt_length": 8},
    {"op": "fork", "source_seq_id": "x", "new_seq_id": "y"},
    {"op": "fork", "source_seq_id": "x", "new_seq_id": "z"},
    {"op": "decode", "seq_id": "y", "num_tokens": 1},
    {"op": "decode", "seq_id": "z", "num_tokens": 1},
    {"op": "decode", "seq_id": "x", "num_tokens": 1},
    {"op": "free", "seq_id": "x"},
    {"op": "free", "seq_id": "y"},
    {"op": "free", "seq_id": "z"},
]

EXPECTED_2 = {
    "per_token_kv_bytes": 4096,
    "total_blocks_allocated": 5,
    "total_cow_copies": 0,
    "peak_blocks_used": 5,
    "final_blocks_used": 0,
    "wasted_slots_at_peak": 9,
    "prefix_cache_hits": 0,
    "prefix_cache_misses": 0,
    "evictions_performed": 0,
}


# ---------------------------------------------------------------------------
# Workload 3: prefix caching with decode
# ---------------------------------------------------------------------------
# Two requests share a prompt prefix via cached prefill. Decode appends
# tokens independently. Tests cache hit counting, peak tracking with
# cached blocks, and correct final_blocks_used including retained cache.

WORKLOAD_3 = [
    {"op": "prefill_cached", "seq_id": "p0", "prompt_length": 8,
     "block_hashes": ["H1", "H2"]},
    {"op": "prefill_cached", "seq_id": "p1", "prompt_length": 8,
     "block_hashes": ["H1", "H2"]},
    {"op": "decode", "seq_id": "p0", "num_tokens": 2},
    {"op": "decode", "seq_id": "p1", "num_tokens": 3},
    {"op": "free", "seq_id": "p0"},
    {"op": "free", "seq_id": "p1"},
]

EXPECTED_3 = {
    "per_token_kv_bytes": 4096,
    "total_blocks_allocated": 4,
    "total_cow_copies": 0,
    "peak_blocks_used": 4,
    "final_blocks_used": 2,
    "wasted_slots_at_peak": 5,
    "prefix_cache_hits": 2,
    "prefix_cache_misses": 2,
    "evictions_performed": 0,
}


# ---------------------------------------------------------------------------
# Workload 4: prefix cache persistence across free/prefill
# ---------------------------------------------------------------------------
# A cached block retained at ref=0 is reused by a later request.
# Tests that cache entries survive sequence free operations.

WORKLOAD_4 = [
    {"op": "prefill_cached", "seq_id": "r0", "prompt_length": 4,
     "block_hashes": ["HA"]},
    {"op": "free", "seq_id": "r0"},
    {"op": "prefill_cached", "seq_id": "r1", "prompt_length": 8,
     "block_hashes": ["HA", "HB"]},
    {"op": "free", "seq_id": "r1"},
]

EXPECTED_4 = {
    "per_token_kv_bytes": 4096,
    "total_blocks_allocated": 2,
    "total_cow_copies": 0,
    "peak_blocks_used": 2,
    "final_blocks_used": 2,
    "wasted_slots_at_peak": 0,
    "prefix_cache_hits": 1,
    "prefix_cache_misses": 2,
    "evictions_performed": 0,
}


# ---------------------------------------------------------------------------
# Workload 5: eviction under memory pressure + CoW + prefix caching
# ---------------------------------------------------------------------------
# Uses a tight 5-block pool. Cached blocks are evicted via LRU when
# the free pool is exhausted during decode. Also tests fork/CoW with
# prefix caching and verifies that non-evicted cached blocks survive.
# Config override: num_gpu_blocks=5.

WORKLOAD_5_CONFIG = {
    "num_layers": 4,
    "num_kv_heads": 4,
    "head_dim": 64,
    "dtype_bytes": 2,
    "block_size": 4,
    "num_gpu_blocks": 5,
}

WORKLOAD_5 = [
    # Cache two full blocks
    {"op": "prefill_cached", "seq_id": "e0", "prompt_length": 8,
     "block_hashes": ["HA", "HB"]},
    # Regular prefill with partial last block
    {"op": "prefill", "seq_id": "e1", "prompt_length": 6},
    # Fork e1 (creates shared partial block)
    {"op": "fork", "source_seq_id": "e1", "new_seq_id": "e1f"},
    # Free e0 -- cached blocks retained at ref=0
    {"op": "free", "seq_id": "e0"},
    # Decode e1 triggers CoW on shared partial block
    {"op": "decode", "seq_id": "e1", "num_tokens": 1},
    # Decode e1f on the now-private block
    {"op": "decode", "seq_id": "e1f", "num_tokens": 1},
    # More decode on e1 -- second token forces eviction (pool exhausted)
    {"op": "decode", "seq_id": "e1", "num_tokens": 2},
    # Free forked sequence
    {"op": "free", "seq_id": "e1f"},
    # Free original
    {"op": "free", "seq_id": "e1"},
    # Verify non-evicted cached block (HB) survives and is reusable
    {"op": "prefill_cached", "seq_id": "e2", "prompt_length": 4,
     "block_hashes": ["HB"]},
    {"op": "free", "seq_id": "e2"},
]

EXPECTED_5 = {
    "per_token_kv_bytes": 4096,
    "total_blocks_allocated": 6,
    "total_cow_copies": 1,
    "peak_blocks_used": 5,
    "final_blocks_used": 1,
    "wasted_slots_at_peak": 3,
    "prefix_cache_hits": 1,
    "prefix_cache_misses": 2,
    "evictions_performed": 1,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBaseNestedForks:
    """Nested forks, multiple CoW copies, complex ref-count propagation."""

    @pytest.fixture(autouse=True)
    def _run(self):
        write_config(DEFAULT_CONFIG)
        write_workload_db(WORKLOAD_1)
        self.results = run_allocator()

    def test_per_token_kv_bytes(self):
        assert self.results["per_token_kv_bytes"] == EXPECTED_1["per_token_kv_bytes"]

    def test_total_blocks_allocated(self):
        assert self.results["total_blocks_allocated"] == EXPECTED_1["total_blocks_allocated"]

    def test_total_cow_copies(self):
        assert self.results["total_cow_copies"] == EXPECTED_1["total_cow_copies"]

    def test_peak_blocks_used(self):
        assert self.results["peak_blocks_used"] == EXPECTED_1["peak_blocks_used"]

    def test_final_blocks_used(self):
        assert self.results["final_blocks_used"] == EXPECTED_1["final_blocks_used"]

    def test_wasted_slots_at_peak(self):
        assert self.results["wasted_slots_at_peak"] == EXPECTED_1["wasted_slots_at_peak"]


class TestFullBlockFork:
    """Full shared blocks must NOT trigger CoW -- just allocate new."""

    @pytest.fixture(autouse=True)
    def _run(self):
        write_config(DEFAULT_CONFIG)
        write_workload_db(WORKLOAD_2)
        self.results = run_allocator()

    def test_total_blocks_allocated(self):
        assert self.results["total_blocks_allocated"] == EXPECTED_2["total_blocks_allocated"]

    def test_total_cow_copies(self):
        assert self.results["total_cow_copies"] == EXPECTED_2["total_cow_copies"]

    def test_peak_blocks_used(self):
        assert self.results["peak_blocks_used"] == EXPECTED_2["peak_blocks_used"]

    def test_final_blocks_used(self):
        assert self.results["final_blocks_used"] == EXPECTED_2["final_blocks_used"]

    def test_wasted_slots_at_peak(self):
        assert self.results["wasted_slots_at_peak"] == EXPECTED_2["wasted_slots_at_peak"]


class TestPrefixCacheWithDecode:
    """Prefix caching: two requests share prompt blocks via hash dedup."""

    @pytest.fixture(autouse=True)
    def _run(self):
        write_config(DEFAULT_CONFIG)
        write_workload_db(WORKLOAD_3)
        self.results = run_allocator()

    def test_total_blocks_allocated(self):
        assert self.results["total_blocks_allocated"] == EXPECTED_3["total_blocks_allocated"]

    def test_prefix_cache_hits(self):
        assert self.results["prefix_cache_hits"] == EXPECTED_3["prefix_cache_hits"]

    def test_prefix_cache_misses(self):
        assert self.results["prefix_cache_misses"] == EXPECTED_3["prefix_cache_misses"]

    def test_peak_blocks_used(self):
        assert self.results["peak_blocks_used"] == EXPECTED_3["peak_blocks_used"]

    def test_final_blocks_used(self):
        assert self.results["final_blocks_used"] == EXPECTED_3["final_blocks_used"]

    def test_wasted_slots_at_peak(self):
        assert self.results["wasted_slots_at_peak"] == EXPECTED_3["wasted_slots_at_peak"]

    def test_total_cow_copies(self):
        assert self.results["total_cow_copies"] == EXPECTED_3["total_cow_copies"]


class TestPrefixCachePersistence:
    """Cached blocks at ref=0 survive free and are reused by later requests."""

    @pytest.fixture(autouse=True)
    def _run(self):
        write_config(DEFAULT_CONFIG)
        write_workload_db(WORKLOAD_4)
        self.results = run_allocator()

    def test_total_blocks_allocated(self):
        assert self.results["total_blocks_allocated"] == EXPECTED_4["total_blocks_allocated"]

    def test_prefix_cache_hits(self):
        assert self.results["prefix_cache_hits"] == EXPECTED_4["prefix_cache_hits"]

    def test_prefix_cache_misses(self):
        assert self.results["prefix_cache_misses"] == EXPECTED_4["prefix_cache_misses"]

    def test_peak_blocks_used(self):
        assert self.results["peak_blocks_used"] == EXPECTED_4["peak_blocks_used"]

    def test_final_blocks_used(self):
        assert self.results["final_blocks_used"] == EXPECTED_4["final_blocks_used"]

    def test_wasted_slots_at_peak(self):
        assert self.results["wasted_slots_at_peak"] == EXPECTED_4["wasted_slots_at_peak"]


class TestEvictionWithCoW:
    """LRU eviction under memory pressure with CoW and prefix caching."""

    @pytest.fixture(autouse=True)
    def _run(self):
        write_config(WORKLOAD_5_CONFIG)
        write_workload_db(WORKLOAD_5)
        self.results = run_allocator()

    def test_total_blocks_allocated(self):
        assert self.results["total_blocks_allocated"] == EXPECTED_5["total_blocks_allocated"]

    def test_total_cow_copies(self):
        assert self.results["total_cow_copies"] == EXPECTED_5["total_cow_copies"]

    def test_peak_blocks_used(self):
        assert self.results["peak_blocks_used"] == EXPECTED_5["peak_blocks_used"]

    def test_final_blocks_used(self):
        assert self.results["final_blocks_used"] == EXPECTED_5["final_blocks_used"]

    def test_wasted_slots_at_peak(self):
        assert self.results["wasted_slots_at_peak"] == EXPECTED_5["wasted_slots_at_peak"]

    def test_prefix_cache_hits(self):
        assert self.results["prefix_cache_hits"] == EXPECTED_5["prefix_cache_hits"]

    def test_prefix_cache_misses(self):
        assert self.results["prefix_cache_misses"] == EXPECTED_5["prefix_cache_misses"]

    def test_evictions_performed(self):
        assert self.results["evictions_performed"] == EXPECTED_5["evictions_performed"]
