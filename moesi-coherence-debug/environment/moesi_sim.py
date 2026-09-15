#!/usr/bin/env python3
"""MOESI directory-based cache coherence protocol simulator.

Simulates a multi-core processor system with private L1 caches and a
directory-based coherence controller implementing the MOESI protocol.

Protocol states:
  L1 Cache: Modified (M), Owner (O), Exclusive (E), Shared (S), Invalid (I)
  Directory: Modified (M), Exclusive (E), Shared (S), Uncached (U)

Usage:
  python3 moesi_sim.py <trace_file> [--cores N] [--capacity N] [--verbose]

Trace format (one operation per line):
  <core_id> READ <hex_address>
  <core_id> WRITE <hex_address> <hex_data>
"""

from enum import IntEnum
import json
import sys




class CState(IntEnum):
    """Cache line states (MOESI)."""
    I = 0  # Invalid
    S = 1  # Shared
    E = 2  # Exclusive
    O = 3  # Owner
    M = 4  # Modified


class DState(IntEnum):
    """Directory entry states."""
    U = 0  # Uncached
    S = 1  # Shared (memory up-to-date)
    E = 2  # Exclusive (single clean copy, memory up-to-date)
    M = 3  # Modified (single dirty copy, memory stale)


class CacheEntry:
    __slots__ = ('state', 'addr', 'data', 'lru_ts')

    def __init__(self, state=CState.I, addr=-1, data=0):
        self.state = state
        self.addr = addr
        self.data = data
        self.lru_ts = 0


class DirEntry:
    __slots__ = ('state', 'owner', 'sharers')

    def __init__(self):
        self.state = DState.U
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


