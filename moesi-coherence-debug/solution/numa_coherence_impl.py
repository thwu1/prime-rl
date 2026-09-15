#!/usr/bin/env python3
"""NUMA-aware MOESI cache coherence protocol simulator.


Extends the base MOESI protocol with:
- NUMA topology awareness (multi-chiplet with block-interleaved home assignment)
- Cycle-accurate cost model (local vs. remote latency)
- Owner state optimization (M→O on reads to avoid memory writeback)
- Per-chiplet shared cache (reduces cross-chiplet traffic for repeated remote reads)
"""

from enum import IntEnum
import json
import sys


class CState(IntEnum):
    """Cache line states (MOESI)."""
    I = 0
    S = 1
    E = 2
    O = 3
    M = 4


class NDState(IntEnum):
    """NUMA directory entry states (extended with Owner)."""
    U = 0  # Uncached
    S = 1  # Shared (memory up-to-date)
    E = 2  # Exclusive (single clean copy)
    O = 3  # Owner (one dirty owner + shared copies, memory stale)
    M = 4  # Modified (single dirty copy, memory stale)


class CacheEntry:
    __slots__ = ('state', 'addr', 'data', 'lru_ts')

    def __init__(self, state=CState.I, addr=-1, data=0):
        self.state = state
        self.addr = addr
        self.data = data
        self.lru_ts = 0


class NDirEntry:
    __slots__ = ('state', 'owner', 'sharers')

    def __init__(self):
        self.state = NDState.U
        self.owner = -1
        self.sharers = set()


class L1Cache:
    """Fully-associative L1 cache with LRU replacement."""

    def __init__(self, capacity, core_id):
        self.capacity = capacity
        self.core_id = core_id
        self.lines = {}
        self._ts = 0

    def _tick(self):
        self._ts += 1
        return self._ts

    def lookup(self, baddr):
        e = self.lines.get(baddr)
        if e is not None and e.state != CState.I:
            e.lru_ts = self._tick()
            return e
        return None

    def find_victim(self):
        if len(self.lines) < self.capacity:
            return None
        return min(self.lines, key=lambda a: self.lines[a].lru_ts)

    def install(self, baddr, state, data):
        e = CacheEntry(state, baddr, data)
        e.lru_ts = self._tick()
        self.lines[baddr] = e
        return e

    def evict(self, baddr):
        e = self.lines.pop(baddr, None)
        if e is not None:
            return e.state, e.data
        return CState.I, 0


class ChipletCache:
    """Per-chiplet shared cache for remotely-fetched data."""

    def __init__(self, capacity):
        self.capacity = capacity
        self.entries = {}
        self._ts = 0
        self._lru = {}

    def lookup(self, baddr):
        if baddr in self.entries:
            self._ts += 1
            self._lru[baddr] = self._ts
            return self.entries[baddr]
        return None

    def install(self, baddr, data):
        if len(self.entries) >= self.capacity and baddr not in self.entries:
            victim = min(self._lru, key=self._lru.get)
            del self.entries[victim]
            del self._lru[victim]
        self.entries[baddr] = data
        self._ts += 1
        self._lru[baddr] = self._ts

    def invalidate(self, baddr):
        self.entries.pop(baddr, None)
        self._lru.pop(baddr, None)


