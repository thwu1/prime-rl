import math
from collections import OrderedDict
from typing import Optional

from block_manager_interface import (
    BlockManagerConfig,
    BlockManagerInterface,
    MemorySnapshot,
    PreemptionMode,
    SequenceStatus,
)


class _PhysicalBlock:
    __slots__ = ("block_id", "device", "ref_count", "token_ids")

    def __init__(self, block_id, device):
        self.block_id = block_id
        self.device = device
        self.ref_count = 0
        self.token_ids = []

    def is_full(self, block_size):
        return len(self.token_ids) >= block_size


class _SequenceInfo:
    __slots__ = ("seq_id", "arrival_order", "block_table", "num_tokens", "is_swapped")

    def __init__(self, seq_id, arrival_order):
        self.seq_id = seq_id
        self.arrival_order = arrival_order
        self.block_table = []
        self.num_tokens = 0
        self.is_swapped = False


class BlockManager(BlockManagerInterface):

    def __init__(self, config):
        self.config = config
        self._arrival_counter = 0

        self.gpu_blocks = {}
        self.gpu_free_ids = []
        for i in range(config.num_gpu_blocks):
            self.gpu_blocks[i] = _PhysicalBlock(i, "gpu")
            self.gpu_free_ids.append(i)

        self.cpu_blocks = {}
        self.cpu_free_ids = []
        for i in range(config.num_cpu_blocks):
            self.cpu_blocks[i] = _PhysicalBlock(i, "cpu")
            self.cpu_free_ids.append(i)

        self.sequences = {}
        self.hash_to_block = {}
        self.evictable_blocks = OrderedDict()
        self.prefix_cache_hits = 0
        self.prefix_cache_misses = 0
        self.cow_copies = 0

    def _alloc_gpu_block(self):
        if self.gpu_free_ids:
            return self.gpu_free_ids.pop(0)
        if self.config.enable_prefix_caching and self.evictable_blocks:
            block_id, _ = self.evictable_blocks.popitem(last=False)
            block = self.gpu_blocks[block_id]
            ck = tuple(block.token_ids)
            if ck in self.hash_to_block and self.hash_to_block[ck] == block_id:
                del self.hash_to_block[ck]
            block.token_ids = []
            block.ref_count = 0
            return block_id
        return None

    def _free_gpu_block(self, block_id):
        block = self.gpu_blocks[block_id]
        if self.config.enable_prefix_caching and block.is_full(self.config.block_size):
            self.evictable_blocks[block_id] = None
        else:
            ck = tuple(block.token_ids)
            if ck in self.hash_to_block and self.hash_to_block[ck] == block_id:
                del self.hash_to_block[ck]
            block.token_ids = []
            block.ref_count = 0
            self.gpu_free_ids.append(block_id)

    def _alloc_cpu_block(self):
        if self.cpu_free_ids:
            return self.cpu_free_ids.pop(0)
        return None

    def _free_cpu_block(self, block_id):
        block = self.cpu_blocks[block_id]
        block.token_ids = []
        block.ref_count = 0
        self.cpu_free_ids.append(block_id)

    def allocate(self, seq_id, token_ids):
        if seq_id in self.sequences:
            return False

        if not token_ids:
            seq = _SequenceInfo(seq_id, self._arrival_counter)
            self._arrival_counter += 1
            self.sequences[seq_id] = seq
            return True

        num_blocks = math.ceil(len(token_ids) / self.config.block_size)

        plan = []
        for i in range(num_blocks):
            start = i * self.config.block_size
            end = min(start + self.config.block_size, len(token_ids))
            btokens = token_ids[start:end]
            is_full = len(btokens) == self.config.block_size

            if self.config.enable_prefix_caching and is_full:
                ck = tuple(btokens)
                if ck in self.hash_to_block:
                    plan.append(("hit", self.hash_to_block[ck], btokens))
                    continue

            plan.append(("miss", None, btokens))

        num_misses = sum(1 for t, _, _ in plan if t == "miss")
        available = len(self.gpu_free_ids)
        if self.config.enable_prefix_caching:
            evictable_count = len(self.evictable_blocks)
            for ht, bid, _ in plan:
                if ht == "hit" and bid in self.evictable_blocks:
                    evictable_count -= 1
            available += evictable_count
        if num_misses > available:
            return False

        seq = _SequenceInfo(seq_id, self._arrival_counter)
        self._arrival_counter += 1
        seq.num_tokens = len(token_ids)

        for hit_type, bid, btokens in plan:
            if hit_type == "hit":
                block = self.gpu_blocks[bid]
                block.ref_count += 1
                if bid in self.evictable_blocks:
                    del self.evictable_blocks[bid]
                seq.block_table.append(bid)
                self.prefix_cache_hits += 1
            else:
                new_id = self._alloc_gpu_block()
                block = self.gpu_blocks[new_id]
                block.ref_count = 1
                block.token_ids = list(btokens)
                seq.block_table.append(new_id)
                if self.config.enable_prefix_caching:
                    if len(btokens) == self.config.block_size:
                        self.prefix_cache_misses += 1
                        self.hash_to_block[tuple(btokens)] = new_id

        self.sequences[seq_id] = seq
        return True

    def append_tokens(self, seq_id, token_ids):
        if seq_id not in self.sequences:
            return False
        seq = self.sequences[seq_id]
        if seq.is_swapped:
            return False
        if not token_ids:
            return True

        remaining = list(token_ids)

        while remaining:
            if seq.block_table:
                last_bid = seq.block_table[-1]
                last_block = self.gpu_blocks[last_bid]
                space = self.config.block_size - len(last_block.token_ids)

                if space > 0:
                    if last_block.ref_count > 1:
                        new_id = self._alloc_gpu_block()
                        if new_id is None:
                            return False
                        new_block = self.gpu_blocks[new_id]
                        new_block.token_ids = list(last_block.token_ids)
                        new_block.ref_count = 1
                        last_block.ref_count -= 1
                        seq.block_table[-1] = new_id
                        self.cow_copies += 1
                        last_bid = new_id
                        last_block = new_block
                        space = self.config.block_size - len(last_block.token_ids)

                    fill = min(space, len(remaining))
                    last_block.token_ids.extend(remaining[:fill])
                    remaining = remaining[fill:]
                    seq.num_tokens += fill
                    continue

            new_id = self._alloc_gpu_block()
            if new_id is None:
                return False
            new_block = self.gpu_blocks[new_id]
            new_block.ref_count = 1
            fill = min(self.config.block_size, len(remaining))
            new_block.token_ids = remaining[:fill]
            remaining = remaining[fill:]
            seq.block_table.append(new_id)
            seq.num_tokens += fill

        return True

    def fork(self, parent_seq_id, child_seq_id):
        if parent_seq_id not in self.sequences:
            return False
        if child_seq_id in self.sequences:
            return False
        parent = self.sequences[parent_seq_id]
        if parent.is_swapped:
            return False

        child = _SequenceInfo(child_seq_id, self._arrival_counter)
        self._arrival_counter += 1
        child.num_tokens = parent.num_tokens
        child.block_table = list(parent.block_table)

        for bid in child.block_table:
            self.gpu_blocks[bid].ref_count += 1

        self.sequences[child_seq_id] = child
        return True

    def free(self, seq_id):
        if seq_id not in self.sequences:
            return
        seq = self.sequences[seq_id]

        if seq.is_swapped:
            for bid in seq.block_table:
                block = self.cpu_blocks[bid]
                block.ref_count -= 1
                if block.ref_count == 0:
                    self._free_cpu_block(bid)
        else:
            for bid in seq.block_table:
                block = self.gpu_blocks[bid]
                block.ref_count -= 1
                if block.ref_count == 0:
                    self._free_gpu_block(bid)

        del self.sequences[seq_id]

    def swap_out(self, seq_id):
        if seq_id not in self.sequences:
            return False
        seq = self.sequences[seq_id]
        if seq.is_swapped:
            return False
        if len(self.cpu_free_ids) < len(seq.block_table):
            return False

        new_table = []
        gpu_to_free = []

        for gpu_bid in seq.block_table:
            cpu_bid = self._alloc_cpu_block()
            cpu_block = self.cpu_blocks[cpu_bid]
            gpu_block = self.gpu_blocks[gpu_bid]

            cpu_block.token_ids = list(gpu_block.token_ids)
            cpu_block.ref_count = 1

            gpu_block.ref_count -= 1
            if gpu_block.ref_count == 0:
                gpu_to_free.append(gpu_bid)

            new_table.append(cpu_bid)

        for bid in gpu_to_free:
            self._free_gpu_block(bid)

        seq.block_table = new_table
        seq.is_swapped = True
        return True

    def swap_in(self, seq_id):
        if seq_id not in self.sequences:
            return False
        seq = self.sequences[seq_id]
        if not seq.is_swapped:
            return False

        num_needed = len(seq.block_table)
        available = len(self.gpu_free_ids)
        if self.config.enable_prefix_caching:
            available += len(self.evictable_blocks)
        if available < num_needed:
            return False

        new_table = []
        cpu_to_free = []

        for cpu_bid in seq.block_table:
            gpu_bid = self._alloc_gpu_block()
            gpu_block = self.gpu_blocks[gpu_bid]
            cpu_block = self.cpu_blocks[cpu_bid]

            gpu_block.token_ids = list(cpu_block.token_ids)
            gpu_block.ref_count = 1

            cpu_block.ref_count -= 1
            if cpu_block.ref_count == 0:
                cpu_to_free.append(cpu_bid)

            new_table.append(gpu_bid)

        for bid in cpu_to_free:
            self._free_cpu_block(bid)

        seq.block_table = new_table
        seq.is_swapped = False
        return True

    def get_sequence_status(self, seq_id):
        if seq_id not in self.sequences:
            return None
        seq = self.sequences[seq_id]
        return SequenceStatus(
            seq_id=seq.seq_id,
            num_logical_blocks=len(seq.block_table),
            num_tokens=seq.num_tokens,
            is_swapped=seq.is_swapped,
            block_table=list(seq.block_table),
        )

    def get_memory_snapshot(self):
        gpu_used = sum(1 for b in self.gpu_blocks.values() if b.ref_count > 0)
        gpu_cached = len(self.evictable_blocks)
        gpu_free = self.config.num_gpu_blocks - gpu_used - gpu_cached

        cpu_used = sum(1 for b in self.cpu_blocks.values() if b.ref_count > 0)
        cpu_free = self.config.num_cpu_blocks - cpu_used

        active = sum(1 for s in self.sequences.values() if not s.is_swapped)
        swapped = sum(1 for s in self.sequences.values() if s.is_swapped)

        return MemorySnapshot(
            gpu_blocks_used=gpu_used,
            gpu_blocks_free=gpu_free,
            gpu_blocks_cached=gpu_cached,
            cpu_blocks_used=cpu_used,
            cpu_blocks_free=cpu_free,
            num_active_sequences=active,
            num_swapped_sequences=swapped,
            prefix_cache_hits=self.prefix_cache_hits,
            prefix_cache_misses=self.prefix_cache_misses,
            cow_copies=self.cow_copies,
        )

    def can_allocate(self, num_tokens):
        if num_tokens <= 0:
            return True
        blocks_needed = math.ceil(num_tokens / self.config.block_size)
        available = len(self.gpu_free_ids)
        if self.config.enable_prefix_caching:
            available += len(self.evictable_blocks)
        return available >= blocks_needed

    def get_num_free_gpu_blocks(self):
        return len(self.gpu_free_ids)

    def get_num_free_cpu_blocks(self):
        return len(self.cpu_free_ids)

    def select_preemption_victim(self):
        active = [s for s in self.sequences.values() if not s.is_swapped]
        if not active:
            return None
        return max(active, key=lambda s: s.arrival_order).seq_id
