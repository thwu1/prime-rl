#!/usr/bin/env python3
"""
Reference implementation of a PtrHash-style Minimal Perfect Hash Function.

Uses pilot-based construction with cuckoo-hashing eviction, following the
algorithm described in: Groot Koerkamp, "PtrHash: Minimal Perfect Hashing
at RAM Throughput", SEA 2025.
"""

import random
import heapq

MASK64 = (1 << 64) - 1
C = 0x517cc1b727220a95


def _splitmix(x):
    """SplitMix64 bit finalizer — strong 64-bit mixing function."""
    x = (x ^ (x >> 30)) & MASK64
    x = (x * 0xbf58476d1ce4e5b9) & MASK64
    x = (x ^ (x >> 27)) & MASK64
    x = (x * 0x94d049bb133111eb) & MASK64
    x = (x ^ (x >> 31)) & MASK64
    return x


class MPHF:
    """Minimal Perfect Hash Function using pilot-based construction with
    cuckoo-hashing eviction."""

    def __init__(self):
        self.seed = 0
        self.n = 0
        self.num_slots = 0
        self.num_buckets = 0
        self.pilots = []
        self.remap = []
        self._phashes = None  # precomputed pilot hashes

    @staticmethod
    def build(keys, alpha=0.98, lam=3.0):
        """Build an MPHF for the given list of integer keys."""
        mphf = MPHF()
        mphf.n = len(keys)

        if mphf.n == 0:
            return mphf

        # Compute table sizes
        mphf.num_slots = max(int(mphf.n / alpha) + 1, mphf.n + 1)
        if mphf.num_slots & (mphf.num_slots - 1) == 0:
            mphf.num_slots += 1
        mphf.num_buckets = max(int(mphf.n / lam) + 3, 4)

        rng = random.Random(42)

        for _attempt in range(10):
            mphf.seed = rng.randint(0, MASK64)

            # Precompute all 256 pilot hashes
            mphf._phashes = [(C * (p ^ mphf.seed)) & MASK64 for p in range(256)]

            # Hash all keys
            _hk = mphf._hash_key
            all_hashes = [_hk(k) for k in keys]

            # Check for duplicate hashes
            if len(set(all_hashes)) != mphf.n:
                continue

            # Assign keys to buckets
            nb = mphf.num_buckets
            bucket_hashes = [[] for _ in range(nb)]
            for h in all_hashes:
                bucket_hashes[(h * nb) >> 64].append(h)

            # Sort bucket indices by size descending
            bucket_order = sorted(
                range(nb), key=lambda i: len(bucket_hashes[i]), reverse=True
            )

            pilots = [0] * nb
            taken = bytearray(mphf.num_slots)
            slot_owner = [-1] * mphf.num_slots

            if mphf._find_all_pilots(
                bucket_hashes, bucket_order, pilots, taken, slot_owner
            ):
                mphf.pilots = pilots
                mphf._build_remap(taken)
                return mphf

        raise RuntimeError("MPHF construction failed after 10 seed attempts")

    def _hash_key(self, key):
        """Hash a key with the current seed using SplitMix64 finalizer."""
        return _splitmix((key ^ self.seed) & MASK64)

    def _get_bucket(self, h):
        """Map a 64-bit hash to a bucket index via fast reduce."""
        return (h * self.num_buckets) >> 64

    def _find_all_pilots(self, bkt_h, order, pilots, taken, owners):
        """Find pilots for all buckets using greedy search with eviction."""
        max_evictions = 10 * self.num_slots
        total_evictions = 0
        ns = self.num_slots
        phashes = self._phashes

        def slots_for(bh, p):
            hp = phashes[p]
            return [((h ^ hp) & MASK64) % ns for h in bh]

        for new_b in order:
            bkt = bkt_h[new_b]
            if not bkt:
                continue

            stack = [(-len(bkt), new_b)]
            recent = [new_b]

            while stack:
                _, b = heapq.heappop(stack)
                bh = bkt_h[b]
                if not bh:
                    continue

                # Phase 1: collision-free pilot search
                placed = False
                for p in range(256):
                    slots = slots_for(bh, p)
                    if len(set(slots)) != len(slots):
                        continue
                    if all(taken[s] == 0 for s in slots):
                        pilots[b] = p
                        for s in slots:
                            taken[s] = 1
                            owners[s] = b
                        placed = True
                        break

                if placed:
                    continue

                # Phase 2: eviction pilot search
                best_score = float('inf')
                best_pilot = -1
                p0 = (b * 2654435761) & 0xFF

                for delta in range(256):
                    p = (p0 + delta) & 0xFF
                    slots = slots_for(bh, p)
                    if len(set(slots)) != len(slots):
                        continue

                    score = 0
                    skip = False
                    for s in slots:
                        o = owners[s]
                        if o >= 0 and o != b:
                            if o in recent:
                                skip = True
                                break
                            score += len(bkt_h[o]) ** 2

                    if skip:
                        continue
                    if score < best_score:
                        best_score = score
                        best_pilot = p
                        if score <= 1:
                            break

                if best_pilot < 0:
                    return False

                # Apply pilot with eviction
                pilots[b] = best_pilot
                slots = slots_for(bh, best_pilot)

                for s in slots:
                    o = owners[s]
                    if o >= 0 and o != b:
                        total_evictions += 1
                        if total_evictions > max_evictions:
                            return False
                        ev_slots = slots_for(bkt_h[o], pilots[o])
                        for es in ev_slots:
                            taken[es] = 0
                            owners[es] = -1
                        heapq.heappush(stack, (-len(bkt_h[o]), o))

                    taken[s] = 1
                    owners[s] = b

                recent.append(b)
                if len(recent) > 16:
                    recent = recent[-16:]

        return True

    def _build_remap(self, taken):
        """Build remap table: occupied slots >= n map to free slots < n."""
        free_below_n = [i for i in range(self.n) if not taken[i]]
        self.remap = [0] * (self.num_slots - self.n)
        fi = 0
        for j in range(self.num_slots - self.n):
            if taken[self.n + j]:
                self.remap[j] = free_below_n[fi]
                fi += 1

    def query(self, key):
        """Query the MPHF for a key. Returns a value in [0, n)."""
        h = self._hash_key(key)
        b = self._get_bucket(h)
        p = self.pilots[b]
        hp = self._phashes[p]
        slot = ((h ^ hp) & MASK64) % self.num_slots
        if slot < self.n:
            return slot
        return self.remap[slot - self.n]

    def bits_per_key(self):
        """Return the storage cost in bits per key."""
        if self.n == 0:
            return 0.0
        pilot_bytes = len(self.pilots)
        remap_bytes = len(self.remap) * 4
        return 8.0 * (pilot_bytes + remap_bytes) / self.n
