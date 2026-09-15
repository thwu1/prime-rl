"""Belady's OPT (MIN) offline optimal replacement policy."""

from policies.base import ReplacementPolicy


class BeladyOPT(ReplacementPolicy):

    def __init__(self, num_sets, num_ways, accesses, block_size):
        self.num_ways = num_ways
        self.num_sets = num_sets

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

    def on_access(self, set_idx, way, hit, pc=0):
        self.way_next_use[set_idx][way] = self.next_use[self.access_idx]
        self.access_idx += 1

    def find_victim(self, set_idx, cache_set):
        inv = cache_set.find_invalid()
        if inv >= 0:
            return inv
        return min(range(self.num_ways),
                   key=lambda w: self.way_next_use[set_idx][w])

    def storage_bytes(self):
        return -1
