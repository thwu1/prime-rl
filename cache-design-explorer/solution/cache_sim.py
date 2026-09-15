#!/usr/bin/env python3

"""Reference cache simulator and answer generator."""

import json
import math


class CacheLine:
    __slots__ = ['valid', 'dirty', 'tag', 'last_used']

    def __init__(self):
        self.valid = False
        self.dirty = False
        self.tag = 0
        self.last_used = 0


class CacheSimulator:
    def __init__(self, capacity, block_size, associativity):
        self.capacity = capacity
        self.block_size = block_size
        self.associativity = associativity
        self.n_sets = capacity // (block_size * associativity)
        self.n_offset_bits = int(math.log2(block_size))
        self.n_index_bits = int(math.log2(self.n_sets)) if self.n_sets > 1 else 0
        self.sets = [
            [CacheLine() for _ in range(associativity)]
            for _ in range(self.n_sets)
        ]
        self.hits = 0
        self.misses = 0
        self.writebacks = 0
        self.n_stores = 0
        self.n_loads = 0
        self.time = 0

    def _get_tag(self, addr):
        return addr >> (self.n_offset_bits + self.n_index_bits)

    def _get_index(self, addr):
        if self.n_index_bits == 0:
            return 0
        return (addr >> self.n_offset_bits) & ((1 << self.n_index_bits) - 1)

    def access(self, op, addr):
        self.time += 1
        tag = self._get_tag(addr)
        index = self._get_index(addr)
        is_write = (op == 'w')
        if is_write:
            self.n_stores += 1
        else:
            self.n_loads += 1

        cache_set = self.sets[index]

        # Check for hit
        for line in cache_set:
            if line.valid and line.tag == tag:
                self.hits += 1
                line.last_used = self.time
                if is_write:
                    line.dirty = True
                return True

        # Miss
        self.misses += 1

        # Find victim: prefer first invalid line (lowest way index)
        victim = None
        for line in cache_set:
            if not line.valid:
                victim = line
                break

        if victim is None:
            # True LRU: evict line with smallest last_used
            victim = min(cache_set, key=lambda l: l.last_used)

        # Writeback if evicting a dirty line
        if victim.valid and victim.dirty:
            self.writebacks += 1

        # Install new line
        victim.valid = True
        victim.tag = tag
        victim.dirty = is_write
        victim.last_used = self.time
        return False

    def run_trace(self, trace_path):
        with open(trace_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    self.access(parts[0], int(parts[1], 16))

    def stats(self):
        total = self.hits + self.misses
        hit_rate = round(self.hits / total * 100, 2) if total > 0 else 0.0
        miss_rate = round(self.misses / total * 100, 2) if total > 0 else 0.0
        bus_to_cache = self.misses * self.block_size
        cache_to_bus_wb = self.writebacks * self.block_size
        total_traffic_wb = bus_to_cache + cache_to_bus_wb
        cache_to_bus_wt = self.n_stores * 4
        total_traffic_wt = bus_to_cache + cache_to_bus_wt
        return {
            "hits": self.hits,
            "misses": self.misses,
            "writebacks": self.writebacks,
            "hit_rate": hit_rate,
            "miss_rate": miss_rate,
            "n_stores": self.n_stores,
            "bus_to_cache": bus_to_cache,
            "cache_to_bus_wb": cache_to_bus_wb,
            "total_traffic_wb": total_traffic_wb,
            "cache_to_bus_wt": cache_to_bus_wt,
            "total_traffic_wt": total_traffic_wt,
        }


def run_sim(trace_path, c, b, a):
    sim = CacheSimulator(c, b, a)
    sim.run_trace(trace_path)
    return sim.stats()


def main():
    trace_a = '/app/traces/trace_a.txt'
    trace_b = '/app/traces/trace_b.txt'
    trace_c = '/app/traces/trace_c.txt'

    # Q1: trace_a, C=512, B=32, A=1
    q1_stats = run_sim(trace_a, 512, 32, 1)
    q1 = {k: q1_stats[k] for k in [
        'hits', 'misses', 'writebacks', 'hit_rate', 'n_stores',
        'bus_to_cache', 'cache_to_bus_wb', 'total_traffic_wb',
        'cache_to_bus_wt', 'total_traffic_wt',
    ]}

    # Q2: trace_b, C=4096, B=64, A=4
    q2_stats = run_sim(trace_b, 4096, 64, 4)
    q2 = {k: q2_stats[k] for k in [
        'hits', 'misses', 'writebacks', 'hit_rate', 'n_stores',
        'bus_to_cache', 'cache_to_bus_wb', 'total_traffic_wb',
        'cache_to_bus_wt', 'total_traffic_wt',
    ]}

    # Q3: trace_c, C=2048, B=32, A in {1,2,4,8}
    q3_results = {}
    best_miss_rate = float('inf')
    best_a = None
    for assoc in [1, 2, 4, 8]:
        s = run_sim(trace_c, 2048, 32, assoc)
        q3_results[str(assoc)] = {
            "miss_rate": s['miss_rate'],
            "total_traffic_wb": s['total_traffic_wb'],
        }
        if s['miss_rate'] < best_miss_rate:
            best_miss_rate = s['miss_rate']
            best_a = assoc
    q3 = {"results": q3_results, "best_associativity": best_a}

    # Q4: AMAT for 5 configs on trace_a
    q4_params = [
        (256, 16, 1),
        (512, 32, 1),
        (512, 32, 2),
        (1024, 32, 2),
        (1024, 64, 4),
    ]
    q4_configs = []
    best_amat = float('inf')
    best_idx = None
    for i, (c, b, a) in enumerate(q4_params):
        s = run_sim(trace_a, c, b, a)
        total = s['hits'] + s['misses']
        miss_frac = s['misses'] / total if total > 0 else 0
        amat = round(1 + miss_frac * 100, 2)
        q4_configs.append({"amat": amat})
        if amat < best_amat:
            best_amat = amat
            best_idx = i
    q4 = {"configs": q4_configs, "best_config_index": best_idx}

    # Q5: minimize total_traffic_wb on trace_b over 36 configs
    best_traffic = float('inf')
    best_config = None
    for c in [512, 1024, 2048, 4096]:
        for b in [16, 32, 64]:
            for a in [1, 2, 4]:
                s = run_sim(trace_b, c, b, a)
                t = s['total_traffic_wb']
                if t < best_traffic:
                    best_traffic = t
                    best_config = (c, b, a)
    q5 = {
        "best_config": {
            "capacity": best_config[0],
            "block_size": best_config[1],
            "associativity": best_config[2],
        },
        "min_traffic": best_traffic,
    }

    answers = {"q1": q1, "q2": q2, "q3": q3, "q4": q4, "q5": q5}
    with open('/app/answers.json', 'w') as f:
        json.dump(answers, f, indent=2)
    print("Answers written to /app/answers.json")


if __name__ == '__main__':
    main()
