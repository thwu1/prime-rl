
import sys
import math

import pytest

sys.path.insert(0, "/app")
from block_manager_interface import BlockManagerConfig, PreemptionMode
from block_manager import BlockManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_config(**overrides):
    defaults = dict(
        num_gpu_blocks=16,
        num_cpu_blocks=8,
        block_size=4,
        enable_prefix_caching=False,
        preemption_mode=PreemptionMode.SWAP,
    )
    defaults.update(overrides)
    return BlockManagerConfig(**defaults)


# ===================================================================
# Basic Allocation and Free
# ===================================================================

class TestBasicAllocation:

    def setup_method(self):
        self.bm = BlockManager(_default_config())

    def test_allocate_single_block(self):
        assert self.bm.allocate(1, [10, 20, 30])
        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 1
        assert snap.gpu_blocks_free == 15
        assert snap.gpu_blocks_cached == 0
        assert snap.num_active_sequences == 1

    def test_allocate_multiple_blocks(self):
        assert self.bm.allocate(1, [10, 20, 30, 40, 50])
        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 2  # ceil(5/4)
        assert snap.gpu_blocks_free == 14

    def test_allocate_exact_block_boundary(self):
        assert self.bm.allocate(1, [10, 20, 30, 40])
        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 1
        assert snap.gpu_blocks_free == 15

    def test_free_releases_blocks(self):
        self.bm.allocate(1, [10, 20, 30])
        self.bm.allocate(2, [40, 50, 60, 70, 80])
        self.bm.free(1)
        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 2
        assert snap.gpu_blocks_free == 14
        assert snap.num_active_sequences == 1

        self.bm.free(2)
        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 0
        assert snap.gpu_blocks_free == 16
        assert snap.num_active_sequences == 0

    def test_allocate_fails_when_full(self):
        bm = BlockManager(_default_config(num_gpu_blocks=2))
        assert bm.allocate(1, [1, 2, 3, 4, 5, 6, 7, 8])  # 2 blocks
        assert not bm.allocate(2, [9, 10, 11, 12])  # needs 1, 0 free

    def test_duplicate_seq_id_fails(self):
        assert self.bm.allocate(1, [10, 20, 30])
        assert not self.bm.allocate(1, [40, 50, 60])


# ===================================================================
# Append Tokens
# ===================================================================

class TestAppendTokens:

    def setup_method(self):
        self.bm = BlockManager(_default_config())

    def test_append_within_block(self):
        self.bm.allocate(1, [10, 20, 30])
        assert self.bm.append_tokens(1, [40])
        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 1
        s = self.bm.get_sequence_status(1)
        assert s.num_tokens == 4

    def test_append_crosses_boundary(self):
        self.bm.allocate(1, [10, 20, 30])
        assert self.bm.append_tokens(1, [40, 50])
        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 2
        s = self.bm.get_sequence_status(1)
        assert s.num_tokens == 5
        assert s.num_logical_blocks == 2

    def test_append_multiple_new_blocks(self):
        self.bm.allocate(1, [10, 20, 30])  # 1 block, 3/4
        assert self.bm.append_tokens(1, [40, 50, 60, 70, 80, 90, 100])
        # total 10 tokens => ceil(10/4) = 3 blocks
        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 3
        s = self.bm.get_sequence_status(1)
        assert s.num_tokens == 10
        assert s.num_logical_blocks == 3

    def test_append_fails_when_no_blocks(self):
        bm = BlockManager(_default_config(num_gpu_blocks=1))
        bm.allocate(1, [10, 20, 30, 40])  # 1 full block
        assert not bm.append_tokens(1, [50])  # needs new block, 0 free
        # sequence unchanged
        s = bm.get_sequence_status(1)
        assert s.num_tokens == 4
        assert s.num_logical_blocks == 1


# ===================================================================
# Fork and Copy-on-Write
# ===================================================================

