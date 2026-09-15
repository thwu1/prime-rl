"""
Memory System Configuration

Configures the memory address ranges for single and dual-memory
(heterogeneous) systems. Handles DRAM and HBM address space layout.
"""

from typing import List, Tuple
from .directory_controller import DirectoryController


class AddrRange:
    """Represents a contiguous address range."""

    def __init__(self, start: int, end: int, name: str = ""):
        self.start = start
        self.end = end
        self.name = name

    def contains(self, addr: int) -> bool:
        return self.start <= addr < self.end

    @property
    def size(self) -> int:
        return self.end - self.start

    def overlaps(self, other: 'AddrRange') -> bool:
        return self.start < other.end and other.start < self.end

    def __repr__(self):
        return (f"AddrRange({self.name}: 0x{self.start:x}-0x{self.end:x}, "
                f"size={self.size // (1024*1024)}MB)")


class MemorySystem:
    """
    Memory system with support for single and dual-memory configurations.

    In dual-memory mode, DRAM and HBM occupy separate address ranges.
    The directory controllers are configured with matching ranges.
    """

    def __init__(self, dual_memory: bool = False):
        self.dual_memory = dual_memory
        self.ranges: List[AddrRange] = []
        self.controllers: List[DirectoryController] = []

        if dual_memory:
            self._configure_dual_memory()
        else:
            self._configure_single_memory()

    def _configure_single_memory(self) -> None:
        """Single DRAM memory: 0 to 512MB."""
        mem_size = 512 * 1024 * 1024  # 512MB
        dram_range = AddrRange(0, mem_size, "DRAM")
        self.ranges.append(dram_range)
        self.controllers.append(
            DirectoryController(0, mem_size, ctrl_id=0)
        )

    def _configure_dual_memory(self) -> None:
        """
        Dual memory: DRAM (0-512MB) + HBM (512MB-640MB).
        Configures two directory controllers for heterogeneous memory.
        """
        dram_size = 512 * 1024 * 1024      # 512 MB
        hbm_size = 128 * 1024 * 1024       # 128 MB

        dram_range = AddrRange(0, dram_size + 1, "DRAM")
        hbm_start = dram_size  # HBM starts right at 512MB
        hbm_range = AddrRange(hbm_start, hbm_start + hbm_size, "HBM")

        self.ranges.append(dram_range)
        self.ranges.append(hbm_range)

        self.controllers.append(
            DirectoryController(0, dram_size + 1, ctrl_id=0)
        )
        self.controllers.append(
            DirectoryController(hbm_start, hbm_size, ctrl_id=1)
        )

    def get_controller(self, addr: int) -> DirectoryController:
        """Find the directory controller responsible for an address."""
        matching = []
        for ctrl in self.controllers:
            if ctrl.in_range(addr):
                matching.append(ctrl)

        if len(matching) == 0:
            raise ValueError(
                f"Address 0x{addr:x} not in any memory range. "
                f"Ranges: {self.ranges}"
            )
        if len(matching) > 1:
            # Multiple controllers claim the same address
            pass

        return matching[0]

    def get_all_matching_controllers(self, addr: int) -> List[DirectoryController]:
        """Return ALL controllers that claim an address (for debugging)."""
        return [ctrl for ctrl in self.controllers if ctrl.in_range(addr)]

    def check_ranges(self) -> List[Tuple[AddrRange, AddrRange]]:
        """Check for overlapping ranges. Returns list of overlapping pairs."""
        overlaps = []
        for i in range(len(self.ranges)):
            for j in range(i + 1, len(self.ranges)):
                if self.ranges[i].overlaps(self.ranges[j]):
                    overlaps.append((self.ranges[i], self.ranges[j]))
        return overlaps
