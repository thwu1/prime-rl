#!/usr/bin/env python3

"""MESI cache coherence protocol simulator.

Implements a snoopy-bus MESI protocol for multi-core systems with private
write-back, write-allocate L1 caches and LRU replacement.
"""

import json
import math
import sys


class CacheLine:
    __slots__ = ('tag', 'state')

    def __init__(self):
        self.tag = None
        self.state = 'I'


class CacheSet:
    def __init__(self, num_ways):
        self.lines = [CacheLine() for _ in range(num_ways)]
        self.lru_order = list(range(num_ways))

    def find(self, tag):
        """Return way index of valid line with matching tag, or -1."""
        for i, line in enumerate(self.lines):
            if line.tag == tag and line.state != 'I':
                return i
        return -1

    def get_victim(self):
        """Select replacement victim: prefer lowest-index Invalid way, else LRU."""
        for i in range(len(self.lines)):
            if self.lines[i].state == 'I':
                return i
        return self.lru_order[-1]

    def touch(self, way):
        """Move way to MRU position in LRU ordering."""
        if way in self.lru_order:
            self.lru_order.remove(way)
        self.lru_order.insert(0, way)


class L1Cache:
    def __init__(self, size_bytes, associativity, line_size):
        self.size_bytes = size_bytes
        self.associativity = associativity
        self.line_size = line_size
        self.num_sets = size_bytes // (associativity * line_size)
        self.sets = [CacheSet(associativity) for _ in range(self.num_sets)]
        self.offset_bits = int(math.log2(line_size))
        self.index_bits = int(math.log2(self.num_sets))

        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.writebacks = 0
        self.invalidations_received = 0
        self.upgrades = 0

    def get_set_index(self, addr):
        return (addr >> self.offset_bits) & ((1 << self.index_bits) - 1)

    def get_tag(self, addr):
        return addr >> (self.offset_bits + self.index_bits)


class MESISimulator:
    def __init__(self, num_cores, cache_size, associativity, line_size):
        self.num_cores = num_cores
        self.cache_size = cache_size
        self.associativity = associativity
        self.line_size = line_size
        self.caches = [L1Cache(cache_size, associativity, line_size)
                       for _ in range(num_cores)]
        self.bus_transactions = 0
        self.total_invalidations = 0
        self.memory_reads = 0
        self.memory_writes = 0

    def _snoop_for_read(self, req_core, addr):
        """Handle BusRd snooping: E->S, M->S (with flush). Return (found, was_modified)."""
        found = False
        was_modified = False
        for i, cache in enumerate(self.caches):
            if i == req_core:
                continue
            si = cache.get_set_index(addr)
            tg = cache.get_tag(addr)
            way = cache.sets[si].find(tg)
            if way >= 0:
                line = cache.sets[si].lines[way]
                found = True
                if line.state == 'M':
                    was_modified = True
                    self.memory_writes += 1
                    cache.writebacks += 1
                    line.state = 'S'
                elif line.state == 'E':
                    line.state = 'S'
                # S stays S
        return found, was_modified

    def _snoop_for_write(self, req_core, addr):
        """Handle BusRdX snooping: all valid->I (M flushes first). Return (found, was_modified)."""
        found = False
        was_modified = False
        for i, cache in enumerate(self.caches):
            if i == req_core:
                continue
            si = cache.get_set_index(addr)
            tg = cache.get_tag(addr)
            way = cache.sets[si].find(tg)
            if way >= 0:
                line = cache.sets[si].lines[way]
                found = True
                if line.state == 'M':
                    was_modified = True
                    self.memory_writes += 1
                    cache.writebacks += 1
                line.state = 'I'
                cache.invalidations_received += 1
                self.total_invalidations += 1
        return found, was_modified

    def _invalidate_sharers(self, req_core, addr):
        """Handle BusUpgr: invalidate all other sharers."""
        for i, cache in enumerate(self.caches):
            if i == req_core:
                continue
            si = cache.get_set_index(addr)
            tg = cache.get_tag(addr)
            way = cache.sets[si].find(tg)
            if way >= 0:
                cache.sets[si].lines[way].state = 'I'
                cache.invalidations_received += 1
                self.total_invalidations += 1

    def access(self, core_id, is_write, addr):
        cache = self.caches[core_id]
        si = cache.get_set_index(addr)
        tg = cache.get_tag(addr)
        cset = cache.sets[si]
        way = cset.find(tg)

        if way >= 0:
            # === HIT ===
            line = cset.lines[way]
            cache.hits += 1

            if is_write:
                if line.state == 'S':
                    # BusUpgr
                    self.bus_transactions += 1
                    cache.upgrades += 1
                    self._invalidate_sharers(core_id, addr)
                    line.state = 'M'
                elif line.state == 'E':
                    # Silent upgrade
                    line.state = 'M'
                # M->M: nothing

            cset.touch(way)
        else:
            # === MISS ===
            cache.misses += 1
            self.bus_transactions += 1

            # Select victim
            victim_way = cset.get_victim()
            victim = cset.lines[victim_way]

            # Eviction handling
            if victim.state != 'I':
                cache.evictions += 1
                if victim.state == 'M':
                    cache.writebacks += 1
                    self.memory_writes += 1

            # Snoop other caches
            if is_write:
                found, was_modified = self._snoop_for_write(core_id, addr)
            else:
                found, was_modified = self._snoop_for_read(core_id, addr)

            # Memory read unless data supplied via M-line flush
            if not was_modified:
                self.memory_reads += 1

            # Place line
            victim.tag = tg
            if is_write:
                victim.state = 'M'
            elif found:
                victim.state = 'S'
            else:
                victim.state = 'E'

            cset.touch(victim_way)

    def run_trace(self, trace_path):
        with open(trace_path) as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line or raw_line.startswith('#'):
                    continue
                parts = raw_line.split()
                core_id = int(parts[0])
                is_write = parts[1] == 'W'
                addr = int(parts[2], 16)
                self.access(core_id, is_write, addr)

    def get_stats(self):
        total_hits = sum(c.hits for c in self.caches)
        total_misses = sum(c.misses for c in self.caches)
        total = total_hits + total_misses

        stats = {
            "config": {
                "num_cores": self.num_cores,
                "cache_size": self.cache_size,
                "associativity": self.associativity,
                "line_size": self.line_size
            },
            "per_core": [],
            "total_hits": total_hits,
            "total_misses": total_misses,
            "overall_miss_rate": total_misses / max(1, total),
            "bus_transactions": self.bus_transactions,
            "total_invalidations": self.total_invalidations,
            "memory_reads": self.memory_reads,
            "memory_writes": self.memory_writes
        }

        for i, cache in enumerate(self.caches):
            ct = cache.hits + cache.misses
            stats["per_core"].append({
                "core_id": i,
                "hits": cache.hits,
                "misses": cache.misses,
                "hit_rate": cache.hits / max(1, ct),
                "evictions": cache.evictions,
                "writebacks": cache.writebacks,
                "invalidations_received": cache.invalidations_received,
                "upgrades": cache.upgrades
            })

        return stats


