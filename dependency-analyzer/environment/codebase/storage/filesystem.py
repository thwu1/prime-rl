"""Filesystem implementation on top of block storage."""

from storage.block import Block


class FileSystem:
    """A simple filesystem using block storage."""

    def __init__(self, num_blocks: int = 256):
        self.blocks = {i: Block(i) for i in range(num_blocks)}
        self.file_table = {}

    def create_file(self, name: str) -> bool:
        """Create a new file. Returns False if it already exists."""
        if name in self.file_table:
            return False
        self.file_table[name] = []
        return True

    def allocate_block(self) -> int:
        """Find and return an unused block ID."""
        used = {b for blist in self.file_table.values() for b in blist}
        for bid in self.blocks:
            if bid not in used:
                return bid
        return -1

    def write_file(self, name: str, data: bytes) -> None:
        """Write data to a file, allocating blocks as needed."""
        if name not in self.file_table:
            raise FileNotFoundError(name)
        blocks_needed = (len(data) + Block.BLOCK_SIZE - 1) // Block.BLOCK_SIZE
        block_ids = []
        for _ in range(blocks_needed):
            bid = self.allocate_block()
            block_ids.append(bid)
        self.file_table[name] = block_ids
        for i, bid in enumerate(block_ids):
            chunk = data[i * Block.BLOCK_SIZE : (i + 1) * Block.BLOCK_SIZE]
            self.blocks[bid] = Block(bid, chunk)
