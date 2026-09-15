
from config import *


class FrameAllocator:
    """Physical memory frame allocator."""

    def __init__(self):
        """Initialize the allocator with all memory free."""
        raise NotImplementedError

    def alloc_pages(self, order, zone_pref, migrate_type):
        """Allocate 2^order contiguous, aligned page frames.

        Returns PFN of first page, or -1 on failure.
        """
        raise NotImplementedError

    def free_pages(self, pfn, order):
        """Free a previously allocated block.

        Raises ValueError on invalid operations.
        """
        raise NotImplementedError

    def get_zone_stats(self, zone):
        """Get zone statistics.

        Returns dict with keys:
            'free_pages': int
            'total_pages': int
            'nr_free': list of MAX_ORDER+1 ints (count of free blocks per order)
        """
        raise NotImplementedError

    def compact_zone(self, zone):
        """Compact a zone. Returns number of pages relocated."""
        raise NotImplementedError

    def fragmentation_index(self, zone, order):
        """Compute fragmentation metric for zone at given order. Returns float."""
        raise NotImplementedError

    def get_allocation_info(self, pfn):
        """Get metadata for a page frame.

        Returns None if pfn is out of range.
        Otherwise returns dict with keys:
            'allocated': bool
            'order': int
            'zone': int
            'migrate_type': int
            'base_pfn': int
        """
        raise NotImplementedError