class TestForkAndCoW:

    def setup_method(self):
        self.bm = BlockManager(_default_config())

    def test_fork_shares_blocks(self):
        self.bm.allocate(1, [10, 20, 30, 40, 50, 60])  # 2 blocks
        assert self.bm.fork(1, 2)
        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 2  # shared
        assert snap.num_active_sequences == 2

        s1 = self.bm.get_sequence_status(1)
        s2 = self.bm.get_sequence_status(2)
        assert s1.block_table == s2.block_table
        assert s2.num_tokens == 6

    def test_cow_on_shared_partial_block(self):
        self.bm.allocate(1, [10, 20, 30, 40, 50, 60])  # last block partial
        self.bm.fork(1, 2)
        assert self.bm.append_tokens(2, [70])

        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 3  # 2 original + 1 CoW copy
        assert snap.cow_copies == 1

        s1 = self.bm.get_sequence_status(1)
        s2 = self.bm.get_sequence_status(2)
        assert s1.block_table[0] == s2.block_table[0]  # first block shared
        assert s1.block_table[-1] != s2.block_table[-1]  # last block diverged

    def test_no_cow_when_last_block_full(self):
        self.bm.allocate(1, [10, 20, 30, 40, 50, 60, 70, 80])  # 2 full
        self.bm.fork(1, 2)
        assert self.bm.append_tokens(2, [90])

        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 3  # 2 shared + 1 new (no CoW)
        assert snap.cow_copies == 0

        s2 = self.bm.get_sequence_status(2)
        assert s2.num_tokens == 9
        assert s2.num_logical_blocks == 3

    def test_free_forked_sequence_decrements_refcount(self):
        self.bm.allocate(1, [10, 20, 30, 40, 50, 60])
        self.bm.fork(1, 2)
        self.bm.free(2)

        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 2  # still used by seq 1
        assert snap.num_active_sequences == 1

        self.bm.free(1)
        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 0

    def test_cow_then_free_parent(self):
        self.bm.allocate(1, [10, 20, 30, 40, 50, 60])  # 2 blocks
        self.bm.fork(1, 2)
        self.bm.append_tokens(2, [70])  # CoW on last block
        # blocks: first(ref=2), parent_last(ref=1), cow_block(ref=1)

        self.bm.free(1)
        snap = self.bm.get_memory_snapshot()
        # first block ref 2->1, parent_last ref 1->0 freed
        assert snap.gpu_blocks_used == 2
        assert snap.gpu_blocks_free == 14

    def test_multiple_forks_chain(self):
        """Fork A->B, B->C. Verify cascading CoW."""
        self.bm.allocate(1, [10, 20, 30, 40, 50, 60])
        self.bm.fork(1, 2)
        self.bm.fork(2, 3)

        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 2
        assert snap.num_active_sequences == 3

        # CoW on seq 3's partial last block (ref=3)
        self.bm.append_tokens(3, [70])
        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 3
        assert snap.cow_copies == 1

        s1 = self.bm.get_sequence_status(1)
        s2 = self.bm.get_sequence_status(2)
        s3 = self.bm.get_sequence_status(3)
        assert s1.block_table[0] == s2.block_table[0] == s3.block_table[0]
        assert s1.block_table[1] == s2.block_table[1]
        assert s3.block_table[1] != s1.block_table[1]

        # CoW on seq 2's partial last block (now ref=2, shared with seq 1)
        self.bm.append_tokens(2, [80])
        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 4
        assert snap.cow_copies == 2

        # Seq 1's last block now ref=1: no CoW
        self.bm.append_tokens(1, [90])
        snap = self.bm.get_memory_snapshot()
        assert snap.cow_copies == 2  # unchanged


# ===================================================================
# Swap Out / Swap In
# ===================================================================

