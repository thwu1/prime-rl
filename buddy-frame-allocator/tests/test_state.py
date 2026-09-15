
import sys
import pytest

sys.path.insert(0, "/app")
from allocator import FrameAllocator
from config import (
    TOTAL_PAGES, MAX_ORDER, NR_ZONES,
    ZONE_DMA, ZONE_NORMAL, ZONE_HIGHMEM,
    ZONE_RANGES,
    MIGRATE_UNMOVABLE, MIGRATE_MOVABLE, MIGRATE_RECLAIMABLE,
)


# ---------------------------------------------------------------------------
# Basic allocation operations
# ---------------------------------------------------------------------------

class TestAllocationBasics:

    def test_init_total_free(self):
        alloc = FrameAllocator()
        total = sum(alloc.get_zone_stats(z)["free_pages"] for z in range(NR_ZONES))
        assert total == TOTAL_PAGES

    def test_init_zone_sizes(self):
        alloc = FrameAllocator()
        for z in range(NR_ZONES):
            start, end = ZONE_RANGES[z]
            stats = alloc.get_zone_stats(z)
            assert stats["total_pages"] == end - start

    def test_alloc_single_page(self):
        alloc = FrameAllocator()
        pfn = alloc.alloc_pages(0, ZONE_NORMAL, MIGRATE_MOVABLE)
        assert pfn >= 0
        info = alloc.get_allocation_info(pfn)
        assert info["allocated"] is True
        assert info["order"] == 0
        alloc.free_pages(pfn, 0)

    def test_alloc_reduces_free_count(self):
        alloc = FrameAllocator()
        before = alloc.get_zone_stats(ZONE_NORMAL)["free_pages"]
        pfn = alloc.alloc_pages(3, ZONE_NORMAL, MIGRATE_MOVABLE)
        after = alloc.get_zone_stats(ZONE_NORMAL)["free_pages"]
        assert before - after == 8
        alloc.free_pages(pfn, 3)

    def test_free_restores_pages(self):
        alloc = FrameAllocator()
        before = alloc.get_zone_stats(ZONE_NORMAL)["free_pages"]
        pfn = alloc.alloc_pages(2, ZONE_NORMAL, MIGRATE_MOVABLE)
        alloc.free_pages(pfn, 2)
        after = alloc.get_zone_stats(ZONE_NORMAL)["free_pages"]
        assert before == after

    def test_alloc_alignment(self):
        alloc = FrameAllocator()
        for order in range(MAX_ORDER + 1):
            pfn = alloc.alloc_pages(order, ZONE_NORMAL, MIGRATE_MOVABLE)
            assert pfn >= 0, f"Failed to allocate order {order}"
            assert pfn % (1 << order) == 0, (
                f"PFN {pfn} not aligned to order {order}"
            )
            alloc.free_pages(pfn, order)


# ---------------------------------------------------------------------------
# Deallocation and block coalescing
# ---------------------------------------------------------------------------

class TestDeallocation:

    def test_full_restore_after_free(self):
        """Allocate then free a single order-0 page; the zone should return
        to its pristine state."""
        alloc = FrameAllocator()
        stats_before = alloc.get_zone_stats(ZONE_NORMAL)
        pfn = alloc.alloc_pages(0, ZONE_NORMAL, MIGRATE_MOVABLE)
        alloc.free_pages(pfn, 0)
        stats_after = alloc.get_zone_stats(ZONE_NORMAL)
        assert stats_before["free_pages"] == stats_after["free_pages"]
        assert stats_before["nr_free"] == stats_after["nr_free"]

    def test_no_coalesce_across_zones(self):
        """Zone boundaries must block block coalescing."""
        alloc = FrameAllocator()
        dma = alloc.get_zone_stats(ZONE_DMA)
        normal = alloc.get_zone_stats(ZONE_NORMAL)
        assert dma["total_pages"] == 1024
        assert normal["total_pages"] == 11264


# ---------------------------------------------------------------------------
# Zone allocation and fallback
# ---------------------------------------------------------------------------

class TestZoneAllocation:

    def test_alloc_in_preferred_zone(self):
        alloc = FrameAllocator()
        pfn = alloc.alloc_pages(0, ZONE_DMA, MIGRATE_MOVABLE)
        assert ZONE_RANGES[ZONE_DMA][0] <= pfn < ZONE_RANGES[ZONE_DMA][1]
        alloc.free_pages(pfn, 0)

    def test_dma_no_fallback(self):
        """DMA has no fallback zones; exhaustion must return -1."""
        alloc = FrameAllocator()
        pfn_big = alloc.alloc_pages(MAX_ORDER, ZONE_DMA, MIGRATE_MOVABLE)
        assert pfn_big >= 0
        assert alloc.get_zone_stats(ZONE_DMA)["free_pages"] == 0
        assert alloc.alloc_pages(0, ZONE_DMA, MIGRATE_MOVABLE) == -1
        alloc.free_pages(pfn_big, MAX_ORDER)

    def test_highmem_fallback_to_normal(self):
        """HighMem should fall back to Normal when exhausted."""
        alloc = FrameAllocator()
        allocated = []
        for _ in range(4):  # 4 * 1024 = 4096 pages = full HighMem
            pfn = alloc.alloc_pages(MAX_ORDER, ZONE_HIGHMEM, MIGRATE_MOVABLE)
            assert pfn >= 0
            allocated.append((pfn, MAX_ORDER))
        assert alloc.get_zone_stats(ZONE_HIGHMEM)["free_pages"] == 0

        pfn = alloc.alloc_pages(0, ZONE_HIGHMEM, MIGRATE_MOVABLE)
        assert pfn >= 0
        assert ZONE_RANGES[ZONE_NORMAL][0] <= pfn < ZONE_RANGES[ZONE_NORMAL][1]
        alloc.free_pages(pfn, 0)
        for p, o in allocated:
            alloc.free_pages(p, o)


