"""Set-associative cache simulator core."""


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


def simulate(accesses, num_sets, num_ways, block_size, policy):
    """Run cache simulation with given replacement policy.

    Args:
        accesses: list of (pc, addr, access_type) tuples
        num_sets: number of cache sets
        num_ways: set associativity
        block_size: cache block size in bytes
        policy: replacement policy object with on_access() and find_victim()

    Returns:
        (hits, misses) tuple
    """
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
            policy.on_access(set_idx, way, True, pc=pc)
        else:
            misses += 1
            victim = policy.find_victim(set_idx, cs)
            cs.insert(victim, tag)
            policy.on_access(set_idx, victim, False, pc=pc)

    return hits, misses
