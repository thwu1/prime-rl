"""
PagedAttention KV Cache Block Manager

A block-based KV cache memory manager inspired by the PagedAttention algorithm
for high-throughput LLM serving.  Uses a C shared library (libblockpool.so) for
low-level block pool operations and Python for higher-level logic.

See spec.md for the full specification.
"""

import ctypes
import hashlib
import os
from typing import Optional


# ---------------------------------------------------------------------------
#  CBlockView — proxy that makes a C-backed block look like a Python object
# ---------------------------------------------------------------------------

class CBlockView:
    """Provides PhysicalBlock-compatible attribute access backed by the C pool."""

    def __init__(self, pool_handle, block_id, lib, block_size):
        self._pool = pool_handle
        self._id = block_id
        self._lib = lib
        self._bs = block_size
        self.content_hash: Optional[str] = None
        self.device: str = "gpu"

    @property
    def block_id(self):
        return self._id

    @property
    def ref_count(self):
        return self._lib.blockpool_get_refcount(self._pool, self._id)

    @ref_count.setter
    def ref_count(self, value):
        # C library owns ref counts — use allocator methods instead.
        pass

    @property
    def token_ids(self):
        n = self._lib.blockpool_get_num_tokens(self._pool, self._id)
        return [self._lib.blockpool_get_token(self._pool, self._id, i)
                for i in range(n)]

    @token_ids.setter
    def token_ids(self, toks):
        self._lib.blockpool_clear_tokens(self._pool, self._id)
        for i, t in enumerate(toks):
            self._lib.blockpool_set_token(self._pool, self._id, i, t)
        self._lib.blockpool_set_num_tokens(self._pool, self._id, len(toks))


# ---------------------------------------------------------------------------
#  BlockAllocator — wraps the C pool, adds prefix-cache bookkeeping
# ---------------------------------------------------------------------------

