"""Tests for paged KV-cache allocator, scheduler, and evaluation pipeline."""

import os
import sys
import json
import csv

sys.path.insert(0, '/app')

import pytest
from kv_types import (
    Block, BlockHash, Request, RequestStatus,
    SchedulerPolicy, ScheduleResult,
)
from kv_cache_manager import KVCacheManager, FreeBlockQueue
from scheduler import Scheduler


# ── FreeBlockQueue ──────────────────────────────────────────────────

class TestFreeBlockQueue:

    def test_basic_fifo(self):
        q = FreeBlockQueue()
        blocks = [Block(block_id=i) for i in range(4)]
        for b in blocks:
            q.append(b)
        assert len(q) == 4
        assert q.popleft().block_id == 0
        assert q.popleft().block_id == 1
        assert len(q) == 2
        assert q.popleft().block_id == 2
        assert q.popleft().block_id == 3
        assert len(q) == 0

    def test_remove_middle(self):
        q = FreeBlockQueue()
        blocks = [Block(block_id=i) for i in range(5)]
        for b in blocks:
            q.append(b)
        q.remove(blocks[2])
        assert len(q) == 4
        ids = [q.popleft().block_id for _ in range(4)]
        assert ids == [0, 1, 3, 4]

    def test_remove_head_and_tail(self):
        q = FreeBlockQueue()
        blocks = [Block(block_id=i) for i in range(3)]
        for b in blocks:
            q.append(b)
        q.remove(blocks[0])  # head
        q.remove(blocks[2])  # tail
        assert len(q) == 1
        assert q.popleft().block_id == 1


# ── KVCacheManager ─────────────────────────────────────────────────