class MOESISimulator:
    """MOESI directory-based cache coherence protocol simulator."""

    BLOCK_BITS = 6  # 64-byte cache blocks

    def __init__(self, num_cores=4, l1_capacity=8):
        self.num_cores = num_cores
        self.caches = [L1Cache(l1_capacity, i) for i in range(num_cores)]
        self.directory = {}
        self.memory = {}
        self.verbose = False
        self.stats = dict(
            reads=0, writes=0, hits=0, misses=0,
            evictions=0, invalidations=0, writebacks=0, forwards=0,
        )

    def _baddr(self, addr):
        return (addr >> self.BLOCK_BITS) << self.BLOCK_BITS

    def _dir(self, baddr):
        if baddr not in self.directory:
            self.directory[baddr] = DirEntry()
        return self.directory[baddr]

    def _mem_rd(self, baddr):
        return self.memory.get(baddr, 0)

    def _mem_wr(self, baddr, data):
        self.memory[baddr] = data

    def _log(self, msg):
        if self.verbose:
            print(f"  [{msg}]", file=sys.stderr)

    # ---------------------------------------------------------------- #
    #                        Eviction logic                            #
    # ---------------------------------------------------------------- #

    def _do_eviction(self, core_id, new_baddr):
        """Evict LRU line from core's L1 if cache is full."""
        cache = self.caches[core_id]
        if new_baddr in cache.lines:
            return
        victim_addr = cache.find_victim()
        if victim_addr is None:
            return
        victim = cache.lines[victim_addr]
        self.stats['evictions'] += 1
        self._log(f"evict core={core_id} addr={victim_addr:#x} "
                  f"state={victim.state.name} data={victim.data:#x}")

        if victim.state == CState.M:
            self._dir_putm(core_id, victim_addr, victim.data)
        elif victim.state == CState.O:
            self._dir_puto(core_id, victim_addr, victim.data)
        elif victim.state == CState.E:
            self._dir_pute(core_id, victim_addr)
        elif victim.state == CState.S:
            self._dir_puts(core_id, victim_addr)

        del cache.lines[victim_addr]

    # ---------------------------------------------------------------- #
    #           Directory: writeback / release handlers                 #
    # ---------------------------------------------------------------- #

    def _dir_putm(self, core_id, baddr, data):
        """Handle PutM — eviction of a Modified line from L1."""
        d = self._dir(baddr)
        self.stats['writebacks'] += 1
        if d.state == DState.M and d.owner == core_id:
            self._mem_wr(baddr, data)
            d.state = DState.U
            d.owner = -1
        elif d.state == DState.E and d.owner == core_id:
            d.state = DState.U
            d.owner = -1

    def _dir_puto(self, core_id, baddr, data):
        """Handle PutO — eviction of an Owner line from L1."""
        d = self._dir(baddr)
        self._mem_wr(baddr, data)
        self.stats['writebacks'] += 1
        d.sharers.discard(core_id)
        d.state = DState.S if d.sharers else DState.U
        d.owner = -1

    def _dir_pute(self, core_id, baddr):
        """Handle PutE — release of an Exclusive line from L1."""
        d = self._dir(baddr)
        if d.state == DState.E and d.owner == core_id:
            d.state = DState.U
            d.owner = -1

    def _dir_puts(self, core_id, baddr):
        """Handle PutS — release of a Shared line from L1."""
        d = self._dir(baddr)
        if d.state == DState.S:
            d.sharers.discard(core_id)
            if not d.sharers:
                d.state = DState.U

    # ---------------------------------------------------------------- #
    #           Directory: coherence request handlers                  #
    # ---------------------------------------------------------------- #

    def _dir_gets(self, core_id, baddr):
        """Handle GetS (read request) from an L1 cache.

        Returns (data, new_cache_state) for the requesting core.
        """
        d = self._dir(baddr)

        if d.state == DState.U:
            data = self._mem_rd(baddr)
            d.state = DState.E
            d.owner = core_id
            d.sharers = set()
            return data, CState.E

        if d.state == DState.E:
            old = d.owner
            oe = self.caches[old].lookup(baddr)
            data = oe.data if oe else self._mem_rd(baddr)
            if oe:
                oe.state = CState.S
            self._mem_wr(baddr, data)
            d.state = DState.S
            d.owner = -1
            d.sharers = {core_id}
            return data, CState.S

        if d.state == DState.S:
            data = self._mem_rd(baddr)
            d.sharers.add(core_id)
            return data, CState.S

        if d.state == DState.M:
            old = d.owner
            oe = self.caches[old].lookup(baddr)
            self.stats['forwards'] += 1
            if oe:
                data = oe.data
                oe.state = CState.S
            else:
                data = self._mem_rd(baddr)
            self._mem_wr(baddr, data)
            d.state = DState.S
            d.owner = -1
            d.sharers = {old, core_id}
            return data, CState.S

        return self._mem_rd(baddr), CState.S

    def _dir_getm(self, core_id, baddr, upgrade=False):
        """Handle GetM (write / upgrade request) from an L1 cache.

        Returns the data value for the requesting core.
        """
        d = self._dir(baddr)

        if d.state == DState.U:
            data = self._mem_rd(baddr)
            d.state = DState.M
            d.owner = core_id
            d.sharers = set()
            return data

        if d.state == DState.E:
            old = d.owner
            if old != core_id:
                oe = self.caches[old].lookup(baddr)
                data = oe.data if oe else self._mem_rd(baddr)
                self.caches[old].evict(baddr)
                self.stats['invalidations'] += 1
            else:
                ent = self.caches[core_id].lookup(baddr)
                data = ent.data if ent else self._mem_rd(baddr)
            d.state = DState.M
            d.owner = core_id
            d.sharers = set()
            return data

        if d.state == DState.S:
            data = self._mem_rd(baddr)
            for sid in list(d.sharers - {core_id}):
                self.caches[sid].evict(baddr)
                self.stats['invalidations'] += 1
            d.state = DState.M
            d.owner = core_id
            d.sharers = set()
            return data

        if d.state == DState.M:
            old = d.owner
            if old != core_id:
                oe = self.caches[old].lookup(baddr)
                data = oe.data if oe else self._mem_rd(baddr)
                self.caches[old].evict(baddr)
                self.stats['invalidations'] += 1
                self.stats['forwards'] += 1
            else:
                ent = self.caches[core_id].lookup(baddr)
                data = ent.data if ent else self._mem_rd(baddr)
            d.state = DState.M
            d.owner = core_id
            d.sharers = set()
            return data

        return self._mem_rd(baddr)

    # ---------------------------------------------------------------- #
    #                         Public API                               #
    # ---------------------------------------------------------------- #

    def read(self, core_id, addr):
        """Process a read operation from the given core. Returns data."""
        baddr = self._baddr(addr)
        cache = self.caches[core_id]
        self.stats['reads'] += 1

        entry = cache.lookup(baddr)
        if entry is not None:
            self.stats['hits'] += 1
            self._log(f"core {core_id} READ {addr:#x} HIT "
                      f"state={entry.state.name} data={entry.data:#x}")
            return entry.data

        self.stats['misses'] += 1
        self._do_eviction(core_id, baddr)
        data, state = self._dir_gets(core_id, baddr)
        cache.install(baddr, state, data)
        self._log(f"core {core_id} READ {addr:#x} MISS "
                  f"state={state.name} data={data:#x}")
        return data

    def write(self, core_id, addr, data):
        """Process a write operation from the given core."""
        baddr = self._baddr(addr)
        cache = self.caches[core_id]
        self.stats['writes'] += 1

        entry = cache.lookup(baddr)
        if entry is not None:
            if entry.state == CState.M:
                self.stats['hits'] += 1
                entry.data = data
                self._log(f"core {core_id} WRITE {addr:#x}={data:#x} HIT M")
                return
            if entry.state == CState.E:
                self.stats['hits'] += 1
                entry.state = CState.M
                entry.data = data
                self._log(f"core {core_id} WRITE {addr:#x}={data:#x} "
                          f"HIT E->M silent")
                return
            if entry.state in (CState.S, CState.O):
                self.stats['hits'] += 1
                self._dir_getm(core_id, baddr, upgrade=True)
                entry.state = CState.M
                entry.data = data
                self._log(f"core {core_id} WRITE {addr:#x}={data:#x} "
                          f"upgrade {entry.state.name}->M")
                return

        self.stats['misses'] += 1
        self._do_eviction(core_id, baddr)
        self._dir_getm(core_id, baddr, upgrade=False)
        cache.install(baddr, CState.M, data)
        self._log(f"core {core_id} WRITE {addr:#x}={data:#x} MISS")

    def verify_coherence(self):
        """Check SWMR and data-value invariants across all caches."""
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
            if len(m_copies) > 1:
                violations.append(
                    f"Multiple Modified at {baddr:#x}: {m_copies}")
            if m_copies and len(copies) > 1:
                violations.append(
                    f"Modified coexists with others at {baddr:#x}: {copies}")
            if len(copies) > 1:
                vals = set(c[2] for c in copies)
                if len(vals) > 1:
                    violations.append(
                        f"Data value mismatch at {baddr:#x}: {copies}")

        return violations

    def dump_state(self):
        """Return full simulator state as a dict."""
        result = {
            'memory': {f'{k:#x}': v for k, v in sorted(self.memory.items())},
            'caches': {},
            'directory': {},
            'stats': self.stats,
        }
        for cid in range(self.num_cores):
            cs = {}
            for addr, e in sorted(self.caches[cid].lines.items()):
                if e.state != CState.I:
                    cs[f'{addr:#x}'] = {
                        'state': e.state.name, 'data': f'{e.data:#x}'}
            result['caches'][f'core_{cid}'] = cs
        for addr, d in sorted(self.directory.items()):
            result['directory'][f'{addr:#x}'] = {
                'state': d.state.name,
                'owner': d.owner,
                'sharers': sorted(d.sharers),
            }
        return result