class BlockAllocator:
    """Manages allocation of physical blocks on a single device."""

    def __init__(self, num_blocks: int, block_size: int, device: str):
        self.num_blocks = num_blocks
        self.block_size = block_size
        self.device = device

        lib_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "libblockpool.so")
        self._lib = ctypes.CDLL(lib_path)
        self._setup_bindings()
        self._pool = self._lib.blockpool_create(num_blocks, block_size)

        self.blocks: dict = {}
        for i in range(num_blocks):
            v = CBlockView(self._pool, i, self._lib, block_size)
            v.device = device
            self.blocks[i] = v

        # Prefix cache: content hash -> block_id  (Python-side only)
        self.hash_to_block: dict = {}

    def _setup_bindings(self):
        """Declare ctypes argtypes / restypes for the C library."""
        self._lib.blockpool_create.argtypes = [ctypes.c_int, ctypes.c_int]
        self._lib.blockpool_create.restype = ctypes.c_int

        self._lib.blockpool_destroy.argtypes = [ctypes.c_void_p]
        self._lib.blockpool_destroy.restype = None

        self._lib.blockpool_allocate.argtypes = [ctypes.c_void_p]
        self._lib.blockpool_allocate.restype = ctypes.c_int

        self._lib.blockpool_free.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._lib.blockpool_free.restype = None

        self._lib.blockpool_incref.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._lib.blockpool_incref.restype = None

        self._lib.blockpool_get_refcount.argtypes = [ctypes.c_void_p,
                                                      ctypes.c_int]
        self._lib.blockpool_get_refcount.restype = ctypes.c_int

        self._lib.blockpool_num_free.argtypes = [ctypes.c_void_p]
        self._lib.blockpool_num_free.restype = ctypes.c_int

        self._lib.blockpool_num_blocks.argtypes = [ctypes.c_void_p]
        self._lib.blockpool_num_blocks.restype = ctypes.c_int

        self._lib.blockpool_block_size.argtypes = [ctypes.c_void_p]
        self._lib.blockpool_block_size.restype = ctypes.c_int

        self._lib.blockpool_set_token.argtypes = [ctypes.c_void_p,
                                                   ctypes.c_int,
                                                   ctypes.c_int,
                                                   ctypes.c_int]
        self._lib.blockpool_set_token.restype = None

        self._lib.blockpool_get_token.argtypes = [ctypes.c_void_p,
                                                   ctypes.c_int,
                                                   ctypes.c_int]
        self._lib.blockpool_get_token.restype = ctypes.c_int

        self._lib.blockpool_get_num_tokens.argtypes = [ctypes.c_void_p,
                                                        ctypes.c_int]
        self._lib.blockpool_get_num_tokens.restype = ctypes.c_int

        self._lib.blockpool_set_num_tokens.argtypes = [ctypes.c_void_p,
                                                        ctypes.c_int,
                                                        ctypes.c_int]
        self._lib.blockpool_set_num_tokens.restype = None

        self._lib.blockpool_clear_tokens.argtypes = [ctypes.c_void_p,
                                                      ctypes.c_int]
        self._lib.blockpool_clear_tokens.restype = None

        self._lib.blockpool_copy_tokens.argtypes = [ctypes.c_void_p,
                                                     ctypes.c_int,
                                                     ctypes.c_int]
        self._lib.blockpool_copy_tokens.restype = None

        self._lib.blockpool_append_token.argtypes = [ctypes.c_void_p,
                                                      ctypes.c_int,
                                                      ctypes.c_int]
        self._lib.blockpool_append_token.restype = None

    def __del__(self):
        if hasattr(self, '_pool') and self._pool:
            self._lib.blockpool_destroy(self._pool)
            self._pool = None

    # -- allocation / deallocation -----------------------------------------

    def allocate(self) -> int:
        block_id = self._lib.blockpool_allocate(self._pool)
        if block_id < 0:
            raise RuntimeError(f"Out of free blocks on {self.device}")
        self.blocks[block_id].content_hash = None
        return block_id

    def free(self, block_id: int):
        self._lib.blockpool_free(self._pool, block_id)
        if self._lib.blockpool_get_refcount(self._pool, block_id) == 0:
            self.blocks[block_id].content_hash = None

    def increment_ref(self, block_id: int):
        self._lib.blockpool_incref(self._pool, block_id)

    def get_ref_count(self, block_id: int) -> int:
        return self._lib.blockpool_get_refcount(self._pool, block_id)

    def get_num_free(self) -> int:
        return self._lib.blockpool_num_free(self._pool)

    # -- prefix cache ------------------------------------------------------

    def compute_hash(self, token_ids: list) -> str:
        return hashlib.sha256(str(token_ids).encode()).hexdigest()[:16]

    def cache_full_block(self, block_id: int):
        block = self.blocks[block_id]
        toks = block.token_ids
        if len(toks) == self.block_size:
            h = self.compute_hash(toks)
            block.content_hash = h
            self.hash_to_block[h] = block_id

    def lookup_cache(self, token_ids: list) -> Optional[int]:
        h = self.compute_hash(token_ids)
        block_id = self.hash_to_block.get(h)
        if block_id is not None:
            return block_id
        return None


# ---------------------------------------------------------------------------
#  BlockManager — coordinates GPU / CPU allocators, block tables, swapping
# ---------------------------------------------------------------------------

