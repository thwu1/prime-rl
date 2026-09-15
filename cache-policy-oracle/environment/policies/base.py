"""Base class for cache replacement policies."""


class ReplacementPolicy:
    """Interface for pluggable cache replacement policies.

    Subclasses must implement on_access(), find_victim(), and storage_bytes().
    """

    def on_access(self, set_idx, way, hit, pc=0):
        """Called after every cache access (hit or miss).

        Args:
            set_idx: cache set index
            way: way within the set that was accessed or filled
            hit: True if cache hit, False if miss (block was just inserted)
            pc: program counter of the accessing instruction
        """
        raise NotImplementedError

    def find_victim(self, set_idx, cache_set):
        """Select a victim way for eviction on a cache miss.

        Args:
            set_idx: cache set index
            cache_set: CacheSet object (has find_invalid(), num_ways, tags, valid)

        Returns:
            way index to evict
        """
        raise NotImplementedError

    def storage_bytes(self):
        """Compute auxiliary storage budget in bytes.

        Returns the total bytes of replacement metadata maintained by this
        policy (e.g., recency bits, prediction counters). Does not include
        tag/data storage.
        """
        raise NotImplementedError