def main():
    import os
    os.makedirs('/app/output', exist_ok=True)

    trace_path = '/app/traces/workload.trace'

    # --- Part 1: Baseline stats ---
    print("Running baseline simulation (4 cores, 2KB, 4-way, 64B lines)...")
    sim = MESISimulator(num_cores=4, cache_size=2048, associativity=4, line_size=64)
    sim.run_trace(trace_path)
    stats = sim.get_stats()
    with open('/app/output/stats.json', 'w') as f:
        json.dump(stats, f, indent=2)
    print(f"  total_hits={stats['total_hits']}, total_misses={stats['total_misses']}, "
          f"miss_rate={stats['overall_miss_rate']:.4f}")
    print(f"  bus_tx={stats['bus_transactions']}, invalidations={stats['total_invalidations']}, "
          f"mem_reads={stats['memory_reads']}, mem_writes={stats['memory_writes']}")

    # --- Part 2: Design space sweep ---
    print("\nDesign-space sweep (4-way, 64B lines):")
    sizes = [512, 1024, 2048, 4096, 8192, 16384, 32768]
    miss_rates = {}
    for sz in sizes:
        sim2 = MESISimulator(num_cores=4, cache_size=sz, associativity=4, line_size=64)
        sim2.run_trace(trace_path)
        s2 = sim2.get_stats()
        mr = s2['overall_miss_rate']
        miss_rates[sz] = mr
        print(f"  size={sz:>6d}B  miss_rate={mr:.4f}")

    # Find minimum size with miss rate < 10%
    min_size = None
    for sz in sizes:
        if miss_rates[sz] < 0.10:
            min_size = sz
            break

    if min_size is None:
        # Even 32KB doesn't meet threshold
        min_size = 32768
        mr_at_min = miss_rates[32768]
        mr_at_half = miss_rates.get(16384, 1.0)
    else:
        mr_at_min = miss_rates[min_size]
        if min_size <= 512:
            mr_at_half = 1.0
        else:
            mr_at_half = miss_rates[min_size // 2]

    result = {
        "min_cache_size_bytes": min_size,
        "miss_rate_at_min": mr_at_min,
        "miss_rate_at_half": mr_at_half
    }
    with open('/app/output/min_size.json', 'w') as f:
        json.dump(result, f, indent=2)
    print(f"\nMinimum size for <10% miss rate: {min_size}B "
          f"(rate={mr_at_min:.4f}, half={mr_at_half:.4f})")


if __name__ == '__main__':
    main()
