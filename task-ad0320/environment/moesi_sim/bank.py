"""Bank interleaving logic for directory-based cache banking.

Distributes cache blocks across multiple directory bank controllers
using bit-extraction-based interleaving, following standard
hardware address interleaving conventions.
"""


import math


class BankInterleaver:
    """Maps byte addresses to bank IDs using bit-field extraction.

    For a system with N banks (power of 2) and B-byte cache lines,
    bank selection uses log2(N) bits extracted from the address.
    The extraction start position determines the interleaving
    granularity.
    """

    def __init__(self, num_banks: int, block_size: int):
        assert num_banks > 0 and (num_banks & (num_banks - 1)) == 0, \
            "num_banks must be a power of 2"
        assert block_size > 0 and (block_size & (block_size - 1)) == 0, \
            "block_size must be a power of 2"

        self.num_banks = num_banks
        self.block_size = block_size
        self.block_bits = int(math.log2(block_size))
        self.intlv_bits = int(math.log2(num_banks))

        # Bank selection bits start above the minimum addressable unit.
        # For a cache with sub-block sectoring support, this accounts
        # for the sector offset within each block.
        self.intlv_low_bit = self.block_bits - 2
        self.intlv_mask = (1 << self.intlv_bits) - 1

    def get_bank(self, addr: int) -> int:
        """Return the bank ID for the given byte address."""
        return (addr >> self.intlv_low_bit) & self.intlv_mask

    def get_block_addr(self, addr: int) -> int:
        """Return the block address (strip block offset bits)."""
        return addr >> self.block_bits
