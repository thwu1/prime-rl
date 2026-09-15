
"""
Multi-Zone Buddy Frame Allocator — reference implementation.
"""

from config import *


class FrameAllocator:
    """Multi-zone buddy frame allocator with anti-fragmentation support."""

    def __init__(self):
        # Per-page metadata
        self._page_info = [
            {
                "allocated": False,
                "order": -1,
                "zone": -1,
                "migrate_type": -1,
                "base_pfn": -1,
            }
            for _ in range(TOTAL_PAGES)
        ]

        # free_lists[zone][migrate_type][order] -> set of base PFNs
        self._free_lists = [
            [[set() for _ in range(MAX_ORDER + 1)] for _ in range(NR_MIGRATE_TYPES)]
            for _ in range(NR_ZONES)
        ]

        # Populate initial free blocks: largest aligned buddies per zone
        for zone in range(NR_ZONES):
            start, end = ZONE_RANGES[zone]
            pfn = start
            while pfn < end:
                for order in range(MAX_ORDER, -1, -1):
                    block_size = 1 << order
                    if pfn % block_size == 0 and pfn + block_size <= end:
                        self._free_lists[zone][MIGRATE_MOVABLE][order].add(pfn)
                        pfn += block_size
                        break

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pfn_to_zone(pfn):
        for z in range(NR_ZONES):
            s, e = ZONE_RANGES[z]
            if s <= pfn < e:
                return z
        return -1

    def _try_alloc_from_list(self, zone, mt, order):
        """Try to allocate from a specific (zone, migrate_type) free list.
        Returns the base PFN or -1."""
        for cur_order in range(order, MAX_ORDER + 1):
            bucket = self._free_lists[zone][mt][cur_order]
            if bucket:
                pfn = min(bucket)
                bucket.remove(pfn)
                # Split down to requested order
                while cur_order > order:
                    cur_order -= 1
                    buddy_half = pfn + (1 << cur_order)
                    self._free_lists[zone][mt][cur_order].add(buddy_half)
                return pfn
        return -1

    def _remove_free_page(self, zone, pfn):
        """Extract a single page *pfn* from whatever free block contains it,
        splitting larger blocks as needed."""
        for order in range(MAX_ORDER + 1):
            block_pfn = pfn & ~((1 << order) - 1)
            for mt in range(NR_MIGRATE_TYPES):
                if block_pfn in self._free_lists[zone][mt][order]:
                    self._free_lists[zone][mt][order].remove(block_pfn)
                    # Split the block down, keeping everything except *pfn*
                    cur_pfn = block_pfn
                    cur_order = order
                    while cur_order > 0:
                        cur_order -= 1
                        half = 1 << cur_order
                        if pfn < cur_pfn + half:
                            # target in lower half -> upper half goes back
                            self._free_lists[zone][mt][cur_order].add(cur_pfn + half)
                        else:
                            # target in upper half -> lower half goes back
                            self._free_lists[zone][mt][cur_order].add(cur_pfn)
                            cur_pfn = cur_pfn + half
                    return
        # Should not reach here if pfn is truly free
        raise RuntimeError(f"_remove_free_page: PFN {pfn} not found in any free list")

    def _add_free_and_merge(self, zone, pfn, migrate_type):
        """Insert a single page back into the free lists, performing buddy
        merging upward as far as possible."""
        cur_pfn = pfn
        cur_order = 0
        zone_start, zone_end = ZONE_RANGES[zone]
        while cur_order < MAX_ORDER:
            buddy_pfn = cur_pfn ^ (1 << cur_order)
            if buddy_pfn < zone_start or buddy_pfn >= zone_end:
                break
            found = False
            for mt in range(NR_MIGRATE_TYPES):
                if buddy_pfn in self._free_lists[zone][mt][cur_order]:
                    self._free_lists[zone][mt][cur_order].remove(buddy_pfn)
                    found = True
                    break
            if not found:
                break
            cur_pfn = min(cur_pfn, buddy_pfn)
            cur_order += 1
        self._free_lists[zone][migrate_type][cur_order].add(cur_pfn)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def alloc_pages(self, order, zone_pref, migrate_type):
        if order < 0 or order > MAX_ORDER:
            return -1
        if zone_pref < 0 or zone_pref >= NR_ZONES:
            return -1
        if migrate_type < 0 or migrate_type >= NR_MIGRATE_TYPES:
            return -1

        zones = [zone_pref] + ZONE_FALLBACK.get(zone_pref, [])
        for zone in zones:
            mtypes = [migrate_type] + MIGRATE_FALLBACK.get(migrate_type, [])
            for mt in mtypes:
                pfn = self._try_alloc_from_list(zone, mt, order)
                if pfn >= 0:
                    for p in range(pfn, pfn + (1 << order)):
                        self._page_info[p] = {
                            "allocated": True,
                            "order": order,
                            "zone": zone,
                            "migrate_type": migrate_type,
                            "base_pfn": pfn,
                        }
                    return pfn
        return -1

    def free_pages(self, pfn, order):
        if pfn < 0 or pfn >= TOTAL_PAGES:
            raise ValueError(f"PFN {pfn} out of range")
        info = self._page_info[pfn]
        if not info["allocated"]:
            raise ValueError(f"PFN {pfn} is not allocated")
        if info["base_pfn"] != pfn:
            raise ValueError(
                f"PFN {pfn} is not the base of an allocation "
                f"(base is {info['base_pfn']})"
            )
        if info["order"] != order:
            raise ValueError(
                f"PFN {pfn} was allocated with order {info['order']}, not {order}"
            )

        zone = info["zone"]
        migrate_type = info["migrate_type"]

        # Clear page metadata
        for p in range(pfn, pfn + (1 << order)):
            self._page_info[p] = {
                "allocated": False,
                "order": -1,
                "zone": -1,
                "migrate_type": -1,
                "base_pfn": -1,
            }

        # Buddy merging
        cur_pfn = pfn
        cur_order = order
        zone_start, zone_end = ZONE_RANGES[zone]

        while cur_order < MAX_ORDER:
            buddy_pfn = cur_pfn ^ (1 << cur_order)
            if buddy_pfn < zone_start or buddy_pfn >= zone_end:
                break
            # Check if buddy is free at this order (any migrate type)
            found = False
            for mt in range(NR_MIGRATE_TYPES):
                if buddy_pfn in self._free_lists[zone][mt][cur_order]:
                    self._free_lists[zone][mt][cur_order].remove(buddy_pfn)
                    found = True
                    break
            if not found:
                break
            cur_pfn = min(cur_pfn, buddy_pfn)
            cur_order += 1

        self._free_lists[zone][migrate_type][cur_order].add(cur_pfn)

    def get_zone_stats(self, zone):
        if zone < 0 or zone >= NR_ZONES:
            return None
        start, end = ZONE_RANGES[zone]
        nr_free = []
        free_pages = 0
        for order in range(MAX_ORDER + 1):
            count = sum(
                len(self._free_lists[zone][mt][order])
                for mt in range(NR_MIGRATE_TYPES)
            )
            nr_free.append(count)
            free_pages += count * (1 << order)
        return {
            "free_pages": free_pages,
            "total_pages": end - start,
            "nr_free": nr_free,
        }

    def compact_zone(self, zone):
        if zone < 0 or zone >= NR_ZONES:
            return 0
        zone_start, zone_end = ZONE_RANGES[zone]
        migrate_scanner = zone_start
        free_scanner = zone_end - 1
        moved = 0

        while migrate_scanner < free_scanner:
            # Advance migration scanner to next MOVABLE order-0 allocated page
            while migrate_scanner < free_scanner:
                info = self._page_info[migrate_scanner]
                if (
                    info["allocated"]
                    and info["migrate_type"] == MIGRATE_MOVABLE
                    and info["base_pfn"] == migrate_scanner
                    and info["order"] == 0
                ):
                    break
                migrate_scanner += 1
            if migrate_scanner >= free_scanner:
                break

            # Retreat free scanner to next unallocated page
            while free_scanner > migrate_scanner:
                if not self._page_info[free_scanner]["allocated"]:
                    break
                free_scanner -= 1
            if free_scanner <= migrate_scanner:
                break

            old_pfn = migrate_scanner
            new_pfn = free_scanner

            # Extract the destination free page (split larger blocks if needed)
            self._remove_free_page(zone, new_pfn)

            # Place allocation at new location
            self._page_info[new_pfn] = {
                "allocated": True,
                "order": 0,
                "zone": zone,
                "migrate_type": MIGRATE_MOVABLE,
                "base_pfn": new_pfn,
            }

            # Vacate old location
            self._page_info[old_pfn] = {
                "allocated": False,
                "order": -1,
                "zone": -1,
                "migrate_type": -1,
                "base_pfn": -1,
            }

            # Return old location to free pool with buddy merging
            self._add_free_and_merge(zone, old_pfn, MIGRATE_MOVABLE)

            moved += 1
            migrate_scanner += 1
            free_scanner -= 1

        return moved

    def fragmentation_index(self, zone, order):
        if zone < 0 or zone >= NR_ZONES:
            return -1.0
        if order < 0 or order > MAX_ORDER:
            return -1.0
        stats = self.get_zone_stats(zone)
        free_pages = stats["free_pages"]
        if free_pages < (1 << order):
            return -1.0
        # Check if a suitable block already exists
        for o in range(order, MAX_ORDER + 1):
            if stats["nr_free"][o] > 0:
                return 0.0
        # Fraction of free pages in blocks too small
        small_free = 0
        for o in range(order):
            small_free += stats["nr_free"][o] * (1 << o)
        if free_pages == 0:
            return -1.0
        return small_free / free_pages

    def get_allocation_info(self, pfn):
        if pfn < 0 or pfn >= TOTAL_PAGES:
            return None
        return dict(self._page_info[pfn])
