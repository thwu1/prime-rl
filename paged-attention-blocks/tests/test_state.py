
"""
Tests for PagedAttention KV Cache Block Manager (hybrid C/Python).

Covers: library build, memory safety (valgrind), ctypes bindings,
block allocation, reference counting, copy-on-write, prefix caching,
swap out/in, preemption victim selection, and utilization statistics.
"""

import os
import re
import subprocess
import pytest
import sys


# ---------------------------------------------------------------------------
# Build & memory-safety tests
# ---------------------------------------------------------------------------

class TestBuildAndSafety:

    def test_shared_library_exists(self):
        """libblockpool.so must exist (agent should have run make)."""
        assert os.path.exists("/app/libblockpool.so"), (
            "libblockpool.so not found — run make in /app to build it"
        )

    def test_shared_library_loadable(self):
        """The .so must be loadable via ctypes and expose expected symbols."""
        import ctypes
        lib = ctypes.CDLL("/app/libblockpool.so")
        for fn in ("blockpool_create", "blockpool_destroy",
                    "blockpool_allocate", "blockpool_free",
                    "blockpool_incref", "blockpool_get_refcount",
                    "blockpool_num_free", "blockpool_append_token"):
            assert hasattr(lib, fn), f"missing symbol: {fn}"

    def test_valgrind_no_leaks(self):
        """The C library must be free of memory leaks."""
        test_src = "/tmp/_blockpool_leak_test.c"
        test_bin = "/tmp/_blockpool_leak_test"

        with open(test_src, "w") as f:
            f.write(
                '#include "blockpool.h"\n'
                'int main(void) {\n'
                '    BlockPool *p = blockpool_create(8, 4);\n'
                '    int b0 = blockpool_allocate(p);\n'
                '    int b1 = blockpool_allocate(p);\n'
                '    blockpool_append_token(p, b0, 10);\n'
                '    blockpool_append_token(p, b0, 20);\n'
                '    blockpool_incref(p, b0);\n'
                '    blockpool_free(p, b0);\n'
                '    blockpool_free(p, b0);\n'
                '    blockpool_free(p, b1);\n'
                '    blockpool_destroy(p);\n'
                '    return 0;\n'
                '}\n'
            )

        comp = subprocess.run(
            ["gcc", "-o", test_bin, test_src, "/app/blockpool.c",
             "-I/app", "-Wall"],
            capture_output=True, text=True,
        )
        assert comp.returncode == 0, f"compile failed:\n{comp.stderr}"

        vg = subprocess.run(
            ["valgrind", "--leak-check=full", "--errors-for-leak-kinds=definite",
             "--error-exitcode=42", test_bin],
            capture_output=True, text=True, timeout=30,
        )

        stderr = vg.stderr
        leak_match = re.search(r"definitely lost: ([\d,]+) bytes", stderr)
        if leak_match:
            lost = int(leak_match.group(1).replace(",", ""))
            assert lost == 0, (
                f"valgrind: {lost} bytes definitely lost\n{stderr}"
            )
        if vg.returncode == 42:
            pytest.fail(f"valgrind error exit:\n{stderr}")


# ---------------------------------------------------------------------------
# Import block_manager — all subsequent tests depend on this
# ---------------------------------------------------------------------------

sys.path.insert(0, "/app")
from block_manager import BlockAllocator, BlockManager


# ---------------------------------------------------------------------------
# BlockAllocator tests
# ---------------------------------------------------------------------------