class TestKVCacheManager:

    def test_basic_allocation(self):
        mgr = KVCacheManager(num_blocks=10, block_size=4)
        req = Request("r1", [1, 2, 3, 4, 5, 6, 7, 8])
        assert mgr.num_free_blocks == 10
        assert mgr.allocate_slots(req, 8) is True
        assert mgr.num_free_blocks == 8
        assert mgr.get_num_allocated_blocks("r1") == 2

    def test_allocation_failure_no_side_effects(self):
        mgr = KVCacheManager(num_blocks=2, block_size=4)
        req = Request("r1", list(range(20)))
        assert mgr.allocate_slots(req, 20) is False
        assert mgr.num_free_blocks == 2
        assert mgr.get_num_allocated_blocks("r1") == 0

    def test_free_returns_blocks(self):
        mgr = KVCacheManager(num_blocks=10, block_size=4)
        req = Request("r1", [1, 2, 3, 4, 5, 6, 7, 8])
        mgr.allocate_slots(req, 8)
        mgr.free("r1")
        assert mgr.num_free_blocks == 10
        assert mgr.get_num_allocated_blocks("r1") == 0

    def test_hash_complete_blocks_only(self):
        mgr = KVCacheManager(num_blocks=10, block_size=4)
        req = Request("r1", list(range(10)))
        hashes = mgr.hash_request_tokens(req)
        # 10 tokens / 4 block_size = 2 complete blocks, 2 leftover
        assert len(hashes) == 2

    def test_hash_deterministic_and_chained(self):
        mgr = KVCacheManager(num_blocks=10, block_size=4)
        h1 = mgr.hash_request_tokens(Request("a", [1, 2, 3, 4, 5, 6, 7, 8]))
        h2 = mgr.hash_request_tokens(Request("b", [1, 2, 3, 4, 5, 6, 7, 8]))
        h3 = mgr.hash_request_tokens(Request("c", [1, 2, 3, 4, 9, 10, 11, 12]))
        # Same tokens → same hashes
        assert h1[0].hash_value == h2[0].hash_value
        assert h1[1].hash_value == h2[1].hash_value
        # Same first block, different second → first matches, second differs
        assert h1[0].hash_value == h3[0].hash_value
        assert h1[1].hash_value != h3[1].hash_value

    def test_hash_chaining_position_dependent(self):
        """Identical token blocks at different positions must get different
        hashes when preceded by different prefixes."""
        mgr = KVCacheManager(num_blocks=10, block_size=4)
        # Second block has same tokens [5,6,7,8] but different first block
        h1 = mgr.hash_request_tokens(Request("a", [1, 2, 3, 4, 5, 6, 7, 8]))
        h2 = mgr.hash_request_tokens(Request("b", [9, 10, 11, 12, 5, 6, 7, 8]))
        # First blocks differ (different tokens)
        assert h1[0].hash_value != h2[0].hash_value
        # Second blocks MUST also differ (same tokens, different context)
        assert h1[1].hash_value != h2[1].hash_value

    def test_prefix_cache_basic(self):
        mgr = KVCacheManager(num_blocks=10, block_size=4)
        # First request: allocate, cache, free
        r1 = Request("r1", [1, 2, 3, 4, 5, 6, 7, 8])
        mgr.hash_request_tokens(r1)
        assert mgr.find_longest_cache_hit(r1) == 0
        mgr.allocate_slots(r1, 8)
        mgr.cache_blocks("r1")
        mgr.free("r1")
        assert mgr.num_free_blocks == 10

        # Second request with same prefix + extra tokens
        r2 = Request("r2", [1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        mgr.hash_request_tokens(r2)
        assert mgr.find_longest_cache_hit(r2) == 2

        r2.num_computed_tokens = 8  # cached portion
        assert mgr.allocate_slots(r2, 2, num_computed_blocks=2) is True
        # 2 reused + 1 new = 3 total
        assert mgr.get_num_allocated_blocks("r2") == 3
        assert mgr.num_free_blocks == 7  # 10 - 2 reused - 1 new

    def test_prefix_cache_ref_counting(self):
        mgr = KVCacheManager(num_blocks=10, block_size=4)
        r1 = Request("r1", [1, 2, 3, 4, 5, 6, 7, 8])
        mgr.hash_request_tokens(r1)
        mgr.allocate_slots(r1, 8)
        mgr.cache_blocks("r1")
        shared = list(mgr.req_to_blocks["r1"])

        # r2 shares same blocks while r1 is alive
        r2 = Request("r2", [1, 2, 3, 4, 5, 6, 7, 8])
        mgr.hash_request_tokens(r2)
        r2.num_computed_tokens = 8
        mgr.allocate_slots(r2, 0, num_computed_blocks=2)
        assert shared[0].ref_count == 2
        assert shared[1].ref_count == 2

        # Free r1 → ref drops to 1, blocks stay allocated
        mgr.free("r1")
        assert shared[0].ref_count == 1
        assert mgr.num_free_blocks == 8  # 10 - 2 shared (still held by r2)

        # Free r2 → ref drops to 0, blocks return to free queue
        mgr.free("r2")
        assert shared[0].ref_count == 0
        assert mgr.num_free_blocks == 10

    def test_cache_invalidation_on_recycle(self):
        mgr = KVCacheManager(num_blocks=3, block_size=4)
        r1 = Request("r1", [1, 2, 3, 4, 5, 6, 7, 8])
        mgr.hash_request_tokens(r1)
        mgr.allocate_slots(r1, 8)
        mgr.cache_blocks("r1")
        mgr.free("r1")

        # Allocate different data, recycling r1's blocks
        r2 = Request("r2", [20, 21, 22, 23, 24, 25, 26, 27])
        mgr.allocate_slots(r2, 8)

        # Original hashes should now be invalidated
        r3 = Request("r3", [1, 2, 3, 4, 5, 6, 7, 8])
        mgr.hash_request_tokens(r3)
        assert mgr.find_longest_cache_hit(r3) == 0

    def test_incremental_decode_allocation(self):
        mgr = KVCacheManager(num_blocks=10, block_size=4)
        req = Request("r1", [1, 2, 3, 4])

        # Prefill: 4 tokens = 1 block
        mgr.allocate_slots(req, 4)
        req.num_computed_tokens = 4
        assert mgr.get_num_allocated_blocks("r1") == 1

        # Decode token 5: need 2nd block
        mgr.allocate_slots(req, 1)
        req.num_computed_tokens = 5
        assert mgr.get_num_allocated_blocks("r1") == 2

        # Tokens 6-8: still fit in 2 blocks
        for _ in range(3):
            mgr.allocate_slots(req, 1)
            req.num_computed_tokens += 1
        assert req.num_computed_tokens == 8
        assert mgr.get_num_allocated_blocks("r1") == 2

        # Token 9: triggers 3rd block
        mgr.allocate_slots(req, 1)
        req.num_computed_tokens = 9
        assert mgr.get_num_allocated_blocks("r1") == 3


# ── Scheduler ───────────────────────────────────────────────────────

class TestScheduler:

    def test_fcfs_order(self):
        mgr = KVCacheManager(num_blocks=20, block_size=4)
        sched = Scheduler(mgr, SchedulerPolicy.FCFS, token_budget=100)
        for rid, toks in [("r1", [1,2,3,4]), ("r2", [5,6,7,8]), ("r3", [9,10,11,12])]:
            sched.add_request(Request(rid, toks))
        result = sched.schedule()
        assert [r[0] for r in result.prefill_requests] == ["r1", "r2", "r3"]

    def test_priority_order(self):
        mgr = KVCacheManager(num_blocks=20, block_size=4)
        sched = Scheduler(mgr, SchedulerPolicy.PRIORITY, token_budget=100)
        sched.add_request(Request("r1", [1,2,3,4], priority=1.0))
        sched.add_request(Request("r2", [5,6,7,8], priority=3.0))
        sched.add_request(Request("r3", [9,10,11,12], priority=2.0))
        result = sched.schedule()
        assert [r[0] for r in result.prefill_requests] == ["r2", "r3", "r1"]

    def test_decode_before_prefill(self):
        mgr = KVCacheManager(num_blocks=20, block_size=4)
        sched = Scheduler(mgr, SchedulerPolicy.FCFS, token_budget=100)
        sched.add_request(Request("r1", [1,2,3,4]))
        sched.schedule()  # prefill r1
        sched.update_after_step("r1", 100)  # decode token

        sched.add_request(Request("r2", [5,6,7,8]))
        result = sched.schedule()
        assert len(result.decode_requests) == 1
        assert result.decode_requests[0][0] == "r1"
        assert len(result.prefill_requests) == 1
        assert result.prefill_requests[0][0] == "r2"

    def test_token_budget(self):
        mgr = KVCacheManager(num_blocks=20, block_size=4)
        sched = Scheduler(mgr, SchedulerPolicy.FCFS, token_budget=6)
        sched.add_request(Request("r1", [1,2,3,4]))   # 4 tokens
        sched.add_request(Request("r2", [5,6,7,8]))   # 4 tokens
        result = sched.schedule()
        assert len(result.prefill_requests) == 2
        assert result.prefill_requests[0] == ("r1", 4, 0)
        assert result.prefill_requests[1] == ("r2", 2, 0)  # only 2 budget left
        assert result.total_tokens == 6

    def test_preemption_priority(self):
        mgr = KVCacheManager(num_blocks=4, block_size=4)
        sched = Scheduler(mgr, SchedulerPolicy.PRIORITY, token_budget=100)
        sched.add_request(Request("r1", [1,2,3,4], priority=1.0))
        sched.add_request(Request("r2", [5,6,7,8], priority=10.0))
        sched.add_request(Request("r3", [9,10,11,12], priority=5.0))
        sched.schedule()  # all prefilled; 3 blocks used, 1 free

        sched.update_after_step("r1", 101)
        sched.update_after_step("r2", 102)
        sched.update_after_step("r3", 103)

        # Each needs 1 more block for decode (5 tokens -> 2 blocks).
        # r2 (pri=10) gets the 1 free block.
        # r3 (pri=5) needs a block → preempt r1 (pri=1).
        # r1 gets re-queued as WAITING.
        result = sched.schedule()
        decode_ids = [r[0] for r in result.decode_requests]
        assert "r2" in decode_ids
        assert "r3" in decode_ids
        assert "r1" in result.preempted_requests
        assert sched.num_running == 2
        assert sched.num_waiting == 1

    def test_chunked_prefill(self):
        mgr = KVCacheManager(num_blocks=20, block_size=4)
        sched = Scheduler(mgr, SchedulerPolicy.FCFS, token_budget=100, chunk_size=8)
        sched.add_request(Request("r1", list(range(20))))

        # Step 1: first 8 tokens
        result = sched.schedule()
        assert result.prefill_requests[0][1] == 8
        assert sched.num_running == 1
        assert sched.num_waiting == 0

        # Step 2: next 8 tokens
        result = sched.schedule()
        assert result.prefill_requests[0][1] == 8

        # Step 3: remaining 4 tokens
        result = sched.schedule()
        assert result.prefill_requests[0][1] == 4

        # Step 4: all prompt done → decode
        result = sched.schedule()
        assert len(result.decode_requests) == 1
        assert result.decode_requests[0][0] == "r1"

    def test_finish_request(self):
        mgr = KVCacheManager(num_blocks=10, block_size=4)
        sched = Scheduler(mgr, SchedulerPolicy.FCFS, token_budget=100)
        sched.add_request(Request("r1", [1,2,3,4]))
        sched.schedule()
        assert sched.num_running == 1
        assert mgr.num_free_blocks == 9
        sched.finish_request("r1")
        assert sched.num_running == 0
        assert mgr.num_free_blocks == 10


# ── Workload Trace Analysis ────────────────────────────────────────

class TestWorkloadAnalysis:

    def test_analysis_results(self):
        path = '/app/analysis.json'
        assert os.path.exists(path), "analysis.json not found at /app/analysis.json"
        with open(path) as f:
            analysis = json.load(f)

        assert analysis['total_preemptions'] == 2, \
            f"total_preemptions: expected 2, got {analysis['total_preemptions']}"
        assert analysis['peak_active_requests'] == 4, \
            f"peak_active_requests: expected 4, got {analysis['peak_active_requests']}"
        assert abs(analysis['cache_hit_ratio'] - 0.1625) < 0.001, \
            f"cache_hit_ratio: expected ~0.1625, got {analysis['cache_hit_ratio']}"
        assert analysis['total_decode_tokens'] == 38, \
            f"total_decode_tokens: expected 38, got {analysis['total_decode_tokens']}"


# ── Per-Request Statistics CSV ─────────────────────────────────────

class TestRequestStatsCSV:

    EXPECTED = {
        'r001': (256, 3, 0, 16),
        'r002': (128, 6, 4, 4),
        'r003': (512, 8, 0, 32),
        'r004': (128, 6, 0, 8),
        'r005': (384, 9, 8, 16),
        'r006': (192, 4, 2, 10),
        'r007': (320, 2, 6, 14),
    }

    def test_csv_exists(self):
        assert os.path.exists('/app/request_stats.csv'), \
            "request_stats.csv not found at /app/request_stats.csv"

    def test_csv_correct_data(self):
        with open('/app/request_stats.csv') as f:
            reader = csv.DictReader(f)
            rows = {}
            for row in reader:
                rid = row['request_id'].strip()
                rows[rid] = row

        assert len(rows) == 7, f"Expected 7 rows, got {len(rows)}"

        for rid, (pt, dt, cb, nb) in self.EXPECTED.items():
            assert rid in rows, f"Missing request {rid} in CSV"
            r = rows[rid]
            assert int(r['total_prefill_tokens']) == pt, \
                f"{rid} total_prefill_tokens: expected {pt}, got {r['total_prefill_tokens']}"
            assert int(r['total_decode_tokens']) == dt, \
                f"{rid} total_decode_tokens: expected {dt}, got {r['total_decode_tokens']}"
            assert int(r['total_cached_blocks']) == cb, \
                f"{rid} total_cached_blocks: expected {cb}, got {r['total_cached_blocks']}"
            assert int(r['total_new_blocks']) == nb, \
                f"{rid} total_new_blocks: expected {nb}, got {r['total_new_blocks']}"


# ── SQLite Analysis Database ───────────────────────────────────────

class TestAnalysisDatabase:

    def test_db_exists(self):
        assert os.path.exists('/app/analysis.db'), \
            "analysis.db not found at /app/analysis.db"

    def test_db_structure_and_data(self):
        import sqlite3 as sql
        conn = sql.connect('/app/analysis.db')
        cur = conn.cursor()

        # Table must exist
        cur.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='request_stats'")
        assert cur.fetchone() is not None, \
            "Table 'request_stats' does not exist in analysis.db"

        # Must have 7 rows
        cur.execute("SELECT COUNT(*) FROM request_stats")
        assert cur.fetchone()[0] == 7, "Expected 7 rows in request_stats"

        # Total decode tokens must sum to 38
        cur.execute(
            "SELECT SUM(CAST(total_decode_tokens AS INTEGER)) "
            "FROM request_stats")
        total = cur.fetchone()[0]
        assert int(total) == 38, \
            f"SUM(total_decode_tokens): expected 38, got {total}"

        conn.close()


# ── Evaluation Results ─────────────────────────────────────────────

class TestEvaluationResults:

    def test_evaluation_exists(self):
        assert os.path.exists('/app/evaluation.json'), \
            "evaluation.json not found at /app/evaluation.json"

    def test_evaluation_values(self):
        with open('/app/evaluation.json') as f:
            data = json.load(f)

        assert data['highest_cache_efficiency_request'] == 'r002', \
            f"highest_cache_efficiency_request: expected 'r002', " \
            f"got '{data['highest_cache_efficiency_request']}'"

        assert abs(data['avg_decode_tokens'] - 5.43) < 0.01, \
            f"avg_decode_tokens: expected ~5.43, " \
            f"got {data['avg_decode_tokens']}"

        assert data['total_blocks_allocated'] == 120, \
            f"total_blocks_allocated: expected 120, " \
            f"got {data['total_blocks_allocated']}"

        assert abs(data['fairness_index'] - 0.8386) < 0.001, \
            f"fairness_index: expected ~0.8386, " \
            f"got {data['fairness_index']}"
