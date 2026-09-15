"""Least Recently Used (LRU) replacement policy."""

import math
from policies.base import ReplacementPolicy


class LRUPolicy(ReplacementPolicy):

    def __init__(self, num_sets, num_ways):
        self.num_sets = num_sets
        self.num_ways = num_ways
        self.access_time = [[0] * num_ways for _ in range(num_sets)]
        self.clock = 0

    def on_access(self, set_idx, way, hit, pc=0):
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
