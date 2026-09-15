
"""Reference MESI cache coherence protocol simulator for test verification."""

import json
import math


class CacheLine:
    __slots__ = ('tag', 'state')

    def __init__(self):
        self.tag = None
        self.state = 'I'


class CacheSet:
    def __init__(self, num_ways):
        self.lines = [CacheLine() for _ in range(num_ways)]
        self.lru_order = list(range(num_ways))  # [0]=MRU ... [-1]=LRU

    def find(self, tag):
        for i, line in enumerate(self.lines):
            if line.tag == tag and line.state != 'I':
                return i
        return -1

    def get_victim(self):
        for i in range(len(self.lines)):
            if self.lines[i].state == 'I':
                return i
        return self.lru_order[-1]

    def touch(self, way):
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
            # HIT
            line = cset.lines[way]
            cache.hits += 1

            if is_write:
                if line.state == 'S':
                    self.bus_transactions += 1
                    cache.upgrades += 1
                    self._invalidate_sharers(core_id, addr)
                    line.state = 'M'
                elif line.state == 'E':
                    line.state = 'M'
                # M stays M
            # Read hits: no state change

            cset.touch(way)
        else:
            # MISS
            cache.misses += 1
            self.bus_transactions += 1

            victim_way = cset.get_victim()
            victim = cset.lines[victim_way]

            if victim.state != 'I':
                cache.evictions += 1
                if victim.state == 'M':
                    cache.writebacks += 1
                    self.memory_writes += 1

            if is_write:
                found, was_modified = self._snoop_for_write(core_id, addr)
            else:
                found, was_modified = self._snoop_for_read(core_id, addr)

            if not was_modified:
                self.memory_reads += 1

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
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = line.split()
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