class NUMACoherenceSimulator:
    """NUMA-aware MOESI directory-based cache coherence simulator."""

    BLOCK_BITS = 6

    def __init__(self, num_cores=8, l1_capacity=8, cores_per_chiplet=4,
                 enable_owner_opt=True, enable_chiplet_cache=True,
                 chiplet_cache_capacity=16):
        self.num_cores = num_cores
        self.cores_per_chiplet = cores_per_chiplet
        self.num_chiplets = num_cores // cores_per_chiplet
        self.enable_owner_opt = enable_owner_opt
        self.enable_chiplet_cache = enable_chiplet_cache

        self.caches = [L1Cache(l1_capacity, i) for i in range(num_cores)]
        self.directory = {}
        self.memory = {}

        if enable_chiplet_cache:
            self.chiplet_caches = [
                ChipletCache(chiplet_cache_capacity)
                for _ in range(self.num_chiplets)
            ]
        else:
            self.chiplet_caches = None

        self.cost = {
            'hit': 1, 'local_miss': 10, 'remote_miss': 50,
            'chiplet_cache_hit': 8, 'writeback': 100,
            'local_inv': 5, 'remote_inv': 25,
        }

        self.stats = {
            'reads': 0, 'writes': 0, 'hits': 0, 'misses': 0,
            'total_cycles': 0, 'inter_chiplet_messages': 0,
            'memory_writebacks': 0, 'invalidations': 0,
            'chiplet_cache_hits': 0, 'owner_transitions': 0,
            'evictions': 0, 'forwards': 0,
        }

    # ---- topology helpers ----

    def _baddr(self, addr):
        return (addr >> self.BLOCK_BITS) << self.BLOCK_BITS

    def _core_chiplet(self, core_id):
        return core_id // self.cores_per_chiplet

    def _home_chiplet(self, baddr):
        return (baddr >> self.BLOCK_BITS) % self.num_chiplets

    def _is_local(self, core_id, baddr):
        return self._core_chiplet(core_id) == self._home_chiplet(baddr)

    # ---- directory / memory ----

    def _dir(self, baddr):
        if baddr not in self.directory:
            self.directory[baddr] = NDirEntry()
        return self.directory[baddr]

    def _mem_rd(self, baddr):
        return self.memory.get(baddr, 0)

    def _mem_wr(self, baddr, data):
        self.memory[baddr] = data

    # ---- cost tracking ----

    def _add_miss_cost(self, core_id, baddr):
        if self._is_local(core_id, baddr):
            self.stats['total_cycles'] += self.cost['local_miss']
        else:
            self.stats['total_cycles'] += self.cost['remote_miss']
            self.stats['inter_chiplet_messages'] += 1

    def _add_inv_cost(self, baddr, target_core_id):
        home_chip = self._home_chiplet(baddr)
        target_chip = self._core_chiplet(target_core_id)
        if home_chip == target_chip:
            self.stats['total_cycles'] += self.cost['local_inv']
        else:
            self.stats['total_cycles'] += self.cost['remote_inv']
            self.stats['inter_chiplet_messages'] += 1

    def _add_writeback_cost(self, baddr, data):
        self._mem_wr(baddr, data)
        self.stats['memory_writebacks'] += 1
        self.stats['total_cycles'] += self.cost['writeback']

    def _invalidate_chiplet_caches(self, baddr):
        if self.chiplet_caches:
            for cc in self.chiplet_caches:
                cc.invalidate(baddr)

    # ---- eviction ----

    def _do_eviction(self, core_id, new_baddr):
        cache = self.caches[core_id]
        if new_baddr in cache.lines:
            return
        victim_addr = cache.find_victim()
        if victim_addr is None:
            return
        victim = cache.lines[victim_addr]
        self.stats['evictions'] += 1

        if victim.state == CState.M:
            self._dir_putm(core_id, victim_addr, victim.data)
        elif victim.state == CState.O:
            self._dir_puto(core_id, victim_addr, victim.data)
        elif victim.state == CState.E:
            self._dir_pute(core_id, victim_addr)
        elif victim.state == CState.S:
            self._dir_puts(core_id, victim_addr)

        del cache.lines[victim_addr]

    # ---- directory: writeback / release handlers ----

    def _dir_putm(self, core_id, baddr, data):
        d = self._dir(baddr)
        if d.state == NDState.M and d.owner == core_id:
            self._add_writeback_cost(baddr, data)
            d.state = NDState.U
            d.owner = -1
        elif d.state == NDState.E and d.owner == core_id:
            # Silent E→M means data may be dirty
            self._add_writeback_cost(baddr, data)
            d.state = NDState.U
            d.owner = -1

    def _dir_puto(self, core_id, baddr, data):
        d = self._dir(baddr)
        self._add_writeback_cost(baddr, data)
        if d.owner == core_id:
            d.owner = -1
        d.state = NDState.S if d.sharers else NDState.U

    def _dir_pute(self, core_id, baddr):
        d = self._dir(baddr)
        if d.state == NDState.E and d.owner == core_id:
            d.state = NDState.U
            d.owner = -1

    def _dir_puts(self, core_id, baddr):
        d = self._dir(baddr)
        if d.state in (NDState.S, NDState.O):
            d.sharers.discard(core_id)
            if d.state == NDState.S and not d.sharers:
                d.state = NDState.U

    # ---- directory: coherence request handlers ----

    def _dir_gets(self, core_id, baddr):
        """Handle GetS (read). Returns (data, cache_state)."""
        d = self._dir(baddr)

        if d.state == NDState.U:
            data = self._mem_rd(baddr)
            d.state = NDState.E
            d.owner = core_id
            d.sharers = set()
            return data, CState.E

        if d.state == NDState.E:
            old = d.owner
            oe = self.caches[old].lookup(baddr)
            data = oe.data if oe else self._mem_rd(baddr)
            if oe:
                oe.state = CState.S
            self._mem_wr(baddr, data)
            d.state = NDState.S
            d.owner = -1
            d.sharers = {old, core_id}
            self.stats['forwards'] += 1
            return data, CState.S

        if d.state == NDState.S:
            data = self._mem_rd(baddr)
            d.sharers.add(core_id)
            return data, CState.S

        if d.state == NDState.M:
            old = d.owner
            oe = self.caches[old].lookup(baddr)
            self.stats['forwards'] += 1
            data = oe.data if oe else self._mem_rd(baddr)

            if self.enable_owner_opt:
                # M → O: owner keeps dirty copy, no writeback
                if oe:
                    oe.state = CState.O
                d.state = NDState.O
                d.sharers = {core_id}
                # d.owner stays the same
                self.stats['owner_transitions'] += 1
            else:
                # M → S: writeback to memory
                if oe:
                    oe.state = CState.S
                self._add_writeback_cost(baddr, data)
                d.state = NDState.S
                d.owner = -1
                d.sharers = {old, core_id}

            return data, CState.S

        if d.state == NDState.O:
            # Owner has dirty data; forward from owner
            old = d.owner
            oe = self.caches[old].lookup(baddr)
            data = oe.data if oe else self._mem_rd(baddr)
            d.sharers.add(core_id)
            self.stats['forwards'] += 1
            return data, CState.S

        return self._mem_rd(baddr), CState.S

    def _dir_getm(self, core_id, baddr):
        """Handle GetM (write/upgrade). Returns data."""
        d = self._dir(baddr)

        if d.state == NDState.U:
            data = self._mem_rd(baddr)
            d.state = NDState.M
            d.owner = core_id
            d.sharers = set()
            return data

        if d.state == NDState.E:
            old = d.owner
            if old != core_id:
                oe = self.caches[old].lookup(baddr)
                data = oe.data if oe else self._mem_rd(baddr)
                self.caches[old].evict(baddr)
                self.stats['invalidations'] += 1
                self._add_inv_cost(baddr, old)
            else:
                ent = self.caches[core_id].lookup(baddr)
                data = ent.data if ent else self._mem_rd(baddr)
            d.state = NDState.M
            d.owner = core_id
            d.sharers = set()
            self._invalidate_chiplet_caches(baddr)
            return data

        if d.state == NDState.S:
            data = self._mem_rd(baddr)
            for sid in list(d.sharers - {core_id}):
                self.caches[sid].evict(baddr)
                self.stats['invalidations'] += 1
                self._add_inv_cost(baddr, sid)
            d.state = NDState.M
            d.owner = core_id
            d.sharers = set()
            self._invalidate_chiplet_caches(baddr)
            return data

        if d.state == NDState.M:
            old = d.owner
            if old != core_id:
                oe = self.caches[old].lookup(baddr)
                data = oe.data if oe else self._mem_rd(baddr)
                self.caches[old].evict(baddr)
                self.stats['invalidations'] += 1
                self._add_inv_cost(baddr, old)
                self.stats['forwards'] += 1
            else:
                ent = self.caches[core_id].lookup(baddr)
                data = ent.data if ent else self._mem_rd(baddr)
            d.state = NDState.M
            d.owner = core_id
            d.sharers = set()
            self._invalidate_chiplet_caches(baddr)
            return data

        if d.state == NDState.O:
            old = d.owner
            oe = self.caches[old].lookup(baddr)
            data = oe.data if oe else self._mem_rd(baddr)
            # Invalidate owner (if not requester)
            if old != core_id:
                self.caches[old].evict(baddr)
                self.stats['invalidations'] += 1
                self._add_inv_cost(baddr, old)
            # Invalidate all sharers (except requester)
            for sid in list(d.sharers - {core_id}):
                self.caches[sid].evict(baddr)
                self.stats['invalidations'] += 1
                self._add_inv_cost(baddr, sid)
            d.state = NDState.M
            d.owner = core_id
            d.sharers = set()
            self._invalidate_chiplet_caches(baddr)
            self.stats['forwards'] += 1
            return data

        return self._mem_rd(baddr)

    # ---- public API ----

    def read(self, core_id, addr):
        """Process a read. Returns data value."""
        baddr = self._baddr(addr)
        cache = self.caches[core_id]
        self.stats['reads'] += 1

        # L1 hit
        entry = cache.lookup(baddr)
        if entry is not None:
            self.stats['hits'] += 1
            self.stats['total_cycles'] += self.cost['hit']
            return entry.data

        self.stats['misses'] += 1

        # Check chiplet cache (remote addresses only)
        if (self.enable_chiplet_cache and self.chiplet_caches
                and not self._is_local(core_id, baddr)):
            chip = self._core_chiplet(core_id)
            cc_data = self.chiplet_caches[chip].lookup(baddr)
            if cc_data is not None:
                self.stats['chiplet_cache_hits'] += 1
                self.stats['total_cycles'] += self.cost['chiplet_cache_hit']
                self._do_eviction(core_id, baddr)
                # Register as sharer in directory
                d = self._dir(baddr)
                if d.state in (NDState.S, NDState.O):
                    d.sharers.add(core_id)
                cache.install(baddr, CState.S, cc_data)
                return cc_data

        # Full miss path
        self._do_eviction(core_id, baddr)
        self._add_miss_cost(core_id, baddr)
        data, state = self._dir_gets(core_id, baddr)
        cache.install(baddr, state, data)

        # Populate chiplet cache for remote data
        if (self.enable_chiplet_cache and self.chiplet_caches
                and not self._is_local(core_id, baddr)):
            chip = self._core_chiplet(core_id)
            self.chiplet_caches[chip].install(baddr, data)

        return data

    def write(self, core_id, addr, data):
        """Process a write."""
        baddr = self._baddr(addr)
        cache = self.caches[core_id]
        self.stats['writes'] += 1

        entry = cache.lookup(baddr)
        if entry is not None:
            if entry.state == CState.M:
                self.stats['hits'] += 1
                self.stats['total_cycles'] += self.cost['hit']
                entry.data = data
                return
            if entry.state == CState.E:
                self.stats['hits'] += 1
                self.stats['total_cycles'] += self.cost['hit']
                entry.state = CState.M
                entry.data = data
                return
            if entry.state in (CState.S, CState.O):
                self.stats['hits'] += 1
                self._add_miss_cost(core_id, baddr)
                self._dir_getm(core_id, baddr)
                entry.state = CState.M
                entry.data = data
                self._invalidate_chiplet_caches(baddr)
                return

        self.stats['misses'] += 1
        self._do_eviction(core_id, baddr)
        self._add_miss_cost(core_id, baddr)
        self._dir_getm(core_id, baddr)
        cache.install(baddr, CState.M, data)
        self._invalidate_chiplet_caches(baddr)

    def verify_coherence(self):
        """Check SWMR and data-value invariants."""
        violations = []
        all_addrs = set()
        for c in self.caches:
            for addr, e in c.lines.items():
                if e.state != CState.I:
                    all_addrs.add(addr)

        for baddr in all_addrs:
            copies = []
            for cid in range(self.num_cores):
                e = self.caches[cid].lines.get(baddr)
                if e is not None and e.state != CState.I:
                    copies.append((cid, e.state, e.data))

            m_copies = [c for c in copies if c[1] == CState.M]
            o_copies = [c for c in copies if c[1] == CState.O]

            if len(m_copies) > 1:
                violations.append(
                    f"Multiple M at {baddr:#x}: {m_copies}")
            if len(o_copies) > 1:
                violations.append(
                    f"Multiple O at {baddr:#x}: {o_copies}")
            if m_copies and len(copies) > 1:
                violations.append(
                    f"M coexists with others at {baddr:#x}: {copies}")
            if len(copies) > 1:
                vals = set(c[2] for c in copies)
                if len(vals) > 1:
                    violations.append(
                        f"Data mismatch at {baddr:#x}: {copies}")

        return violations


