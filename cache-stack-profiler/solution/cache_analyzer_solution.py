#!/usr/bin/env python3
"""
Complete cache performance analyzer solution.

"""
import json
import os
from collections import defaultdict


def parse_trace(filepath):
    """Parse a memory trace file. Each line: '<r|w> <8-hex-digit address>'."""
    trace = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            op = parts[0]
            addr = int(parts[1], 16)
            trace.append((op, addr))
    return trace


class CacheSimulator:
    """N-way set-associative cache with true LRU and write-back/write-allocate."""

    def __init__(self, cache_size, block_size, associativity):
        self.cache_size = cache_size
        self.block_size = block_size
        self.associativity = associativity
        self.num_sets = cache_size // (block_size * associativity)
        # Each set is a list of (tag, dirty) tuples in LRU order.
        # Index 0 = most recently used. Last index = least recently used.
        self.sets = [[] for _ in range(self.num_sets)]
        self.hits = 0
        self.misses = 0
        self.loads = 0
        self.stores = 0
        self.writebacks = 0

    def _set_index(self, addr):
        return (addr // self.block_size) % self.num_sets

    def _tag(self, addr):
        return (addr // self.block_size) // self.num_sets

    def access(self, op, addr):
        if op == 'r':
            self.loads += 1
        else:
            self.stores += 1

        si = self._set_index(addr)
        tag = self._tag(addr)
        s = self.sets[si]

        # Search for tag in set
        for i, (t, dirty) in enumerate(s):
            if t == tag:
                # Hit: move to MRU position
                self.hits += 1
                entry = s.pop(i)
                if op == 'w':
                    entry = (t, True)
                s.insert(0, entry)
                return

        # Miss
        self.misses += 1

        # Evict LRU if set is full
        if len(s) >= self.associativity:
            evicted = s.pop()
            if evicted[1]:  # dirty
                self.writebacks += 1

        # Insert new block at MRU position
        s.insert(0, (tag, op == 'w'))

    def stats(self):
        total = self.hits + self.misses
        return {
            "total_accesses": total,
            "loads": self.loads,
            "stores": self.stores,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 6) if total > 0 else 0.0,
            "miss_rate": round(self.misses / total, 6) if total > 0 else 0.0,
            "writebacks": self.writebacks,
            "bytes_bus_to_cache": self.misses * self.block_size,
            "bytes_cache_to_bus": self.writebacks * self.block_size,
            "bytes_total_traffic": (self.misses + self.writebacks) * self.block_size,
        }


def compute_stack_distance(trace, block_size):
    """
    Compute LRU stack distance for every access.

    Maintains a logical LRU stack of block addresses. For each access:
    - If the block was seen before, the stack distance is its current position
      in the stack (0 = MRU, i.e., immediate re-access).
    - If the block is new, the distance is "inf" (cold/compulsory miss).

    Returns a histogram {distance: count} and total_accesses.
    """
    stack = []  # LRU stack: index 0 = MRU
    histogram = defaultdict(int)

    for op, addr in trace:
        block_addr = addr // block_size
        if block_addr in stack:
            pos = stack.index(block_addr)
            histogram[pos] += 1
            stack.pop(pos)
            stack.insert(0, block_addr)
        else:
            histogram["inf"] += 1
            stack.insert(0, block_addr)

    return dict(histogram), len(trace)


def predict_miss_rate(histogram, num_blocks):
    """
    Predict miss rate for fully-associative LRU cache with `num_blocks` blocks.

    By the inclusion property (Mattson et al., 1970): an access hits in a
    fully-associative LRU cache of size C iff its stack distance < C.
    Cold misses ("inf") always miss.
    """
    total = sum(histogram.values())
    misses = histogram.get("inf", 0)
    for dist, count in histogram.items():
        if dist == "inf":
            continue
        if dist >= num_blocks:
            misses += count
    return round(misses / total, 6) if total > 0 else 0.0


def find_optimal(trace, cache_sizes, block_sizes, associativities, target_miss_rate):
    """
    Find minimum-cost config: cost = cache_size * associativity.
    Tiebreak: smallest cache_size, then smallest block_size.
    """
    best = None
    for cs in sorted(cache_sizes):
        for bs in sorted(block_sizes):
            for assoc in sorted(associativities):
                num_sets = cs // (bs * assoc)
                if num_sets < 1:
                    continue
                sim = CacheSimulator(cs, bs, assoc)
                for op, addr in trace:
                    sim.access(op, addr)
                st = sim.stats()
                if st["miss_rate"] <= target_miss_rate:
                    cost = cs * assoc
                    if best is None or cost < best["best_cost"] or \
                       (cost == best["best_cost"] and cs < best["best_cache_size"]) or \
                       (cost == best["best_cost"] and cs == best["best_cache_size"] and bs < best["best_block_size"]):
                        best = {
                            "best_cache_size": cs,
                            "best_block_size": bs,
                            "best_associativity": assoc,
                            "best_cost": cost,
                            "achieved_miss_rate": st["miss_rate"],
                        }
    return best


def main():
    with open("/app/queries.json") as f:
        queries = json.load(f)

    results = {
        "simulations": {},
        "stack_distance": {},
        "miss_rate_predictions": {},
        "optimize": {},
    }

    # Cache for parsed traces and stack distances
    trace_cache = {}
    sd_cache = {}

    # 1. Simulations
    for sim_q in queries.get("simulations", []):
        trace_path = os.path.join("/app", sim_q["trace"])
        if trace_path not in trace_cache:
            trace_cache[trace_path] = parse_trace(trace_path)
        trace = trace_cache[trace_path]

        sim = CacheSimulator(
            sim_q["cache_size_bytes"],
            sim_q["block_size_bytes"],
            sim_q["associativity"],
        )
        for op, addr in trace:
            sim.access(op, addr)
        results["simulations"][sim_q["id"]] = sim.stats()

    # 2. Stack distance
    for sd_q in queries.get("stack_distance", []):
        trace_path = os.path.join("/app", sd_q["trace"])
        if trace_path not in trace_cache:
            trace_cache[trace_path] = parse_trace(trace_path)
        trace = trace_cache[trace_path]

        histogram, total = compute_stack_distance(trace, sd_q["block_size_bytes"])
        # Convert keys to strings for JSON
        str_hist = {str(k): v for k, v in histogram.items()}
        results["stack_distance"][sd_q["id"]] = {
            "histogram": str_hist,
            "total_accesses": total,
        }
        sd_cache[sd_q["id"]] = histogram

    # 3. Miss rate predictions
    for pred_q in queries.get("miss_rate_predictions", []):
        sd_id = pred_q["stack_distance_id"]
        histogram = sd_cache[sd_id]
        preds = {}
        for nb in pred_q["num_blocks"]:
            mr = predict_miss_rate(histogram, nb)
            preds[str(nb)] = mr
        results["miss_rate_predictions"][pred_q["id"]] = preds

    # 4. Optimization
    for opt_q in queries.get("optimize", []):
        trace_path = os.path.join("/app", opt_q["trace"])
        if trace_path not in trace_cache:
            trace_cache[trace_path] = parse_trace(trace_path)
        trace = trace_cache[trace_path]

        best = find_optimal(
            trace,
            opt_q["cache_sizes"],
            opt_q["block_sizes"],
            opt_q["associativities"],
            opt_q["target_miss_rate"],
        )
        results["optimize"][opt_q["id"]] = best

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
