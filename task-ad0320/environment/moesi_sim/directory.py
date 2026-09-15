"""Directory controller for coherence tracking.

Each directory bank is responsible for a subset of the address space
(determined by the bank interleaver).  It tracks which caches hold
copies of each block and in what state.
"""


import math
from .types import CacheState, DirState, DirEntry


class DirectoryController:
    """A single directory bank managing coherence state for its blocks."""

    def __init__(self, bank_id, memory, block_size=64):
        self.bank_id = bank_id
        self.block_bits = int(math.log2(block_size))
        self.entries = {}          # block_addr -> DirEntry
        self.memory = memory       # shared reference to main memory dict
        self.stats = {"gets": 0, "getm": 0, "puts": 0, "putm": 0, "upgrade": 0}

    def get_entry(self, block_addr):
        """Lazily create a directory entry, seeded from memory."""
        if block_addr not in self.entries:
            data = self.memory.get(block_addr, 0)
            self.entries[block_addr] = DirEntry(data=data)
        return self.entries[block_addr]

    # ------------------------------------------------------------------
    # Request handlers
    # ------------------------------------------------------------------

    def handle_gets(self, block_addr, requestor):
        """Process a read (GetS) request.

        Returns (data | None, cache_state_for_requestor, actions).
        *data* is None when the value must come from a forwarding action.
        """
        self.stats["gets"] += 1
        entry = self.get_entry(block_addr)
        actions = []

        if entry.state == DirState.UNCACHED:
            # No cached copies -- supply data, give Exclusive
            entry.state = DirState.EXCLUSIVE_MODIFIED
            entry.owner = requestor
            return entry.data, CacheState.EXCLUSIVE, actions

        elif entry.state == DirState.SHARED:
            # Already shared -- just add another sharer
            entry.sharers.add(requestor)
            return entry.data, CacheState.SHARED, actions

        elif entry.state == DirState.EXCLUSIVE_MODIFIED:
            # Must forward from current owner
            old_owner = entry.owner
            actions.append(("fwd_gets", old_owner, block_addr))
            # Transition to Shared
            entry.state = DirState.SHARED
            entry.sharers.add(requestor)
            entry.owner = -1
            return None, CacheState.SHARED, actions

    def handle_getm(self, block_addr, requestor):
        """Process a write / upgrade (GetM) request.

        Returns (data | None, inv_targets, actions).
        """
        self.stats["getm"] += 1
        entry = self.get_entry(block_addr)
        actions = []
        inv_targets = set()

        if entry.state == DirState.UNCACHED:
            entry.state = DirState.EXCLUSIVE_MODIFIED
            entry.owner = requestor
            return entry.data, inv_targets, actions

        elif entry.state == DirState.SHARED:
            # Invalidate all other sharers
            inv_targets = entry.sharers - {requestor}
            for sharer in inv_targets:
                actions.append(("inv", sharer, block_addr))
            entry.state = DirState.EXCLUSIVE_MODIFIED
            entry.owner = requestor
            entry.sharers.clear()
            return entry.data, inv_targets, actions

        elif entry.state == DirState.EXCLUSIVE_MODIFIED:
            old_owner = entry.owner
            if old_owner == requestor:
                # Already owner -- nothing to do
                return entry.data, inv_targets, actions
            # Forward GetM to current owner
            actions.append(("fwd_getm", old_owner, block_addr))
            inv_targets = {old_owner}
            entry.owner = requestor
            return None, inv_targets, actions

    # ------------------------------------------------------------------
    # Writeback / eviction handlers
    # ------------------------------------------------------------------

    def handle_putm(self, block_addr, requestor, data):
        """Handle writeback of a Modified line (PutM)."""
        self.stats["putm"] += 1
        entry = self.get_entry(block_addr)
        if (entry.state == DirState.EXCLUSIVE_MODIFIED
                and entry.owner == requestor):
            entry.data = data
            self.memory[block_addr] = data
            entry.state = DirState.UNCACHED
            entry.owner = -1

    def handle_puts(self, block_addr, requestor):
        """Handle eviction of a Shared or Exclusive-clean line (PutS)."""
        self.stats["puts"] += 1
        entry = self.get_entry(block_addr)
        if entry.state == DirState.SHARED:
            entry.sharers.discard(requestor)
            if not entry.sharers:
                entry.state = DirState.UNCACHED
        elif (entry.state == DirState.EXCLUSIVE_MODIFIED
              and entry.owner == requestor):
            # Clean exclusive eviction
            entry.state = DirState.UNCACHED
            entry.owner = -1

    def handle_puto(self, block_addr, requestor, data):
        """Handle eviction of an Owned line (PutO) -- writes back dirty data."""
        entry = self.get_entry(block_addr)
        if entry.state == DirState.SHARED:
            entry.data = data
            self.memory[block_addr] = data
            entry.sharers.discard(requestor)
            if not entry.sharers:
                entry.state = DirState.UNCACHED