class TestSwap:

    def test_swap_out(self):
        bm = BlockManager(_default_config(num_gpu_blocks=4, num_cpu_blocks=4))
        bm.allocate(1, [1, 2, 3, 4, 5, 6, 7, 8])  # 2 blocks
        bm.allocate(2, [10, 11, 12, 13])            # 1 block

        assert bm.swap_out(2)
        snap = bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 2
        assert snap.gpu_blocks_free == 2
        assert snap.cpu_blocks_used == 1
        assert snap.num_active_sequences == 1
        assert snap.num_swapped_sequences == 1
        assert bm.get_sequence_status(2).is_swapped

    def test_swap_in(self):
        bm = BlockManager(_default_config(num_gpu_blocks=4, num_cpu_blocks=4))
        bm.allocate(1, [1, 2, 3, 4, 5, 6, 7, 8])  # 2 blocks
        bm.allocate(2, [10, 11, 12, 13])            # 1 block
        bm.swap_out(2)
        bm.free(1)

        assert bm.swap_in(2)
        snap = bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 1
        assert snap.gpu_blocks_free == 3
        assert snap.cpu_blocks_used == 0
        assert snap.num_active_sequences == 1
        assert snap.num_swapped_sequences == 0
        assert not bm.get_sequence_status(2).is_swapped

    def test_swap_in_fails_no_gpu_space(self):
        bm = BlockManager(_default_config(num_gpu_blocks=4, num_cpu_blocks=4))
        bm.allocate(1, [1, 2, 3, 4, 5, 6, 7, 8])  # 2
        bm.allocate(2, [10, 11, 12, 13])            # 1
        bm.swap_out(2)
        bm.allocate(3, [20, 21, 22, 23])            # 1
        bm.allocate(4, [30, 31, 32, 33])            # 1
        # GPU: 4/4 used
        assert not bm.swap_in(2)

    def test_swap_out_fails_no_cpu_space(self):
        bm = BlockManager(_default_config(num_gpu_blocks=8, num_cpu_blocks=1))
        bm.allocate(1, [1, 2, 3, 4, 5, 6, 7, 8])  # 2 GPU blocks
        assert not bm.swap_out(1)  # needs 2 CPU, only 1


# ===================================================================
# Prefix Caching
# ===================================================================

class TestPrefixCaching:

    def setup_method(self):
        self.bm = BlockManager(_default_config(enable_prefix_caching=True))

    def test_cache_hit_on_reallocation(self):
        self.bm.allocate(1, [10, 20, 30, 40, 50, 60, 70, 80])  # 2 full
        self.bm.free(1)

        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_cached == 2
        assert snap.gpu_blocks_used == 0

        self.bm.allocate(2, [10, 20, 30, 40, 90, 91, 92, 93])
        snap = self.bm.get_memory_snapshot()
        assert snap.prefix_cache_hits == 1   # first block reused
        assert snap.prefix_cache_misses == 3  # 2 from alloc(1) + 1 from alloc(2)
        assert snap.gpu_blocks_used == 2
        assert snap.gpu_blocks_cached == 1   # second original block still cached

    def test_partial_block_not_cached(self):
        self.bm.allocate(1, [10, 20, 30])  # 1 partial block
        self.bm.free(1)
        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_cached == 0
        assert snap.gpu_blocks_free == 16

    def test_cache_eviction_when_full(self):
        bm = BlockManager(_default_config(
            num_gpu_blocks=4, enable_prefix_caching=True))
        bm.allocate(1, [1, 2, 3, 4, 5, 6, 7, 8])      # 2 blocks
        bm.allocate(2, [10, 11, 12, 13, 14, 15, 16, 17])  # 2 blocks
        bm.free(1)
        bm.free(2)

        snap = bm.get_memory_snapshot()
        assert snap.gpu_blocks_cached == 4
        assert snap.gpu_blocks_free == 0

        assert bm.allocate(3, [20, 21, 22, 23])  # needs 1 block, must evict
        snap = bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 1
        assert snap.gpu_blocks_cached == 3  # evicted 1

    def test_prefix_sharing_between_active_sequences(self):
        """Two active sequences share a full prefix block via hash table."""
        self.bm.allocate(1, [10, 20, 30, 40, 50, 60])
        # block_a=[10,20,30,40] (full, in hash), block_b=[50,60] (partial)
        self.bm.allocate(2, [10, 20, 30, 40, 70, 80])
        # block_a reused (hit), block_c=[70,80] (new)

        snap = self.bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 3
        assert snap.prefix_cache_hits == 1
        assert snap.prefix_cache_misses == 1  # only block_a miss on first alloc

        s1 = self.bm.get_sequence_status(1)
        s2 = self.bm.get_sequence_status(2)
        assert s1.block_table[0] == s2.block_table[0]  # shared
        assert s1.block_table[1] != s2.block_table[1]  # different


# ===================================================================
# Preemption Victim Selection
# ===================================================================