def run_trace(sim, filename):
    """Parse and execute a memory trace file.

    Returns list of (op, core_id, addr, value) tuples.
    """
    results = []
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
                val = sim.read(core, addr)
                results.append(('READ', core, addr, val))
            elif op == 'WRITE':
                wdata = int(parts[3], 0)
                sim.write(core, addr, wdata)
                results.append(('WRITE', core, addr, wdata))
    return results


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(
        description='MOESI directory-based coherence simulator')
    parser.add_argument('trace', help='Trace file to execute')
    parser.add_argument('--cores', type=int, default=4,
                        help='Number of cores (default: 4)')
    parser.add_argument('--capacity', type=int, default=8,
                        help='L1 cache capacity in lines (default: 8)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Print detailed trace output')
    args = parser.parse_args()

    sim = MOESISimulator(num_cores=args.cores, l1_capacity=args.capacity)
    sim.verbose = args.verbose
    results = run_trace(sim, args.trace)

    print("Trace results:")
    for op, core, addr, val in results:
        if op == 'READ':
            print(f"  core {core} READ  {addr:#010x} => {val:#010x}")
        else:
            print(f"  core {core} WRITE {addr:#010x} <= {val:#010x}")

    print()
    violations = sim.verify_coherence()
    if violations:
        print("COHERENCE VIOLATIONS DETECTED:")
        for v in violations:
            print(f"  ! {v}")
    else:
        print("No coherence violations detected.")

    print(f"\nStats: {json.dumps(sim.stats, indent=2)}")
