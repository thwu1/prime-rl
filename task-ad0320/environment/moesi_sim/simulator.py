"""MOESI coherence protocol simulator.

Models a multi-core system with private L1 caches, banked directory
controllers, and main memory.  All operations are processed
atomically in trace order (no out-of-order or speculative execution).
"""


import math
from .types import CacheState
from .cache import L1Cache
from .directory import DirectoryController
from .bank import BankInterleaver


class MOESISimulator:
    """Trace-driven MOESI coherence simulator."""

    def __init__(self, num_cores=4, num_banks=4, block_size=64,
                 cache_sets=64, cache_assoc=4):
        self.num_cores = num_cores
        self.num_banks = num_banks
        self.block_size = block_size
        self.block_bits = int(math.log2(block_size))
        self.memory = {}  # block_addr -> data

        self.interleaver = BankInterleaver(num_banks, block_size)
        self.caches = [L1Cache(i, cache_sets, cache_assoc, block_size)
                       for i in range(num_cores)]
        self.directories = [DirectoryController(i, self.memory, block_size)
                            for i in range(num_banks)]

        self.stats = {
            "loads": 0, "stores": 0,
            "lr": 0, "sc": 0, "sc_fail": 0,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_dir(self, addr):
        bank = self.interleaver.get_bank(addr)
        return self.directories[bank]

    def _block_addr(self, addr):
        return addr >> self.block_bits

    def _evict(self, core_id, evict_addr, evict_line):
        """Write back / notify directory about an evicted line."""
        if evict_line is None:
            return
        block_addr = self._block_addr(evict_addr)
        dir_ctrl = self._get_dir(evict_addr)
        if evict_line.state == CacheState.MODIFIED:
            dir_ctrl.handle_putm(block_addr, core_id, evict_line.data)
        elif evict_line.state == CacheState.OWNED:
            dir_ctrl.handle_puto(block_addr, core_id, evict_line.data)
        elif evict_line.state in (CacheState.SHARED, CacheState.EXCLUSIVE):
            dir_ctrl.handle_puts(block_addr, core_id)

    # ------------------------------------------------------------------
    # Public API: memory operations
    # ------------------------------------------------------------------

    def load(self, core_id, addr):
        """Execute a load and return the data value."""
        self.stats["loads"] += 1
        cache = self.caches[core_id]
        block_addr = self._block_addr(addr)

        # L1 hit?
        line, way = cache.lookup(addr)
        if line is not None and line.state != CacheState.INVALID:
            cache.touch_lru(cache._set_index(addr), way)
            return line.data

        # Cache miss -- ask directory
        dir_ctrl = self._get_dir(addr)
        data, state, actions = dir_ctrl.handle_gets(block_addr, core_id)

        # Process forwarding
        for action_type, target, target_block in actions:
            if action_type == "fwd_gets":
                target_cache = self.caches[target]
                fwd_addr = target_block << self.block_bits
                target_line, _ = target_cache.lookup(fwd_addr)
                if target_line is not None:
                    data = target_line.data
                    # Mirror data into directory for future SHARED reads
                    dir_ctrl.get_entry(block_addr).data = data
                    # Owner state transition: M->O or E->S
                    if target_line.state == CacheState.MODIFIED:
                        target_line.state = CacheState.OWNED
                    elif target_line.state == CacheState.EXCLUSIVE:
                        target_line.state = CacheState.SHARED

        if data is None:
            data = self.memory.get(block_addr, 0)

        # Install (may evict)
        evict_line, evict_addr = cache.install(addr, data, state)
        if evict_addr is not None:
            self._evict(core_id, evict_addr, evict_line)

        return data

    def store(self, core_id, addr, data):
        """Execute a store."""
        self.stats["stores"] += 1
        cache = self.caches[core_id]
        block_addr = self._block_addr(addr)

        line, way = cache.lookup(addr)

        # Silent upgrade: already Modified
        if line is not None and line.state == CacheState.MODIFIED:
            line.data = data
            cache.touch_lru(cache._set_index(addr), way)
            return

        # Silent upgrade: Exclusive -> Modified
        if line is not None and line.state == CacheState.EXCLUSIVE:
            line.state = CacheState.MODIFIED
            line.data = data
            cache.touch_lru(cache._set_index(addr), way)
            return

        # Need exclusive ownership from directory
        dir_ctrl = self._get_dir(addr)
        _, inv_targets, actions = dir_ctrl.handle_getm(block_addr, core_id)

        for action_type, target, target_block in actions:
            fwd_addr = target_block << self.block_bits
            if action_type == "fwd_getm":
                target_cache = self.caches[target]
                target_line, _ = target_cache.lookup(fwd_addr)
                if target_line is not None:
                    target_cache.invalidate(fwd_addr)
            elif action_type == "inv":
                target_cache = self.caches[target]
                target_cache.invalidate(fwd_addr)

        if line is not None:
            # Upgrade from Shared / Owned -> Modified
            line.state = CacheState.MODIFIED
            line.data = data
            cache.touch_lru(cache._set_index(addr), way)
        else:
            # Miss: install new line
            evict_line, evict_addr = cache.install(
                addr, data, CacheState.MODIFIED)
            if evict_addr is not None:
                self._evict(core_id, evict_addr, evict_line)

    def load_reserved(self, core_id, addr):
        """Execute a Load-Reserved (LR) instruction."""
        self.stats["lr"] += 1
        value = self.load(core_id, addr)
        self.caches[core_id].load_reserved(addr)
        return value

    def store_conditional(self, core_id, addr, data):
        """Execute a Store-Conditional (SC).  Returns True on success."""
        self.stats["sc"] += 1
        cache = self.caches[core_id]
        if cache.store_conditional(addr):
            self.store(core_id, addr, data)
            return True
        self.stats["sc_fail"] += 1
        return False

    # ------------------------------------------------------------------
    # Trace execution
    # ------------------------------------------------------------------

    def execute_trace(self, trace):
        """Execute a list of memory operations.

        Each op: {"core": int, "op": str, "addr": int[, "data": int]}
        """
        results = []
        for op in trace:
            core = op["core"]
            addr = op["addr"]
            if op["op"] == "load":
                val = self.load(core, addr)
                results.append({"op": "load", "core": core,
                                "addr": addr, "value": val})
            elif op["op"] == "store":
                self.store(core, addr, op["data"])
                results.append({"op": "store", "core": core, "addr": addr})
            elif op["op"] == "lr":
                val = self.load_reserved(core, addr)
                results.append({"op": "lr", "core": core,
                                "addr": addr, "value": val})
            elif op["op"] == "sc":
                ok = self.store_conditional(core, addr, op["data"])
                results.append({"op": "sc", "core": core,
                                "addr": addr, "success": ok})
        return results

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def get_bank_stats(self):
        """Per-bank request counts."""
        return {i: dict(d.stats) for i, d in enumerate(self.directories)}

    def get_memory_state(self):
        """Flush all dirty lines and return memory contents."""
        for core_id, cache in enumerate(self.caches):
            for si in range(cache.num_sets):
                for line in cache.sets[si]:
                    if line.state in (CacheState.MODIFIED, CacheState.OWNED):
                        ba = line.tag * cache.num_sets + si
                        self.memory[ba] = line.data
        return dict(self.memory)