class TestPreemptionVictim:

    def setup_method(self):
        self.bm = BlockManager(_default_config())

    def test_lifo_victim_selection(self):
        self.bm.allocate(1, [10, 20])
        self.bm.allocate(2, [30, 40])
        self.bm.allocate(3, [50, 60])
        assert self.bm.select_preemption_victim() == 3

    def test_victim_excludes_swapped(self):
        self.bm.allocate(1, [10, 20])
        self.bm.allocate(2, [30, 40])
        self.bm.allocate(3, [50, 60])
        self.bm.swap_out(3)
        assert self.bm.select_preemption_victim() == 2

    def test_no_victim_when_empty(self):
        assert self.bm.select_preemption_victim() is None


# ===================================================================
# can_allocate
# ===================================================================

class TestCanAllocate:

    def test_can_allocate_when_space(self):
        bm = BlockManager(_default_config(num_gpu_blocks=4))
        assert bm.can_allocate(8)  # needs 2 blocks, 4 free

    def test_cannot_allocate_when_full(self):
        bm = BlockManager(_default_config(num_gpu_blocks=4))
        bm.allocate(1, [1, 2, 3, 4, 5, 6, 7, 8])      # 2
        bm.allocate(2, [9, 10, 11, 12, 13, 14, 15, 16])  # 2
        assert not bm.can_allocate(1)


# ===================================================================
# Complex Mixed Scenarios
# ===================================================================

class TestComplexScenarios:

    def test_fork_swap_free_cycle(self):
        bm = BlockManager(_default_config(num_gpu_blocks=6, num_cpu_blocks=4))
        bm.allocate(1, [1, 2, 3, 4, 5, 6])  # 2 blocks
        bm.fork(1, 2)

        snap = bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 2

        bm.append_tokens(2, [7])  # CoW
        snap = bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 3
        assert snap.cow_copies == 1

        bm.allocate(3, [10, 11, 12, 13, 14, 15, 16, 17])  # 2 blocks
        snap = bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 5

        assert not bm.can_allocate(5)  # needs 2, only 1 free

        victim = bm.select_preemption_victim()
        assert victim == 3

        assert bm.swap_out(3)
        snap = bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 3
        assert snap.gpu_blocks_free == 3
        assert snap.cpu_blocks_used == 2
        assert snap.num_swapped_sequences == 1

        assert bm.allocate(4, [20, 21, 22, 23, 24])  # 2 blocks
        snap = bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 5

        bm.free(1)  # first block ref 2->1, parent_last ref 1->0 freed
        snap = bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 4
        assert snap.gpu_blocks_free == 2

    def test_prefix_cache_with_cow_interaction(self):
        bm = BlockManager(_default_config(enable_prefix_caching=True))

        bm.allocate(1, [10, 20, 30, 40, 50, 60, 70, 80])  # 2 full blocks
        bm.free(1)

        snap = bm.get_memory_snapshot()
        assert snap.gpu_blocks_cached == 2

        # Reuse cached blocks + partial new block
        bm.allocate(2, [10, 20, 30, 40, 50, 60, 70, 80, 90])
        snap = bm.get_memory_snapshot()
        assert snap.prefix_cache_hits == 2
        assert snap.gpu_blocks_used == 3
        assert snap.gpu_blocks_cached == 0

        bm.fork(2, 3)
        snap = bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 3  # shared

        # CoW on last partial block of forked seq
        bm.append_tokens(3, [100])
        snap = bm.get_memory_snapshot()
        assert snap.cow_copies == 1
        assert snap.gpu_blocks_used == 4

    def test_memory_reuse_after_mixed_frees(self):
        """Freed blocks are properly reused for new allocations."""
        bm = BlockManager(_default_config(num_gpu_blocks=8))
        bm.allocate(1, [1] * 4)    # 1 block
        bm.allocate(2, [2] * 8)    # 2 blocks
        bm.allocate(3, [3] * 12)   # 3 blocks
        bm.allocate(4, [4] * 8)    # 2 blocks  => total 8

        snap = bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 8
        assert snap.gpu_blocks_free == 0

        bm.free(2)  # frees 2
        bm.free(3)  # frees 3

        snap = bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 3
        assert snap.gpu_blocks_free == 5

        assert bm.allocate(5, [5] * 16)  # needs 4 blocks
        snap = bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 7
        assert snap.gpu_blocks_free == 1

        assert bm.allocate(6, [6] * 4)  # needs 1 block
        snap = bm.get_memory_snapshot()
        assert snap.gpu_blocks_used == 8
        assert snap.gpu_blocks_free == 0

        assert not bm.can_allocate(1)
