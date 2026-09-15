"""Static Re-Reference Interval Prediction (SRRIP) replacement policy."""

from policies.base import ReplacementPolicy


class SRRIPPolicy(ReplacementPolicy):

    def __init__(self, num_sets, num_ways, rrpv_bits=3):
        self.num_sets = num_sets
        self.num_ways = num_ways
        self.rrpv_bits = rrpv_bits
        self.max_rrpv = (1 << rrpv_bits) - 1
        self.rrpv = [[self.max_rrpv] * num_ways for _ in range(num_sets)]

    def on_access(self, set_idx, way, hit, pc=0):
        if hit:
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
        total_bits = self.num_sets * self.num_ways * self.rrpv_bits
        return (total_bits + 7) // 8
