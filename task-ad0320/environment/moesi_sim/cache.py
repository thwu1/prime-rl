"""L1 cache model with MOESI protocol support and LR/SC reservations."""


import math
from .types import CacheState, CacheLine


class L1Cache:
    """Set-associative L1 cache with MOESI coherence states.

    Supports load-reserved / store-conditional (LR/SC) for atomic
    read-modify-write sequences.  The reservation register tracks
    a single outstanding reservation per core.
    """

    def __init__(self, core_id, num_sets=64, assoc=4, block_size=64):
        self.core_id = core_id
        self.num_sets = num_sets
        self.assoc = assoc
        self.block_size = block_size
        self.block_bits = int(math.log2(block_size))
        self.sets = [[CacheLine() for _ in range(assoc)]
                     for _ in range(num_sets)]

        # LR/SC reservation state
        self.reservation_addr = -1
        self.reservation_valid = False

        # LRU tracking: per-set list, index 0 = MRU
        self.lru = [list(range(assoc)) for _ in range(num_sets)]

    # ------------------------------------------------------------------
    # Address decomposition
    # ------------------------------------------------------------------

    def _set_index(self, addr):
        return (addr >> self.block_bits) % self.num_sets

    def _tag(self, addr):
        return (addr >> self.block_bits) // self.num_sets

    def _block_addr(self, addr):
        return addr >> self.block_bits

    # ------------------------------------------------------------------
    # Lookup / LRU helpers
    # ------------------------------------------------------------------

    def lookup(self, addr):
        """Return (CacheLine, way) or (None, -1) on miss."""
        si = self._set_index(addr)
        tag = self._tag(addr)
        for i, line in enumerate(self.sets[si]):
            if line.tag == tag and line.state != CacheState.INVALID:
                return line, i
        return None, -1

    def touch_lru(self, set_idx, way):
        """Promote *way* to MRU position."""
        lru = self.lru[set_idx]
        if way in lru:
            lru.remove(way)
        lru.insert(0, way)

    # ------------------------------------------------------------------
    # Eviction / install
    # ------------------------------------------------------------------

    def find_victim(self, addr):
        """Pick a way to use: prefer invalid, then LRU.
        Returns (way_index, evict_byte_addr | None).
        """
        si = self._set_index(addr)
        for i, line in enumerate(self.sets[si]):
            if line.state == CacheState.INVALID:
                return i, None
        victim_way = self.lru[si][-1]
        victim = self.sets[si][victim_way]
        victim_addr = (victim.tag * self.num_sets + si) << self.block_bits
        return victim_way, victim_addr

    def install(self, addr, data, state):
        """Install a new cache line, evicting if necessary.
        Returns (evicted_line_copy | None, evict_addr | None).
        """
        way, evict_addr = self.find_victim(addr)
        si = self._set_index(addr)
        evict_line = None
        if evict_addr is not None:
            old = self.sets[si][way]
            evict_line = CacheLine(state=old.state, tag=old.tag, data=old.data)
        self.sets[si][way].state = state
        self.sets[si][way].tag = self._tag(addr)
        self.sets[si][way].data = data
        self.touch_lru(si, way)
        return evict_line, evict_addr

    # ------------------------------------------------------------------
    # Coherence actions received from the interconnect
    # ------------------------------------------------------------------

    def invalidate(self, addr):
        """Invalidate a cache line (Inv / FwdGetM from directory).
        Returns (old_state, old_data).
        """
        line, way = self.lookup(addr)
        if line is not None:
            old_state = line.state
            old_data = line.data
            line.state = CacheState.INVALID
            return old_state, old_data
        return CacheState.INVALID, 0

    # ------------------------------------------------------------------
    # LR / SC support
    # ------------------------------------------------------------------

    def load_reserved(self, addr):
        """Set the reservation register for a subsequent SC."""
        self.reservation_valid = True
        self.reservation_addr = addr

    def store_conditional(self, addr):
        """Check and consume the reservation.
        Returns True if SC succeeds, False otherwise.
        """
        if (self.reservation_valid
                and self._block_addr(self.reservation_addr)
                    == self._block_addr(addr)):
            self.reservation_valid = False
            return True
        return False
