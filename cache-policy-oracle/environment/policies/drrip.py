"""Dynamic RRIP (DRRIP) replacement policy with set dueling."""

from policies.base import ReplacementPolicy


class DRRIPPolicy(ReplacementPolicy):

    def __init__(self, num_sets, num_ways, rrpv_bits=3, num_leader_sets=32):
        self.num_sets = num_sets
        self.num_ways = num_ways
        self.rrpv_bits = rrpv_bits
        self.max_rrpv = (1 << rrpv_bits) - 1
        self.rrpv = [[self.max_rrpv] * num_ways for _ in range(num_sets)]

        self.psel_bits = 10
        self.psel_max = (1 << self.psel_bits) - 1
        self.psel = self.psel_max // 2

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

    def on_access(self, set_idx, way, hit, pc=0):
        if hit:
            self.rrpv[set_idx][way] = 0
        else:
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
        """Compute storage budget for DRRIP replacement metadata.

        Must account for all auxiliary state used by the replacement policy:
        per-way RRPV bits across all sets, plus the PSEL counter bits.
        """
        raise NotImplementedError
