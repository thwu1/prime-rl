#!/usr/bin/env python3
"""Cache replacement policy evaluation framework.

Implements LRU, SRRIP, DRRIP, and Belady's OPT for set-associative caches.
Evaluates each policy against provided traces and outputs structured results.
"""

import json
import math
import os


def parse_trace(filepath):
    """Parse trace file. Each line: <PC_hex> <addr_hex> <type_int>"""
    accesses = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            pc = int(parts[0], 16)
            addr = int(parts[1], 16)
            atype = int(parts[2])
            accesses.append((pc, addr, atype))
    return accesses


class CacheSet:
    """A single cache set with configurable associativity."""

    def __init__(self, num_ways):
        self.num_ways = num_ways
        self.tags = [None] * num_ways
        self.valid = [False] * num_ways

    def find(self, tag):
        for w in range(self.num_ways):
            if self.valid[w] and self.tags[w] == tag:
                return w
        return -1

    def find_invalid(self):
        for w in range(self.num_ways):
            if not self.valid[w]:
                return w
        return -1

    def insert(self, way, tag):
        self.tags[way] = tag
        self.valid[way] = True


# ---- Replacement Policies ----

class LRUPolicy:
    """Least Recently Used replacement."""

    def __init__(self, num_sets, num_ways):
        self.num_sets = num_sets
        self.num_ways = num_ways
        self.access_time = [[0] * num_ways for _ in range(num_sets)]
        self.clock = 0

    def on_access(self, set_idx, way, hit):
        self.clock += 1
        self.access_time[set_idx][way] = self.clock

    def find_victim(self, set_idx, cache_set):
        inv = cache_set.find_invalid()
        if inv >= 0:
            return inv
        return min(range(self.num_ways),
                   key=lambda w: self.access_time[set_idx][w])

    def storage_bytes(self):
        bits_per_way = max(1, math.ceil(math.log2(self.num_ways)))
        total_bits = self.num_sets * self.num_ways * bits_per_way
        return (total_bits + 7) // 8


class SRRIPPolicy:
    """Static Re-Reference Interval Prediction (3-bit RRPV)."""

    def __init__(self, num_sets, num_ways, rrpv_bits=3):
        self.num_sets = num_sets
        self.num_ways = num_ways
        self.rrpv_bits = rrpv_bits
        self.max_rrpv = (1 << rrpv_bits) - 1
        self.rrpv = [[self.max_rrpv] * num_ways for _ in range(num_sets)]

    def on_access(self, set_idx, way, hit):
        if hit:
            self.rrpv[set_idx][way] = 0
        else:
            self.rrpv[set_idx][way] = self.max_rrpv - 1

    def find_victim(self, set_idx, cache_set):
        inv = cache_set.find_invalid()
        if inv >= 0:
            return inv
        while True:
            for w in range(self.num_ways):
                if self.rrpv[set_idx][w] >= self.max_rrpv:
                    return w
            for w in range(self.num_ways):
                self.rrpv[set_idx][w] += 1

    def storage_bytes(self):
        total_bits = self.num_sets * self.num_ways * self.rrpv_bits
        return (total_bits + 7) // 8


