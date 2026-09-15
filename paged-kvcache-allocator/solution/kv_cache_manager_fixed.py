"""Fixed KV-cache block allocator with prefix caching."""

from typing import Dict, List, Optional
from kv_types import Block, BlockHash, Request


class FreeBlockQueue:
    """Doubly-linked list of free KV-cache blocks."""

    def __init__(self):
        self._head = None
        self._tail = None
        self._size = 0

    def append(self, block: Block):
        block.prev_free = self._tail
        block.next_free = None
        block._in_free_queue = True
        if self._tail is not None:
            self._tail.next_free = block
        else:
            self._head = block
        self._tail = block
        self._size += 1

    def popleft(self) -> Block:
        if self._head is None:
            raise RuntimeError("No free blocks available")
        block = self._head
        self._head = block.next_free
        if self._head is not None:
            self._head.prev_free = None
        else:
            self._tail = None
        block.prev_free = None
        block.next_free = None
        block._in_free_queue = False
        self._size -= 1
        return block

    def remove(self, block: Block):
        if not block._in_free_queue:
            return
        if block.prev_free is not None:
            block.prev_free.next_free = block.next_free
        else:
            self._head = block.next_free
        if block.next_free is not None:
            block.next_free.prev_free = block.prev_free
        else:
            self._tail = block.prev_free
        block.prev_free = None
        block.next_free = None
        block._in_free_queue = False
        self._size -= 1

    def __len__(self) -> int:
        return self._size


class KVCacheManager:
    """Manages a pool of KV-cache blocks with prefix caching."""

    def __init__(self, num_blocks: int, block_size: int = 16):
        self.num_blocks = num_blocks
        self.block_size = block_size
        self.blocks = [Block(block_id=i) for i in range(num_blocks)]
        self.free_block_queue = FreeBlockQueue()
        for block in self.blocks:
            self.free_block_queue.append(block)
        self.req_to_blocks: Dict[str, List[Block]] = {}
        self.req_to_block_hashes: Dict[str, List[BlockHash]] = {}
        self.cached_block_hash_to_block: Dict[int, Block] = {}

    @property
    def num_free_blocks(self) -> int:
        return len(self.free_block_queue)

    def get_num_allocated_blocks(self, request_id: str) -> int:
        return len(self.req_to_blocks.get(request_id, []))

    def hash_request_tokens(self, request: Request) -> List[BlockHash]:
        """Compute rolling hashes for complete blocks of tokens."""
        token_ids = request.token_ids
        block_hashes = []
        prev_hash = 0
        num_complete = len(token_ids) // self.block_size
        for i in range(num_complete):
            start = i * self.block_size
            chunk = tuple(token_ids[start:start + self.block_size])
            h = hash((prev_hash, chunk))
            block_hashes.append(BlockHash(hash_value=h, token_ids=chunk))
            prev_hash = h
        self.req_to_block_hashes[request.request_id] = block_hashes
        return block_hashes

    def find_longest_cache_hit(self, request: Request) -> int:
        """Count consecutive leading block hashes present in cache."""
        block_hashes = self.req_to_block_hashes.get(request.request_id, [])
        count = 0
        for bh in block_hashes:
            if bh.hash_value in self.cached_block_hash_to_block:
                count += 1
            else:
                break
        return count

    def allocate_slots(self, request: Request, num_new_tokens: int,
                       num_computed_blocks: int = 0) -> bool:
        """Allocate KV-cache blocks for a request. Atomic on failure."""
        req_id = request.request_id
        blocks_for_request = list(self.req_to_blocks.get(req_id, []))

        total_tokens = request.num_computed_tokens + num_new_tokens
        total_blocks_needed = (total_tokens + self.block_size - 1) // self.block_size

        cached_to_reuse: List[Block] = []
        if num_computed_blocks > 0 and len(blocks_for_request) == 0:
            block_hashes = self.req_to_block_hashes.get(req_id, [])
            for i in range(num_computed_blocks):
                bh = block_hashes[i]
                cached_to_reuse.append(
                    self.cached_block_hash_to_block[bh.hash_value])

        existing = len(blocks_for_request) + len(cached_to_reuse)
        new_needed = max(0, total_blocks_needed - existing)

        cached_in_fq = sum(1 for b in cached_to_reuse if b.ref_count == 0)
        available = len(self.free_block_queue) - cached_in_fq

        if new_needed > available:
            return False

        # Reuse cached blocks
        for block in cached_to_reuse:
            if block.ref_count == 0:
                self.free_block_queue.remove(block)
            block.ref_count += 1
            blocks_for_request.append(block)

        # Allocate fresh blocks from free queue
        for _ in range(new_needed):
            block = self.free_block_queue.popleft()
            if block.block_hash is not None:
                h = block.block_hash.hash_value
                if (h in self.cached_block_hash_to_block
                        and self.cached_block_hash_to_block[h] is block):
                    del self.cached_block_hash_to_block[h]
                block.block_hash = None
            block.ref_count = 1
            blocks_for_request.append(block)

        self.req_to_blocks[req_id] = blocks_for_request
        return True

    def cache_blocks(self, request_id: str):
        """Register allocated blocks in the prefix cache."""
        blocks = self.req_to_blocks.get(request_id, [])
        block_hashes = self.req_to_block_hashes.get(request_id, [])
        for i, bh in enumerate(block_hashes):
            if i < len(blocks):
                blocks[i].block_hash = bh
                self.cached_block_hash_to_block[bh.hash_value] = blocks[i]

    def free(self, request_id: str):
        """Free all blocks allocated to a request."""
        blocks = self.req_to_blocks.pop(request_id, [])
        for block in blocks:
            block.ref_count -= 1
            if block.ref_count == 0:
                self.free_block_queue.append(block)
        self.req_to_block_hashes.pop(request_id, None)
