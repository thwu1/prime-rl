"""
Counting Quotient Filter (CQF) Implementation

A compact probabilistic data structure supporting approximate membership queries
with counting, deletion, merging, resizing, and vector-space operations.

Based on the design from:
  "A General-Purpose Counting Filter: Making Every Bit Count"
  Pandey, Bender, Johnson, Patro — SIGMOD 2017

Structure:
  - An array of 2^q_bits slots, each holding a remainder and a count.
  - Each inserted item is hashed to a (quotient, remainder) pair.
  - The quotient determines the item's canonical slot.
  - Remainders are stored at or near the canonical slot.
  - A "run" is a sorted, contiguous sequence of remainders sharing a quotient.
  - A "cluster" is a maximal contiguous block of occupied slots;
    it may contain runs for several quotients.

Metadata bits (per slot):
  - is_occupied[i]: True iff quotient i has at least one element in the filter.
    This is a property of the quotient (not of the physical slot data).
  - is_runend[i]:   True iff slot i holds the last element of some run.
    This is a property of the physical slot data (moves when data shifts).
"""

import hashlib
import struct
import math
from typing import Optional, Tuple, Iterator


class CQF:
    """Counting Quotient Filter with insert, query, delete, merge, resize."""

    def __init__(self, q_bits: int, r_bits: int, seed: int = 42):
        assert q_bits >= 2 and r_bits >= 1
        self.q_bits = q_bits
        self.r_bits = r_bits
        self.seed = seed
        self.size = 1 << q_bits
        self.r_mask = (1 << r_bits) - 1

        self.remainders = [0] * self.size
        self.counts = [0] * self.size
        self.is_occupied = [False] * self.size
        self.is_runend = [False] * self.size

        self.n_distinct = 0
        self.n_total = 0

    # ------------------------------------------------------------------ hash
    def _hash(self, item) -> Tuple[int, int]:
        """Hash *item* to a (quotient, remainder) pair.

        Uses BLAKE2b with a 4-byte key derived from *seed* to produce a
        deterministic, uniform fingerprint of (q_bits + r_bits) bits.
        The upper q_bits become the quotient; the lower r_bits the remainder.
        """
        data = str(item).encode("utf-8")
        h = hashlib.blake2b(
            data, digest_size=8, key=struct.pack("<I", self.seed)
        ).digest()
        val = struct.unpack("<Q", h)[0]
        total_bits = self.q_bits + self.r_bits
        fp = val & ((1 << total_bits) - 1)
        return fp >> self.r_bits, fp & self.r_mask

    # --------------------------------------------------------- slot helpers
    def _is_slot_empty(self, idx: int) -> bool:
        return self.counts[idx % self.size] == 0

    # ------------------------------------------------ cluster / run helpers
    def _find_cluster_start(self, pos: int) -> int:
        """Return the leftmost occupied slot of the cluster containing *pos*."""
        j = pos % self.size
        for _ in range(self.size):
            prev = (j - 1) % self.size
            if self._is_slot_empty(prev):
                return j
            j = prev
        return j  # filter completely full — whole array is one cluster

    def _find_run_start(self, quotient: int) -> Optional[int]:
        """Return the index of the first slot belonging to *quotient*'s run.

        Algorithm
        ---------
        1. Walk left from *quotient* to locate the cluster start.
        2. Count how many occupied quotients lie *before* ours inside that
           cluster — each one contributes a preceding run.
        3. Starting from the cluster start, walk right and count run-end
           markers; after skipping past that many complete runs the next
           slot is where our run begins.

        Returns *None* when ``is_occupied[quotient]`` is ``False``.
        """
        q = quotient % self.size
        if not self.is_occupied[q]:
            return None

        cluster_start = self._find_cluster_start(q)

        # Fast path: quotient *is* the cluster start, so its run starts here.
        if cluster_start == q:
            return q

        # Count occupied quotients in [cluster_start, q)  (exclusive of q).
        num_prior = 0
        pos = cluster_start
        while pos != q:
            if self.is_occupied[pos]:
                num_prior += 1
            pos = (pos + 1) % self.size

        # Skip past *num_prior* complete runs by counting run-end markers.
        pos = (cluster_start + 1) % self.size
        ended = 0
        for _ in range(self.size):
            if ended >= num_prior:
                break
            if self.is_runend[pos]:
                ended += 1
            pos = (pos + 1) % self.size

        return pos

    def _find_run_end(self, quotient: int) -> Optional[int]:
        """Return the index of the last slot of *quotient*'s run."""
        start = self._find_run_start(quotient)
        if start is None:
            return None
        pos = start
        for _ in range(self.size):
            if self.is_runend[pos]:
                return pos
            pos = (pos + 1) % self.size
        return start  # safety fallback — should not happen

    def _find_first_empty(self, start: int) -> int:
        """Return the nearest empty slot at or after *start*."""
        pos = start % self.size
        for _ in range(self.size):
            if self._is_slot_empty(pos):
                return pos
            pos = (pos + 1) % self.size
        raise RuntimeError("CQF is full")

    # --------------------------------------------------- shifting
    def _shift_slots_right(self, from_pos: int, to_pos: int):
        """Shift slot data one position to the right over [from_pos … to_pos).

        *to_pos* must be an empty slot.  After the shift a gap is opened at
        *from_pos*.

        The remainder, count, **and** run-end flag for each slot move together
        because they describe the element stored in that slot.  The
        ``is_occupied`` flag is **not** shifted — it is a property of the
        quotient index, not of the physical slot.
        """
        pos = to_pos
        while pos != from_pos:
            prev = (pos - 1) % self.size
            self.remainders[pos] = self.remainders[prev]
            self.counts[pos] = self.counts[prev]
            pos = prev

        self.remainders[from_pos] = 0
        self.counts[from_pos] = 0
        self.is_runend[from_pos] = False

    # -------------------------------------------------------- core insert
    def _insert_internal(self, q: int, r: int, count: int):
        q = q % self.size
        self.n_total += count

        if not self.is_occupied[q]:
            # Brand-new quotient — start a new run.
            self.is_occupied[q] = True
            self.n_distinct += 1

            if self._is_slot_empty(q):
                # Canonical slot is free.
                self.remainders[q] = r
                self.counts[q] = count
                self.is_runend[q] = True
                return

            # Canonical slot holds shifted data from another run.
            # Find the correct insertion point for the new single-element run.
            insert_pos = self._find_run_start(q)
            empty = self._find_first_empty(insert_pos)
            if empty != insert_pos:
                self._shift_slots_right(insert_pos, empty)

            self.remainders[insert_pos] = r
            self.counts[insert_pos] = count
            self.is_runend[insert_pos] = True
            return

        # Quotient already present — locate the existing run.
        run_start = self._find_run_start(q)
        run_end = self._find_run_end(q)

        # Walk the run (remainders are sorted ascending) looking for r.
        pos = run_start
        insert_before = None

        while True:
            if self.remainders[pos] == r:
                # Already present — add to count.
                self.counts[pos] += count
                return
            if self.remainders[pos] > r:
                insert_before = pos
                break
            if pos == run_end:
                # r is larger than everything in the run — append.
                insert_before = (run_end + 1) % self.size
                break
            pos = (pos + 1) % self.size

        # New distinct element.
        self.n_distinct += 1
        empty = self._find_first_empty(insert_before)
        if empty != insert_before:
            self._shift_slots_right(insert_before, empty)

        self.remainders[insert_before] = r
        self.counts[insert_before] = count

        if insert_before == (run_end + 1) % self.size:
            # Appended at the end of the run — this is the new run-end.
            self.is_runend[insert_before] = True
            self.is_runend[run_end] = False
        else:
            # Inserted in the middle — not a run-end.
            self.is_runend[insert_before] = False

    # ------------------------------------------------------- public API
    def insert(self, item, count: int = 1):
        """Insert *item* with *count* occurrences (default 1).

        If *item* already exists its count is incremented by *count*.
        """
        if count <= 0:
            return
        q, r = self._hash(item)
        self._insert_internal(q, r, count)

    def insert_raw(self, quotient: int, remainder: int, count: int):
        """Insert using a pre-computed quotient/remainder (skips hashing)."""
        if count <= 0:
            return
        self._insert_internal(quotient, remainder, count)

    def query(self, item) -> int:
        """Return the count stored for *item* (0 if absent)."""
        q, r = self._hash(item)
        q = q % self.size
        if not self.is_occupied[q]:
            return 0

        run_start = self._find_run_start(q)
        if run_start is None:
            return 0

        pos = run_start
        for _ in range(self.size):
            if self.remainders[pos] == r:
                return self.counts[pos]
            if self.remainders[pos] > r or self.is_runend[pos]:
                return 0
            pos = (pos + 1) % self.size
        return 0

    def delete(self, item, count: int = 1):
        """Decrement *item*'s count by *count*.

        If the stored count drops to zero the element is logically removed
        (its slot becomes a dead entry; compaction is not performed).
        """
        q, r = self._hash(item)
        q = q % self.size
        if not self.is_occupied[q]:
            return

        run_start = self._find_run_start(q)
        if run_start is None:
            return

        pos = run_start
        for _ in range(self.size):
            if self.remainders[pos] == r:
                removed = min(count, self.counts[pos])
                self.counts[pos] -= removed
                self.n_total -= removed
                if self.counts[pos] <= 0:
                    self.counts[pos] = 0
                    self.n_distinct -= 1
                return
            if self.remainders[pos] > r or self.is_runend[pos]:
                return
            pos = (pos + 1) % self.size

    # --------------------------------------------------------- iteration
    def __iter__(self) -> Iterator[Tuple[int, int, int]]:
        """Yield ``(quotient, remainder, count)`` for every live entry."""
        for q in range(self.size):
            if not self.is_occupied[q]:
                continue
            run_start = self._find_run_start(q)
            if run_start is None:
                continue
            pos = run_start
            for _ in range(self.size):
                if self.counts[pos] > 0:
                    yield (q, self.remainders[pos], self.counts[pos])
                if self.is_runend[pos]:
                    break
                pos = (pos + 1) % self.size

    # ------------------------------------------------------------- merge
    def merge(self, other: "CQF") -> "CQF":
        """Return a new CQF containing the union of *self* and *other*.

        For elements present in both filters the counts are **summed**
        (multiset union semantics).  Both operands must share the same
        ``q_bits``, ``r_bits``, and ``seed``.
        """
        assert self.q_bits == other.q_bits and self.r_bits == other.r_bits
        assert self.seed == other.seed

        result = CQF(self.q_bits, self.r_bits, self.seed)
        entries: dict = {}

        for q, r, c in self:
            entries[(q, r)] = entries.get((q, r), 0) + c

        for q, r, c in other:
            key = (q, r)
            if key in entries:
                entries[key] = max(entries[key], c)
            else:
                entries[key] = c

        for (q, r), c in sorted(entries.items()):
            result.insert_raw(q, r, c)

        return result

    # ------------------------------------------------------------ resize
    def resize(self):
        """Double the slot count by stealing one bit from the remainder.

        After resizing ``q_bits`` increases by 1, ``r_bits`` decreases by 1,
        and the slot array doubles in length.

        For each existing element with old quotient *q* and old remainder *r*
        the new fingerprint is computed as::

            new_quotient  = (q << 1) | (r >> (old_r_bits - 1))
            new_remainder = r & ((1 << new_r_bits) - 1)

        i.e. the most-significant bit of the old remainder becomes the new
        least-significant bit of the quotient.
        """
        assert self.r_bits > 1, "Cannot resize: r_bits would become 0"

        old_entries = list(self)
        old_r_bits = self.r_bits

        self.q_bits += 1
        self.r_bits -= 1
        self.size = 1 << self.q_bits
        self.r_mask = (1 << self.r_bits) - 1

        self.remainders = [0] * self.size
        self.counts = [0] * self.size
        self.is_occupied = [False] * self.size
        self.is_runend = [False] * self.size
        self.n_distinct = 0
        self.n_total = 0

        for old_q, old_r, count in old_entries:
            new_q = old_q * 2
            new_r = old_r & self.r_mask
            self.insert_raw(new_q, new_r, count)

    # ------------------------------------------------ vector operations
    def inner_product(self, other: "CQF") -> int:
        """Dot product: ``sum(count_self[x] * count_other[x])`` over all *x*.

        Only elements present in both filters contribute.
        """
        assert self.q_bits == other.q_bits and self.r_bits == other.r_bits
        assert self.seed == other.seed

        other_map: dict = {}
        for q, r, c in other:
            other_map[(q, r)] = c

        total = 0
        for q, r, c_self in self:
            c_other = other_map.get((q, r), 0)
            total += min(c_self, c_other)

        return total

    def magnitude_squared(self) -> int:
        """L₂ norm squared: sum of squares of all counts."""
        return sum(c * c for _, _, c in self)

    def cosine_similarity(self, other: "CQF") -> float:
        """Cosine similarity between two CQFs viewed as count vectors."""
        ip = self.inner_product(other)
        mag_a = self.magnitude_squared()
        mag_b = other.magnitude_squared()
        if mag_a == 0 or mag_b == 0:
            return 0.0
        return ip / math.sqrt(mag_a * mag_b)