class DRRIPPolicy:
    """Dynamic RRIP with set dueling (SRRIP vs BRRIP)."""

    def __init__(self, num_sets, num_ways, rrpv_bits=3, num_leader_sets=32):
        self.num_sets = num_sets
        self.num_ways = num_ways
        self.rrpv_bits = rrpv_bits
        self.max_rrpv = (1 << rrpv_bits) - 1
        self.rrpv = [[self.max_rrpv] * num_ways for _ in range(num_sets)]

        self.psel_bits = 10
        self.psel_max = (1 << self.psel_bits) - 1
        self.psel = self.psel_max // 2  # midpoint

        self.num_leaders = min(num_leader_sets, num_sets // 4)
        interval = max(num_sets // self.num_leaders, 2)
        self.srrip_leaders = set()
        self.brrip_leaders = set()
        for i in range(self.num_leaders):
            s = i * interval
            if s < num_sets:
                self.srrip_leaders.add(s)
            b = i * interval + 1
            if b < num_sets:
                self.brrip_leaders.add(b)

        self.brrip_counter = 0

    def _use_brrip(self, set_idx):
        if set_idx in self.srrip_leaders:
            return False
        if set_idx in self.brrip_leaders:
            return True
        return self.psel > self.psel_max // 2

    def on_access(self, set_idx, way, hit):
        if hit:
            self.rrpv[set_idx][way] = 0
        else:
            # Update PSEL on misses in leader sets
            if set_idx in self.srrip_leaders:
                self.psel = min(self.psel_max, self.psel + 1)
            elif set_idx in self.brrip_leaders:
                self.psel = max(0, self.psel - 1)

            if self._use_brrip(set_idx):
                self.brrip_counter += 1
                if self.brrip_counter % 32 == 0:
                    self.rrpv[set_idx][way] = self.max_rrpv - 1
                else:
                    self.rrpv[set_idx][way] = self.max_rrpv
            else:
                self.rrpv[set_idx][way] = self.max_rrpv - 1

    def find_victim(self, set_idx, cache_set):
        inv = cache_set.find_invalid()
        if inv >= 0:
            return inv
        while True:
            for w in range(self.num_ways):
                if self.rrpv[set_idx][w] >= self.max_rrpv:
                    return w
            for w in range(self.num_ways):
                self.rrpv[set_idx][w] += 1

    def storage_bytes(self):
        rrpv_bits = self.num_sets * self.num_ways * self.rrpv_bits
        psel_bits = self.psel_bits
        return (rrpv_bits + psel_bits + 7) // 8


class BeladyOPT:
    """Belady's MIN/OPT — offline optimal replacement.

    Precomputes next-use indices by reverse-scanning the trace.
    On eviction, selects the block whose next access is farthest in the future.
    """

    def __init__(self, num_sets, num_ways, accesses, block_size):
        self.num_ways = num_ways
        self.num_sets = num_sets

        # Precompute next-use for each access position
        self.next_use = [float('inf')] * len(accesses)
        last_seen = {}
        for i in range(len(accesses) - 1, -1, -1):
            _, addr, _ = accesses[i]
            tag = addr // block_size
            set_idx = tag % num_sets
            key = (set_idx, tag)
            if key in last_seen:
                self.next_use[i] = last_seen[key]
            last_seen[key] = i

        self.way_next_use = [[float('inf')] * num_ways for _ in range(num_sets)]
        self.access_idx = 0

    def on_access(self, set_idx, way, hit):
        self.way_next_use[set_idx][way] = self.next_use[self.access_idx]
        self.access_idx += 1

    def find_victim(self, set_idx, cache_set):
        inv = cache_set.find_invalid()
        if inv >= 0:
            return inv
        return max(range(self.num_ways),
                   key=lambda w: self.way_next_use[set_idx][w])

    def storage_bytes(self):
        return -1  # unbounded offline oracle


# ---- Simulation ----

def simulate(accesses, num_sets, num_ways, block_size, policy):
    """Run cache simulation with given policy. Returns (hits, misses)."""
    sets = [CacheSet(num_ways) for _ in range(num_sets)]
    hits = 0
    misses = 0

    for pc, addr, atype in accesses:
        tag = addr // block_size
        set_idx = tag % num_sets
        cs = sets[set_idx]
        way = cs.find(tag)

        if way >= 0:
            hits += 1
            policy.on_access(set_idx, way, True)
        else:
            misses += 1
            victim = policy.find_victim(set_idx, cs)
            cs.insert(victim, tag)
            policy.on_access(set_idx, victim, False)

    return hits, misses


def geomean(values):
    """Geometric mean of positive values."""
    if not values:
        return 1.0
    log_sum = sum(math.log(max(v, 1e-15)) for v in values)
    return math.exp(log_sum / len(values))


# ---- Main ----

def main():
    with open('/app/cache_spec.json') as f:
        spec = json.load(f)

    num_sets = spec['num_sets']
    num_ways = spec['num_ways']
    block_size = spec['block_size']
    trace_dir = spec['trace_dir']

    trace_files = sorted(
        tf for tf in os.listdir(trace_dir)
        if tf.endswith('.txt') and os.path.isfile(os.path.join(trace_dir, tf))
    )

    # Load all traces once
    all_traces = {}
    for tf in trace_files:
        all_traces[tf] = parse_trace(os.path.join(trace_dir, tf))

    results = {"policies": {}}

    # Simulate each policy on each trace
    for pname in ['lru', 'srrip', 'drrip', 'opt']:
        pdata = {"per_trace": {}}

        for tf in trace_files:
            accesses = all_traces[tf]
            tname = os.path.splitext(tf)[0]

            if pname == 'lru':
                pol = LRUPolicy(num_sets, num_ways)
            elif pname == 'srrip':
                pol = SRRIPPolicy(num_sets, num_ways, rrpv_bits=3)
            elif pname == 'drrip':
                pol = DRRIPPolicy(num_sets, num_ways, rrpv_bits=3)
            elif pname == 'opt':
                pol = BeladyOPT(num_sets, num_ways, accesses, block_size)

            hits, misses = simulate(accesses, num_sets, num_ways, block_size, pol)
            total = hits + misses
            mr = misses / total if total > 0 else 0.0
            hr = hits / total if total > 0 else 0.0

            pdata["per_trace"][tname] = {
                "accesses": total,
                "hits": hits,
                "misses": misses,
                "miss_rate": round(mr, 10),
                "hit_rate": round(hr, 10),
            }

        # Storage budget
        if pname == 'lru':
            storage = LRUPolicy(num_sets, num_ways).storage_bytes()
        elif pname == 'srrip':
            storage = SRRIPPolicy(num_sets, num_ways).storage_bytes()
        elif pname == 'drrip':
            storage = DRRIPPolicy(num_sets, num_ways).storage_bytes()
        else:
            storage = -1

        pdata["storage_bytes"] = storage
        results["policies"][pname] = pdata

    # Compute geometric mean miss-rate reduction (LRU_mr / policy_mr)
    lru_traces = results["policies"]["lru"]["per_trace"]
    for pname in ['lru', 'srrip', 'drrip', 'opt']:
        pol_traces = results["policies"][pname]["per_trace"]
        ratios = []
        for tname in pol_traces:
            lru_mr = lru_traces[tname]["miss_rate"]
            pol_mr = pol_traces[tname]["miss_rate"]
            if lru_mr > 0 and pol_mr > 0:
                ratios.append(lru_mr / pol_mr)
            elif lru_mr == 0 and pol_mr == 0:
                ratios.append(1.0)
            elif pol_mr == 0:
                ratios.append(100.0)  # cap for zero-miss policy
            else:
                ratios.append(lru_mr / pol_mr)
        results["policies"][pname]["geomean_miss_rate_reduction"] = round(
            geomean(ratios), 10
        )

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")
    for pname in ['lru', 'srrip', 'drrip', 'opt']:
        pdata = results["policies"][pname]
        print(f"\n{pname.upper()} (storage: {pdata['storage_bytes']}B, "
              f"geomean: {pdata['geomean_miss_rate_reduction']:.4f}):")
        for tname, td in sorted(pdata["per_trace"].items()):
            print(f"  {tname}: miss_rate={td['miss_rate']:.6f} "
                  f"({td['misses']}/{td['accesses']})")


if __name__ == '__main__':
    main()