# ---------------------------------------------------------------------------
# Mobility grouping
# ---------------------------------------------------------------------------

class TestMobilityGrouping:

    def test_migrate_type_tracked(self):
        alloc = FrameAllocator()
        pfn = alloc.alloc_pages(0, ZONE_NORMAL, MIGRATE_UNMOVABLE)
        info = alloc.get_allocation_info(pfn)
        assert info["migrate_type"] == MIGRATE_UNMOVABLE
        alloc.free_pages(pfn, 0)

    def test_migrate_type_fallback(self):
        """UNMOVABLE alloc succeeds even when initial blocks are a different type."""
        alloc = FrameAllocator()
        pfn = alloc.alloc_pages(0, ZONE_NORMAL, MIGRATE_UNMOVABLE)
        assert pfn >= 0
        info = alloc.get_allocation_info(pfn)
        assert info["migrate_type"] == MIGRATE_UNMOVABLE
        alloc.free_pages(pfn, 0)


# ---------------------------------------------------------------------------
# Non-overlapping allocations
# ---------------------------------------------------------------------------

class TestNoOverlap:

    def test_no_overlap_single_order(self):
        alloc = FrameAllocator()
        pfns = set()
        for _ in range(500):
            pfn = alloc.alloc_pages(0, ZONE_NORMAL, MIGRATE_MOVABLE)
            assert pfn >= 0
            assert pfn not in pfns, f"Overlapping allocation at PFN {pfn}"
            pfns.add(pfn)
        for pfn in pfns:
            alloc.free_pages(pfn, 0)

    def test_no_overlap_mixed_orders(self):
        alloc = FrameAllocator()
        all_pages = set()
        allocations = []
        for order in [0, 1, 2, 3, 4, 0, 1, 0, 2, 3]:
            pfn = alloc.alloc_pages(order, ZONE_NORMAL, MIGRATE_MOVABLE)
            assert pfn >= 0
            pages = set(range(pfn, pfn + (1 << order)))
            overlap = pages & all_pages
            assert len(overlap) == 0, f"Overlap at pages {overlap}"
            all_pages |= pages
            allocations.append((pfn, order))
        for pfn, order in allocations:
            alloc.free_pages(pfn, order)


# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------

class TestCompaction:

    def test_compact_preserves_free_count(self):
        """Compaction must not change the total number of free pages."""
        alloc = FrameAllocator()
        allocated = []
        for _ in range(100):
            pfn = alloc.alloc_pages(0, ZONE_NORMAL, MIGRATE_MOVABLE)
            allocated.append(pfn)
        for i in range(0, 100, 2):
            alloc.free_pages(allocated[i], 0)
        before = alloc.get_zone_stats(ZONE_NORMAL)["free_pages"]
        moved = alloc.compact_zone(ZONE_NORMAL)
        after = alloc.get_zone_stats(ZONE_NORMAL)["free_pages"]
        assert before == after
        assert isinstance(moved, int) and moved >= 0
        # clean up remaining
        for i in range(1, 100, 2):
            info = alloc.get_allocation_info(allocated[i])
            if info and info["allocated"] and info["base_pfn"] == allocated[i]:
                alloc.free_pages(allocated[i], 0)

    def test_compact_movable_only(self):
        """Compaction must not move UNMOVABLE or higher-order pages."""
        alloc = FrameAllocator()
        unmov_pfn = alloc.alloc_pages(0, ZONE_NORMAL, MIGRATE_UNMOVABLE)
        order2_pfn = alloc.alloc_pages(2, ZONE_NORMAL, MIGRATE_MOVABLE)
        alloc.compact_zone(ZONE_NORMAL)

        info_u = alloc.get_allocation_info(unmov_pfn)
        assert info_u["allocated"] is True
        assert info_u["base_pfn"] == unmov_pfn

        info_o2 = alloc.get_allocation_info(order2_pfn)
        assert info_o2["allocated"] is True
        assert info_o2["base_pfn"] == order2_pfn

        alloc.free_pages(unmov_pfn, 0)
        alloc.free_pages(order2_pfn, 2)


