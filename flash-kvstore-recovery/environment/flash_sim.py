"""
Flash Memory Simulator for NOR Flash.

Simulates the behavior of NOR flash memory:
- Flash starts as all 0xFF (erased state)
- Writing can only change bits from 1 to 0 (AND semantics)
- Erasing sets all bytes in a page to 0xFF
- Erase operates at page granularity
"""



class FlashSimulator:
    """Simulates NOR flash memory with realistic constraints."""

    def __init__(self, size: int, page_size: int = 4096):
        if size % page_size != 0:
            raise ValueError("Flash size must be a multiple of page size")
        if size == 0:
            raise ValueError("Flash size must be positive")
        self.size = size
        self.page_size = page_size
        self.num_pages = size // page_size
        self.data = bytearray(b'\xff' * size)
        self.erase_counts = [0] * self.num_pages

    def read(self, offset: int, length: int) -> bytes:
        """Read bytes from flash."""
        if offset < 0 or length < 0 or offset + length > self.size:
            raise ValueError(
                f"Read out of bounds: offset={offset}, length={length}, "
                f"size={self.size}"
            )
        return bytes(self.data[offset:offset + length])

    def write(self, offset: int, data: bytes) -> None:
        """
        Write bytes to flash.

        Flash writes can only change bits from 1 to 0, never 0 to 1.
        Each written byte is AND-ed with the existing byte at that position.
        """
        if offset < 0 or offset + len(data) > self.size:
            raise ValueError(
                f"Write out of bounds: offset={offset}, length={len(data)}, "
                f"size={self.size}"
            )
        for i, byte in enumerate(data):
            self.data[offset + i] &= byte

    def erase_page(self, page_num: int) -> None:
        """
        Erase a page (set all bytes to 0xFF).

        This is the only way to change bits from 0 to 1 in flash memory.
        """
        if page_num < 0 or page_num >= self.num_pages:
            raise ValueError(f"Invalid page number: {page_num}")
        start = page_num * self.page_size
        self.data[start:start + self.page_size] = b'\xff' * self.page_size
        self.erase_counts[page_num] += 1

    def get_raw(self) -> bytes:
        """Get a copy of the raw flash contents."""
        return bytes(self.data)

    def load_raw(self, data: bytes) -> None:
        """Load raw flash contents (e.g., from a flash dump)."""
        if len(data) != self.size:
            raise ValueError(
                f"Data size {len(data)} does not match flash size {self.size}"
            )
        self.data = bytearray(data)