class TestBlockAllocator:

    def test_basic_allocate_free(self):
        alloc = BlockAllocator(num_blocks=4, block_size=4, device="gpu")
        assert alloc.get_num_free() == 4
        b0 = alloc.allocate()
        assert alloc.get_num_free() == 3
        assert alloc.get_ref_count(b0) == 1
        alloc.free(b0)
        assert alloc.get_num_free() == 4
        assert alloc.get_ref_count(b0) == 0

    def test_ref_counting(self):
        alloc = BlockAllocator(num_blocks=4, block_size=4, device="gpu")
        b0 = alloc.allocate()
        alloc.increment_ref(b0)
        assert alloc.get_ref_count(b0) == 2
        alloc.free(b0)
        assert alloc.get_ref_count(b0) == 1
        assert alloc.get_num_free() == 3
        alloc.free(b0)
        assert alloc.get_ref_count(b0) == 0
        assert alloc.get_num_free() == 4

    def test_prefix_cache_cleanup_on_free(self):
        """free() must remove stale hash_to_block entries."""
        alloc = BlockAllocator(num_blocks=4, block_size=4, device="gpu")
        b0 = alloc.allocate()
        alloc.blocks[b0].token_ids = [10, 20, 30, 40]
        alloc.cache_full_block(b0)
        assert len(alloc.hash_to_block) == 1
        alloc.free(b0)
        assert len(alloc.hash_to_block) == 0, (
            "hash_to_block should be empty after freeing a cached block"
        )

    def test_lookup_cache_validates_block(self):
        """lookup_cache must verify the block is still valid."""
        alloc = BlockAllocator(num_blocks=4, block_size=4, device="gpu")
        b0 = alloc.allocate()
        alloc.blocks[b0].token_ids = [10, 20, 30, 40]
        alloc.cache_full_block(b0)
        alloc.free(b0)
        h = alloc.compute_hash([10, 20, 30, 40])
        alloc.hash_to_block[h] = b0
        result = alloc.lookup_cache([10, 20, 30, 40])
        assert result is None, (
            "lookup_cache should return None for a freed/invalid block"
        )

    def test_lookup_cache_rejects_content_mismatch(self):
        """lookup_cache must reject blocks whose content has changed."""
        alloc = BlockAllocator(num_blocks=4, block_size=4, device="gpu")
        b0 = alloc.allocate()
        alloc.blocks[b0].token_ids = [10, 20, 30, 40]
        alloc.cache_full_block(b0)
        h_old = alloc.compute_hash([10, 20, 30, 40])
        alloc.blocks[b0].token_ids = [50, 60, 70, 80]
        result = alloc.lookup_cache([10, 20, 30, 40])
        assert result is None, (
            "lookup_cache should reject block with mismatched content"
        )


# ---------------------------------------------------------------------------
# BlockManager basic tests
# ---------------------------------------------------------------------------

class TestBlockManagerBasic:

    def test_num_blocks_needed_exact_multiples(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=10, num_cpu_blocks=5)
        assert bm._num_blocks_needed(0) == 0
        assert bm._num_blocks_needed(1) == 1
        assert bm._num_blocks_needed(3) == 1
        assert bm._num_blocks_needed(4) == 1
        assert bm._num_blocks_needed(5) == 2
        assert bm._num_blocks_needed(8) == 2
        assert bm._num_blocks_needed(9) == 3
        assert bm._num_blocks_needed(16) == 4

    def test_allocate_exact_block_size(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=4, num_cpu_blocks=0)
        assert bm.allocate_sequence(1, 1, [1, 2, 3, 4]) is True
        assert len(bm.get_block_table(1)) == 1
        assert bm.gpu_allocator.get_num_free() == 3

    def test_allocate_tight_memory(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=2, num_cpu_blocks=0)
        assert bm.allocate_sequence(1, 1, [1, 2, 3, 4]) is True
        assert bm.allocate_sequence(2, 2, [5, 6, 7, 8]) is True

    def test_allocate_and_free(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=10, num_cpu_blocks=5)
        assert bm.allocate_sequence(1, 1, [1, 2, 3, 4, 5]) is True
        assert len(bm.get_block_table(1)) == 2
        assert bm.free_sequence(1) is True
        assert bm.get_block_table(1) == []
        assert bm.gpu_allocator.get_num_free() == 10

    def test_allocate_duplicate_seq_id(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=10, num_cpu_blocks=5)
        assert bm.allocate_sequence(1, 1, [1, 2]) is True
        assert bm.allocate_sequence(1, 1, [3, 4]) is False

    def test_can_allocate(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=2, num_cpu_blocks=0)
        assert bm.can_allocate(4) is True
        assert bm.can_allocate(8) is True
        assert bm.can_allocate(9) is False


# ---------------------------------------------------------------------------
# Append & COW
# ---------------------------------------------------------------------------