# ---------------------------------------------------------------------------
# Fragmentation index
# ---------------------------------------------------------------------------

class TestFragmentation:

    def test_no_fragmentation_initially(self):
        alloc = FrameAllocator()
        for order in range(MAX_ORDER + 1):
            frag = alloc.fragmentation_index(ZONE_NORMAL, order)
            assert frag == 0.0, f"Unexpected frag {frag} for order {order}"

    def test_fragmentation_after_scatter(self):
        """Interleaved free/allocated pages should produce high fragmentation."""
        alloc = FrameAllocator()
        allocated = []
        while True:
            pfn = alloc.alloc_pages(0, ZONE_DMA, MIGRATE_MOVABLE)
            if pfn < 0:
                break
            allocated.append(pfn)
        assert len(allocated) == 1024
        for i in range(0, len(allocated), 2):
            alloc.free_pages(allocated[i], 0)
        frag = alloc.fragmentation_index(ZONE_DMA, 3)
        assert frag > 0.0
        for i in range(1, len(allocated), 2):
            alloc.free_pages(allocated[i], 0)

    def test_fragmentation_low_memory(self):
        """When free pages < 2^order, must return -1.0."""
        alloc = FrameAllocator()
        allocated = []
        while True:
            pfn = alloc.alloc_pages(0, ZONE_DMA, MIGRATE_MOVABLE)
            if pfn < 0:
                break
            allocated.append(pfn)
        alloc.free_pages(allocated.pop(), 0)
        frag = alloc.fragmentation_index(ZONE_DMA, 1)
        assert frag == -1.0
        for pfn in allocated:
            alloc.free_pages(pfn, 0)


# ---------------------------------------------------------------------------
# Stress tests
# ---------------------------------------------------------------------------

class TestStress:

    def test_alloc_free_cycle(self):
        """Repeated alloc/free cycles must return to the initial state."""
        alloc = FrameAllocator()
        initial = alloc.get_zone_stats(ZONE_NORMAL)
        for _ in range(50):
            pfns = []
            for order in [0, 1, 2, 3]:
                pfn = alloc.alloc_pages(order, ZONE_NORMAL, MIGRATE_MOVABLE)
                assert pfn >= 0
                pfns.append((pfn, order))
            for pfn, order in pfns:
                alloc.free_pages(pfn, order)
        final = alloc.get_zone_stats(ZONE_NORMAL)
        assert initial["free_pages"] == final["free_pages"]
        assert initial["nr_free"] == final["nr_free"]

    def test_exhaust_and_recover(self):
        """Exhaust all memory, free everything, verify full recovery."""
        alloc = FrameAllocator()
        allocated = []
        for zone in [ZONE_DMA, ZONE_NORMAL, ZONE_HIGHMEM]:
            while True:
                pfn = alloc.alloc_pages(MAX_ORDER, zone, MIGRATE_MOVABLE)
                if pfn < 0:
                    break
                allocated.append((pfn, MAX_ORDER))
        total = sum(alloc.get_zone_stats(z)["free_pages"] for z in range(NR_ZONES))
        assert total == 0
        for pfn, order in allocated:
            alloc.free_pages(pfn, order)
        total = sum(alloc.get_zone_stats(z)["free_pages"] for z in range(NR_ZONES))
        assert total == TOTAL_PAGES

    def test_large_order_alloc(self):
        alloc = FrameAllocator()
        pfn = alloc.alloc_pages(MAX_ORDER, ZONE_NORMAL, MIGRATE_MOVABLE)
        assert pfn >= 0
        info = alloc.get_allocation_info(pfn)
        assert info["order"] == MAX_ORDER
        alloc.free_pages(pfn, MAX_ORDER)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_invalid_order_returns_neg1(self):
        alloc = FrameAllocator()
        assert alloc.alloc_pages(MAX_ORDER + 1, ZONE_NORMAL, MIGRATE_MOVABLE) == -1
        assert alloc.alloc_pages(-1, ZONE_NORMAL, MIGRATE_MOVABLE) == -1

    def test_double_free_raises(self):
        alloc = FrameAllocator()
        pfn = alloc.alloc_pages(0, ZONE_NORMAL, MIGRATE_MOVABLE)
        alloc.free_pages(pfn, 0)
        with pytest.raises(ValueError):
            alloc.free_pages(pfn, 0)

    def test_free_wrong_order_raises(self):
        alloc = FrameAllocator()
        pfn = alloc.alloc_pages(2, ZONE_NORMAL, MIGRATE_MOVABLE)
        with pytest.raises(ValueError):
            alloc.free_pages(pfn, 3)
        alloc.free_pages(pfn, 2)

    def test_info_free_page(self):
        alloc = FrameAllocator()
        info = alloc.get_allocation_info(ZONE_RANGES[ZONE_NORMAL][0])
        assert info["allocated"] is False

    def test_info_out_of_range(self):
        alloc = FrameAllocator()
        assert alloc.get_allocation_info(TOTAL_PAGES + 1) is None
        assert alloc.get_allocation_info(-1) is None