def parse_trace(filename):
    """Parse a trace file into operations."""
    ops = []
    with open(filename) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            core = int(parts[0])
            op = parts[1].upper()
            addr = int(parts[2], 0)
            if op == 'READ':
                ops.append(('READ', core, addr, None))
            elif op == 'WRITE':
                wdata = int(parts[3], 0)
                ops.append(('WRITE', core, addr, wdata))
    return ops


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(
        description='NUMA-aware MOESI coherence simulator')
    parser.add_argument('trace', help='Trace file to execute')
    parser.add_argument('--cores', type=int, default=8)
    parser.add_argument('--capacity', type=int, default=8)
    parser.add_argument('--cores-per-chiplet', type=int, default=4)
    parser.add_argument('--no-owner-opt', action='store_true')
    parser.add_argument('--no-chiplet-cache', action='store_true')
    parser.add_argument('--chiplet-cache-capacity', type=int, default=16)
    parser.add_argument('--json-stats', action='store_true')
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

    sim = NUMACoherenceSimulator(
        num_cores=args.cores,
        l1_capacity=args.capacity,
        cores_per_chiplet=args.cores_per_chiplet,
        enable_owner_opt=not args.no_owner_opt,
        enable_chiplet_cache=not args.no_chiplet_cache,
        chiplet_cache_capacity=args.chiplet_cache_capacity,
    )

    ops = parse_trace(args.trace)
    results = []
    for op, core, addr, data in ops:
        if op == 'READ':
            val = sim.read(core, addr)
            results.append(('READ', core, addr, val))
        else:
            sim.write(core, addr, data)
            results.append(('WRITE', core, addr, data))

    if args.json_stats:
        print(json.dumps(sim.stats))
    else:
        for op, core, addr, val in results:
            if op == 'READ':
                print(f"  core {core} READ  {addr:#010x} => {val:#010x}")
            else:
                print(f"  core {core} WRITE {addr:#010x} <= {val:#010x}")

        violations = sim.verify_coherence()
        if violations:
            print("COHERENCE VIOLATIONS DETECTED:")
            for v in violations:
                print(f"  ! {v}")
        else:
            print("No coherence violations detected.")
        print(f"\nStats: {json.dumps(sim.stats, indent=2)}")