class TestAppendAndCOW:

    def test_append_within_block(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=10, num_cpu_blocks=5)
        bm.allocate_sequence(1, 1, [1, 2, 3])
        assert len(bm.get_block_table(1)) == 1
        bm.append_token(1, 4)
        assert len(bm.get_block_table(1)) == 1
        blk = bm.gpu_allocator.blocks[bm.get_block_table(1)[0]]
        assert blk.token_ids == [1, 2, 3, 4]

    def test_append_triggers_new_block(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=10, num_cpu_blocks=5)
        bm.allocate_sequence(1, 1, [1, 2, 3])
        bm.append_token(1, 4)
        bm.append_token(1, 5)
        assert len(bm.get_block_table(1)) == 2

    def test_cow_on_partial_block_after_fork(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=20, num_cpu_blocks=10)
        bm.allocate_sequence(1, 1, [1, 2, 3])
        bm.fork_sequence(1, 2)
        t1 = bm.get_block_table(1)
        t2 = bm.get_block_table(2)
        assert t1[0] == t2[0]
        bm.append_token(2, 99)
        t1 = bm.get_block_table(1)
        t2 = bm.get_block_table(2)
        assert t1[0] != t2[0]
        assert bm.gpu_allocator.blocks[t1[0]].token_ids == [1, 2, 3]
        assert bm.gpu_allocator.blocks[t2[0]].token_ids == [1, 2, 3, 99]

    def test_cow_on_full_block_after_fork(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=20, num_cpu_blocks=10)
        bm.allocate_sequence(1, 1, [1, 2, 3, 4])
        bm.fork_sequence(1, 2)
        bm.append_token(1, 10)
        bm.append_token(2, 20)
        t1 = bm.get_block_table(1)
        t2 = bm.get_block_table(2)
        assert t1[0] == t2[0]
        assert t1[1] != t2[1]
        assert bm.gpu_allocator.blocks[t1[1]].token_ids == [10]
        assert bm.gpu_allocator.blocks[t2[1]].token_ids == [20]

    def test_cow_decrements_ref_count(self):
        """After COW, the original block's ref_count must be decremented."""
        bm = BlockManager(block_size=4, num_gpu_blocks=20, num_cpu_blocks=10)
        bm.allocate_sequence(1, 1, [1, 2, 3])
        bm.fork_sequence(1, 2)
        old_block = bm.get_block_table(1)[0]
        assert bm.gpu_allocator.get_ref_count(old_block) == 2
        bm.append_token(2, 99)
        assert bm.gpu_allocator.get_ref_count(old_block) == 1, (
            "COW must decrement ref_count on the original shared block"
        )

    def test_cow_free_after_diverge(self):
        """After COW and freeing all references, blocks must be reclaimed."""
        bm = BlockManager(block_size=4, num_gpu_blocks=4, num_cpu_blocks=0)
        bm.allocate_sequence(1, 1, [1, 2, 3])
        bm.fork_sequence(1, 2)
        bm.append_token(2, 99)
        bm.free_sequence(1)
        bm.free_sequence(2)
        assert bm.gpu_allocator.get_num_free() == 4, (
            "All blocks must be reclaimed after freeing all sequences"
        )


# ---------------------------------------------------------------------------
# Fork & group membership
# ---------------------------------------------------------------------------

class TestForkGroupMembership:

    def test_fork_adds_child_to_group(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=20, num_cpu_blocks=10)
        bm.allocate_sequence(1, 1, [1, 2, 3, 4])
        bm.fork_sequence(1, 2)
        assert 2 in bm.group_seqs.get(1, set()), (
            "child seq must be added to group_seqs"
        )

    def test_fork_swap_includes_child(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=20, num_cpu_blocks=10)
        bm.allocate_sequence(1, 1, [1, 2, 3, 4])
        bm.fork_sequence(1, 2)
        bm.swap_out(1)
        assert 1 in bm.swapped_block_tables
        assert 2 in bm.swapped_block_tables, (
            "forked child must be swapped out with its group"
        )
        assert 1 not in bm.block_tables
        assert 2 not in bm.block_tables

    def test_fork_free_child_does_not_destroy_group(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=20, num_cpu_blocks=10)
        bm.allocate_sequence(1, 1, [1, 2, 3, 4])
        bm.fork_sequence(1, 2)
        bm.free_sequence(2)
        assert 1 in bm.group_seqs
        assert 1 in bm.group_seqs[1]


# ---------------------------------------------------------------------------
# Swapping
# ---------------------------------------------------------------------------

