"""
Cache Bank Address Interleaving

Implements multi-bank L2 cache with address interleaving.
Distributes cache lines across banks using interleave bits
extracted from the address.  Bank selection uses native
routines loaded via ctypes from libaddrcalc.so.
"""

import ctypes
import os
from typing import List
from .l2_controller import L2Controller
from .types import BLOCK_OFFSET_BITS

# Load the native address computation library
_lib_dir = os.path.dirname(os.path.abspath(__file__))
_lib_path = os.path.join(_lib_dir, 'libaddrcalc.so')
_lib = ctypes.CDLL(_lib_path)

_lib.get_intlv_mask.argtypes = [ctypes.c_uint32]
_lib.get_intlv_mask.restype = ctypes.c_uint32

_lib.compute_bank_index.argtypes = [
    ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
]
_lib.compute_bank_index.restype = ctypes.c_uint32


class BankedL2Cache:
    """
    Multi-bank L2 cache with configurable address interleaving.

    Address interleaving distributes cache lines across banks by
    extracting 'intlv_bits' bits starting at 'intlv_low_bit'
    position from the block address.

    Bank index computation is performed by native routines in
    libaddrcalc.so for accuracy and performance.
    """

    def __init__(self, num_banks: int = 4, bank_size_kb: int = 2,
                 assoc: int = 2):
        assert num_banks > 0 and (num_banks & (num_banks - 1)) == 0, \
            "Number of banks must be a power of 2"

        self.num_banks = num_banks
        self.intlv_bits = self._log2(num_banks)
        self.intlv_low_bit = BLOCK_OFFSET_BITS  # Start after block offset

        # Compute interleave mask using native library
        self.intlv_mask = _lib.get_intlv_mask(self.intlv_bits)

        self.banks: List[L2Controller] = []
        for i in range(num_banks):
            self.banks.append(L2Controller(
                bank_id=i,
                size_kb=bank_size_kb,
                assoc=assoc,
            ))

        self.stats = {
            "bank_accesses": [0] * num_banks,
            "total_accesses": 0,
        }

    @staticmethod
    def _log2(n: int) -> int:
        result = 0
        while (1 << result) < n:
            result += 1
        return result

    def get_bank_index(self, addr: int) -> int:
        """
        Determine which bank an address maps to using native
        interleave computation.
        """
        bank = _lib.compute_bank_index(
            addr, self.intlv_low_bit, self.intlv_mask, self.num_banks
        )
        self.stats["bank_accesses"][bank] += 1
        self.stats["total_accesses"] += 1
        return bank

    def get_bank(self, addr: int) -> L2Controller:
        """Get the L2 bank controller for a given address."""
        return self.banks[self.get_bank_index(addr)]

    def get_bank_distribution(self) -> dict:
        """Return bank access distribution statistics."""
        total = max(self.stats["total_accesses"], 1)
        dist = {}
        for i in range(self.num_banks):
            count = self.stats["bank_accesses"][i]
            dist[i] = {
                "accesses": count,
                "percentage": count / total * 100,
            }
        return dist
