"""
Reference block management patterns from vLLM.

This module illustrates the core data structures and algorithms used
in vLLM's block manager for PagedAttention KV cache management.
It is NOT a complete implementation — it shows the key design patterns.

See also: https://github.com/vllm-project/vllm/tree/main/vllm/core

Physical blocks are the GPU memory units that store KV cache for
a fixed number of tokens (block_size). They are managed with
reference counting to allow sharing between sequences produced
by parallel sampling or beam search.

Per-token KV cache size (bytes):
    2 * num_kv_heads * head_dim * num_layers * dtype_bytes
    (factor of 2 for key + value tensors across all layers)
"""


class PhysicalTokenBlock:
    """A physical block of KV cache on GPU memory.

    Each block stores KV vectors for up to block_size tokens.
    Blocks are reference-counted to support sharing between
    sequences (parallel sampling, beam search).
    """

    def __init__(self, block_number: int, block_size: int):
        self.block_number = block_number
        self.block_size = block_size
        self.ref_count = 0
        self.num_tokens = 0  # Number of tokens stored

    @property
    def is_full(self) -> bool:
        return self.num_tokens >= self.block_size


class BlockSpaceManager:
    """Manages physical blocks with reference-counted sharing.

    Physical blocks are allocated from a free pool. When a block's
    reference count drops to zero, it is returned to the free pool
    for reuse. Fork creates shallow copies of block tables (NOT
    aliases), incrementing ref counts on shared blocks. Copy-on-write
    handles modification of shared blocks.
    """

    def __init__(self, block_size: int, num_blocks: int):
        self.block_size = block_size
        self.free_blocks = list(range(num_blocks))
        self.blocks = {}

    def allocate(self) -> int:
        """Allocate a physical block from the free pool."""
        block_id = self.free_blocks.pop()
        block = PhysicalTokenBlock(block_id, self.block_size)
        block.ref_count = 1
        self.blocks[block_id] = block
        return block_id

    def free(self, block_id: int) -> None:
        """Decrement ref count. Reclaim block when count reaches zero."""
        block = self.blocks[block_id]
        block.ref_count -= 1
        if block.ref_count == 0:
            del self.blocks[block_id]
            self.free_blocks.append(block_id)

    def fork_block_table(self, source_table: list[int]) -> list[int]:
        """Create a new block table sharing all blocks with the source.

        Returns a NEW list (not a reference to the source) with the
        same block IDs. Reference counts are incremented for each
        shared block.
        """
        new_table = list(source_table)  # Must copy, not alias
        for block_id in new_table:
            self.blocks[block_id].ref_count += 1
        return new_table

    def append_token(self, block_table: list[int]) -> list[int]:
        """Append a single token to a sequence's KV cache.

        Handles three cases:
        1. Last block is full -> allocate new block
        2. Last block is shared (ref > 1) -> copy-on-write
        3. Last block is private with space -> increment fill

        In the copy-on-write case, the new block's token count
        equals the old block's count PLUS the newly appended token.
        """
        last_id = block_table[-1]
        last_block = self.blocks[last_id]

        if last_block.is_full:
            new_id = self.allocate()
            self.blocks[new_id].num_tokens = 1
            block_table.append(new_id)
        elif last_block.ref_count > 1:
            old_tokens = last_block.num_tokens
            last_block.ref_count -= 1
            new_id = self.allocate()
            self.blocks[new_id].num_tokens = old_tokens + 1
            block_table[-1] = new_id
        else:
            last_block.num_tokens += 1

        return block_table