class TestSwapping:

    def test_swap_out_and_in_roundtrip(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=10, num_cpu_blocks=10)
        bm.allocate_sequence(1, 1, [1, 2, 3, 4, 5])
        orig_tokens = list(bm.seq_tokens[1])
        gpu_to_cpu = bm.swap_out(1)
        assert len(gpu_to_cpu) > 0
        assert 1 not in bm.block_tables
        assert 1 in bm.swapped_block_tables
        cpu_to_gpu = bm.swap_in(1)
        assert len(cpu_to_gpu) > 0
        assert 1 in bm.block_tables
        assert 1 not in bm.swapped_block_tables
        all_tokens = []
        for bid in bm.get_block_table(1):
            all_tokens.extend(bm.gpu_allocator.blocks[bid].token_ids)
        assert all_tokens == orig_tokens

    def test_swap_in_frees_cpu_blocks(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=10, num_cpu_blocks=10)
        bm.allocate_sequence(1, 1, [1, 2, 3, 4, 5])
        initial_cpu_free = bm.cpu_allocator.get_num_free()
        bm.swap_out(1)
        assert bm.cpu_allocator.get_num_free() < initial_cpu_free
        bm.swap_in(1)
        assert bm.cpu_allocator.get_num_free() == initial_cpu_free, (
            "CPU blocks must be freed after swap_in"
        )

    def test_swap_shared_blocks(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=20, num_cpu_blocks=20)
        bm.allocate_sequence(1, 1, [1, 2, 3, 4])
        bm.fork_sequence(1, 2)
        bm.swap_out(1)
        bm.swap_in(1)
        assert 1 in bm.block_tables
        assert 2 in bm.block_tables
        t1_tokens = []
        for bid in bm.get_block_table(1):
            t1_tokens.extend(bm.gpu_allocator.blocks[bid].token_ids)
        assert t1_tokens == [1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Prefix caching
# ---------------------------------------------------------------------------

class TestPrefixCaching:

    def test_prefix_cache_sharing(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=10, num_cpu_blocks=5,
                          enable_prefix_caching=True)
        bm.allocate_sequence(1, 1, [10, 20, 30, 40, 50, 60, 70, 80, 90])
        bm.allocate_sequence(2, 2, [10, 20, 30, 40, 50, 60, 70, 80, 99])
        t1 = bm.get_block_table(1)
        t2 = bm.get_block_table(2)
        assert t1[0] == t2[0]
        assert t1[1] == t2[1]
        assert t1[2] != t2[2]

    def test_prefix_cache_after_free(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=10, num_cpu_blocks=5,
                          enable_prefix_caching=True)
        bm.allocate_sequence(1, 1, [10, 20, 30, 40])
        bm.free_sequence(1)
        bm.allocate_sequence(2, 2, [50, 60, 70, 80])
        bm.allocate_sequence(3, 3, [10, 20, 30, 40])
        t2 = bm.get_block_table(2)
        t3 = bm.get_block_table(3)
        assert t2[0] != t3[0], (
            "seq 3 must not share a block with seq 2 after seq 1 was freed"
        )
        assert bm.gpu_allocator.blocks[t3[0]].token_ids == [10, 20, 30, 40]

    def test_get_num_prefix_cache_hits_basic(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=20, num_cpu_blocks=5,
                          enable_prefix_caching=True)
        bm.allocate_sequence(1, 1, [10, 20, 30, 40, 50, 60, 70, 80, 90])
        assert bm.get_num_prefix_cache_hits(
            [10, 20, 30, 40, 50, 60, 70, 80]) == 2
        assert bm.get_num_prefix_cache_hits(
            [10, 20, 30, 40, 99, 99, 99, 99]) == 1
        assert bm.get_num_prefix_cache_hits([99, 20, 30, 40]) == 0

    def test_get_num_prefix_cache_hits_partial(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=20, num_cpu_blocks=5,
                          enable_prefix_caching=True)
        bm.allocate_sequence(1, 1, [10, 20, 30, 40, 50])
        assert bm.get_num_prefix_cache_hits([10, 20, 30, 40, 50]) == 1

    def test_get_num_prefix_cache_hits_disabled(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=10, num_cpu_blocks=5,
                          enable_prefix_caching=False)
        bm.allocate_sequence(1, 1, [10, 20, 30, 40])
        assert bm.get_num_prefix_cache_hits([10, 20, 30, 40]) == 0


# ---------------------------------------------------------------------------
# Preemption
# ---------------------------------------------------------------------------

class TestPreemption:

    def test_select_victim_lifo(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=40, num_cpu_blocks=10)
        bm.allocate_sequence(1, 10, [1, 2, 3, 4])
        bm.allocate_sequence(2, 20, [5, 6, 7, 8])
        bm.allocate_sequence(3, 30, [9, 10, 11, 12])
        assert bm.select_victim_group() == 30

    def test_select_victim_skips_swapped(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=40, num_cpu_blocks=10)
        bm.allocate_sequence(1, 10, [1, 2, 3, 4])
        bm.allocate_sequence(2, 20, [5, 6, 7, 8])
        bm.allocate_sequence(3, 30, [9, 10, 11, 12])
        bm.swap_out(30)
        assert bm.select_victim_group() == 20

    def test_select_victim_none_when_empty(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=10, num_cpu_blocks=10)
        assert bm.select_victim_group() is None

    def test_select_victim_none_all_swapped(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=10, num_cpu_blocks=10)
        bm.allocate_sequence(1, 10, [1, 2, 3, 4])
        bm.swap_out(10)
        assert bm.select_victim_group() is None


# ---------------------------------------------------------------------------
# Utilization stats
# ---------------------------------------------------------------------------

class TestUtilizationStats:

    def test_utilization_basic(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=10, num_cpu_blocks=5,
                          enable_prefix_caching=True)
        bm.allocate_sequence(1, 1, [1, 2, 3, 4, 5])
        bm.allocate_sequence(2, 2, [6, 7, 8])
        bm.fork_sequence(1, 3)
        stats = bm.get_utilization_stats()
        assert stats["gpu_total_blocks"] == 10
        assert stats["gpu_used_blocks"] == 3
        assert stats["gpu_free_blocks"] == 7
        assert abs(stats["gpu_utilization"] - 0.3) < 0.001
        assert stats["cpu_total_blocks"] == 5
        assert stats["cpu_used_blocks"] == 0
        assert stats["cpu_free_blocks"] == 5
        assert abs(stats["cpu_utilization"] - 0.0) < 0.001
        assert stats["num_active_sequences"] == 3
        assert stats["num_swapped_sequences"] == 0
        assert stats["num_groups"] == 2
        assert stats["total_shared_blocks"] == 2

    def test_utilization_with_swapped(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=10, num_cpu_blocks=5)
        bm.allocate_sequence(1, 1, [1, 2, 3, 4])
        bm.allocate_sequence(2, 2, [5, 6, 7, 8])
        bm.swap_out(2)
        stats = bm.get_utilization_stats()
        assert stats["num_active_sequences"] == 1
        assert stats["num_swapped_sequences"] == 1
        assert stats["cpu_used_blocks"] == 1
        assert stats["cpu_free_blocks"] == 4


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------

class TestIntegration:

    def test_beam_search_workflow(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=30, num_cpu_blocks=10)
        prompt = list(range(1, 9))
        bm.allocate_sequence(1, 1, prompt)
        assert len(bm.get_block_table(1)) == 2
        bm.fork_sequence(1, 2)
        bm.fork_sequence(1, 3)
        t1 = bm.get_block_table(1)
        t2 = bm.get_block_table(2)
        t3 = bm.get_block_table(3)
        assert t1 == t2 == t3
        assert bm.gpu_allocator.get_ref_count(t1[0]) == 3
        assert bm.gpu_allocator.get_ref_count(t1[1]) == 3
        bm.append_token(1, 100)
        bm.append_token(2, 200)
        bm.append_token(3, 300)
        t1 = bm.get_block_table(1)
        t2 = bm.get_block_table(2)
        t3 = bm.get_block_table(3)
        assert t1[0] == t2[0] == t3[0]
        assert t1[1] == t2[1] == t3[1]
        assert len({t1[2], t2[2], t3[2]}) == 3
        assert bm.gpu_allocator.blocks[t1[2]].token_ids == [100]
        assert bm.gpu_allocator.blocks[t2[2]].token_ids == [200]
        assert bm.gpu_allocator.blocks[t3[2]].token_ids == [300]

    def test_preempt_and_resume(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=8, num_cpu_blocks=8)
        bm.allocate_sequence(1, 10, [1, 2, 3, 4])
        bm.allocate_sequence(2, 20, [5, 6, 7, 8])
        bm.allocate_sequence(3, 30, [9, 10, 11, 12])
        victim = bm.select_victim_group()
        assert victim == 30
        bm.swap_out(victim)
        assert 3 not in bm.block_tables
        assert 3 in bm.swapped_block_tables
        bm.free_sequence(2)
        bm.swap_in(30)
        assert 3 in bm.block_tables
        assert 3 not in bm.swapped_block_tables
        all_tokens = []
        for bid in bm.get_block_table(3):
            all_tokens.extend(bm.gpu_allocator.blocks[bid].token_ids)
        assert all_tokens == [9, 10, 11, 12]

    def test_prefix_cache_with_beam_search(self):
        bm = BlockManager(block_size=4, num_gpu_blocks=20, num_cpu_blocks=10,
                          enable_prefix_caching=True)
        shared_prefix = [10, 20, 30, 40, 50, 60, 70, 80]
        bm.allocate_sequence(1, 1, shared_prefix + [91])
        assert bm.get_num_prefix_cache_hits(shared_prefix) == 2
        bm.allocate_sequence(2, 2, shared_prefix + [92])
        t1 = bm.get_block_table(1)
        t2 = bm.get_block_table(2)
        assert t1[0] == t2[0]
        assert t1[1] == t2[1]
        bm.fork_sequence(2, 3)
        bm.append_token(2, 200)
        bm.append_token(3, 300)
        bm.free_sequence(2)
        bm.free_sequence(3)
        assert bm.get_num_prefix_cache_hits(shared_prefix) == 2