class BlockManager:
    """
    KV cache block manager using PagedAttention.

    Manages block allocation, sharing, caching, swapping, and preemption
    for serving multiple concurrent LLM sequences.
    """

    def __init__(self, block_size: int, num_gpu_blocks: int,
                 num_cpu_blocks: int,
                 enable_prefix_caching: bool = False):
        self.block_size = block_size
        self.gpu_allocator = BlockAllocator(num_gpu_blocks, block_size, "gpu")
        self.cpu_allocator = BlockAllocator(num_cpu_blocks, block_size, "cpu")
        self.enable_prefix_caching = enable_prefix_caching

        self.block_tables: dict = {}
        self.seq_tokens: dict = {}
        self.seq_to_group: dict = {}
        self.group_seqs: dict = {}
        self.swapped_block_tables: dict = {}
        self.group_arrival: dict = {}
        self._next_arrival: int = 0

    # -- helpers -----------------------------------------------------------

    def _num_blocks_needed(self, num_tokens: int) -> int:
        if num_tokens == 0:
            return 0
        return (num_tokens + self.block_size) // self.block_size

    def can_allocate(self, num_tokens: int) -> bool:
        return (self.gpu_allocator.get_num_free()
                >= self._num_blocks_needed(num_tokens))

    # -- sequence lifecycle ------------------------------------------------

    def allocate_sequence(self, seq_id: int, group_id: int,
                          token_ids: list) -> bool:
        if seq_id in self.block_tables:
            return False

        num_blocks = self._num_blocks_needed(len(token_ids))
        if self.gpu_allocator.get_num_free() < num_blocks:
            return False

        block_table = []
        for i in range(num_blocks):
            start = i * self.block_size
            end = min(start + self.block_size, len(token_ids))
            chunk = token_ids[start:end]

            cached = None
            if (self.enable_prefix_caching
                    and len(chunk) == self.block_size):
                cached = self.gpu_allocator.lookup_cache(chunk)

            if cached is not None:
                self.gpu_allocator.increment_ref(cached)
                block_table.append(cached)
            else:
                bid = self.gpu_allocator.allocate()
                self.gpu_allocator.blocks[bid].token_ids = list(chunk)
                if (self.enable_prefix_caching
                        and len(chunk) == self.block_size):
                    self.gpu_allocator.cache_full_block(bid)
                block_table.append(bid)

        self.block_tables[seq_id] = block_table
        self.seq_tokens[seq_id] = list(token_ids)
        self.seq_to_group[seq_id] = group_id
        if group_id not in self.group_seqs:
            self.group_seqs[group_id] = set()
            self.group_arrival[group_id] = self._next_arrival
            self._next_arrival += 1
        self.group_seqs[group_id].add(seq_id)
        return True

    def can_append(self, seq_id: int) -> bool:
        if seq_id not in self.block_tables:
            return False
        n = len(self.seq_tokens[seq_id])
        bt = self.block_tables[seq_id]
        if n > 0 and n % self.block_size == 0:
            return self.gpu_allocator.get_num_free() >= 1
        if bt:
            last = self.gpu_allocator.blocks[bt[-1]]
            if last.ref_count > 1:
                return self.gpu_allocator.get_num_free() >= 1
        return True

    def append_token(self, seq_id: int, token_id: int) -> bool:
        if seq_id not in self.block_tables:
            return False

        num_tokens = len(self.seq_tokens[seq_id])
        block_table = self.block_tables[seq_id]

        # Need a new block if the current one is full
        if num_tokens > 0 and num_tokens % self.block_size == 0:
            if self.gpu_allocator.get_num_free() < 1:
                return False
            new_bid = self.gpu_allocator.allocate()
            block_table.append(new_bid)

        last_block_id = block_table[-1]
        last_block = self.gpu_allocator.blocks[last_block_id]

        # Copy-on-write for shared blocks
        if last_block.ref_count > 1:
            if self.gpu_allocator.get_num_free() < 1:
                return False
            new_bid = self.gpu_allocator.allocate()
            new_block = self.gpu_allocator.blocks[new_bid]
            new_block.token_ids = list(last_block.token_ids)
            last_block.ref_count -= 1
            block_table[-1] = new_bid
            last_block_id = new_bid
            last_block = new_block

        # Invalidate stale content hash
        if last_block.content_hash is not None:
            if last_block.content_hash in self.gpu_allocator.hash_to_block:
                del self.gpu_allocator.hash_to_block[last_block.content_hash]
            last_block.content_hash = None

        last_block.token_ids = last_block.token_ids + [token_id]
        self.seq_tokens[seq_id].append(token_id)

        if (self.enable_prefix_caching
                and len(last_block.token_ids) == self.block_size):
            self.gpu_allocator.cache_full_block(last_block_id)

        return True

    def fork_sequence(self, parent_seq_id: int,
                      child_seq_id: int) -> bool:
        if parent_seq_id not in self.block_tables:
            return False
        if child_seq_id in self.block_tables:
            return False

        parent_table = self.block_tables[parent_seq_id]
        child_table = []
        for bid in parent_table:
            self.gpu_allocator.increment_ref(bid)
            child_table.append(bid)

        self.block_tables[child_seq_id] = child_table
        self.seq_tokens[child_seq_id] = list(self.seq_tokens[parent_seq_id])

        group_id = self.seq_to_group[parent_seq_id]
        self.seq_to_group[child_seq_id] = group_id

        return True

    def free_sequence(self, seq_id: int) -> bool:
        if seq_id not in self.block_tables:
            return False

        for bid in self.block_tables[seq_id]:
            self.gpu_allocator.free(bid)

        group_id = self.seq_to_group[seq_id]
        del self.block_tables[seq_id]
        del self.seq_tokens[seq_id]
        del self.seq_to_group[seq_id]

        if group_id in self.group_seqs:
            self.group_seqs[group_id].discard(seq_id)
            if not self.group_seqs[group_id]:
                del self.group_seqs[group_id]
                if group_id in self.group_arrival:
                    del self.group_arrival[group_id]
        return True

    # -- swapping ----------------------------------------------------------

    def swap_out(self, group_id: int) -> dict:
        if group_id not in self.group_seqs:
            return {}

        gpu_to_cpu: dict = {}
        for seq_id in list(self.group_seqs[group_id]):
            if seq_id not in self.block_tables:
                continue
            bt = self.block_tables[seq_id]
            new_table = []
            for gpu_bid in bt:
                if gpu_bid in gpu_to_cpu:
                    cpu_bid = gpu_to_cpu[gpu_bid]
                    self.cpu_allocator.increment_ref(cpu_bid)
                else:
                    cpu_bid = self.cpu_allocator.allocate()
                    gpu_blk = self.gpu_allocator.blocks[gpu_bid]
                    cpu_blk = self.cpu_allocator.blocks[cpu_bid]
                    cpu_blk.token_ids = list(gpu_blk.token_ids)
                    gpu_to_cpu[gpu_bid] = cpu_bid
                new_table.append(cpu_bid)
                self.gpu_allocator.free(gpu_bid)
            self.swapped_block_tables[seq_id] = new_table
            del self.block_tables[seq_id]
        return gpu_to_cpu

    def swap_in(self, group_id: int) -> dict:
        if group_id not in self.group_seqs:
            return {}

        cpu_to_gpu: dict = {}
        for seq_id in list(self.group_seqs[group_id]):
            if seq_id not in self.swapped_block_tables:
                continue
            cpu_table = self.swapped_block_tables[seq_id]
            new_table = []
            for cpu_bid in cpu_table:
                if cpu_bid in cpu_to_gpu:
                    gpu_bid = cpu_to_gpu[cpu_bid]
                    self.gpu_allocator.increment_ref(gpu_bid)
                else:
                    gpu_bid = self.gpu_allocator.allocate()
                    cpu_blk = self.cpu_allocator.blocks[cpu_bid]
                    gpu_blk = self.gpu_allocator.blocks[gpu_bid]
                    gpu_blk.token_ids = list(cpu_blk.token_ids)
                    cpu_to_gpu[cpu_bid] = gpu_bid
                new_table.append(gpu_bid)
            self.block_tables[seq_id] = new_table
            del self.swapped_block_tables[seq_id]
        return cpu_to_gpu

    # -- queries -----------------------------------------------------------

    def get_block_table(self, seq_id: int) -> list:
        return list(self.block_tables.get(seq_id, []))

    def get_num_prefix_cache_hits(self, token_ids: list) -> int:
        """Count consecutive leading full blocks present in the prefix cache.

        Divide token_ids into block_size chunks starting from the beginning.
        For each full chunk (length == block_size), check if it exists in the
        prefix cache.  Return the count of consecutive hits starting from the
        first block.  Stop at the first miss or partial block.
        """
        raise NotImplementedError("get_num_prefix_cache_hits not implemented")

    def select_victim_group(self) -> Optional[int]:
        """Select group to preempt using LIFO policy (latest arrival first).

        Return the group_id with the highest arrival index among active groups
        (those with at least one sequence in block_tables, not swapped).
        Return None if no active groups exist.
        """
        raise NotImplementedError("select_victim_group not implemented")

    def get_utilization_stats(self) -> dict:
        """Compute memory utilization statistics.

        Returns dict with keys:
        - gpu_total_blocks, gpu_used_blocks, gpu_free_blocks, gpu_utilization
        - cpu_total_blocks, cpu_used_blocks, cpu_free_blocks, cpu_utilization
        - num_active_sequences, num_swapped_sequences, num_groups
        - prefix_cache_size
        - total_shared_blocks (GPU blocks with ref_count > 1)
        """
        raise NotImplementedError("get_utilization_stats not implemented")
