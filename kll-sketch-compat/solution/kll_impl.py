#!/usr/bin/env python3
"""KLL Doubles Sketch — from-scratch implementation with Apache DataSketches binary format compatibility.

Implements the KLL quantile sketch algorithm (Karnin, Lang, Liberty 2016) with the
exact binary serialization format used by the Apache DataSketches C++/Python libraries,
enabling cross-library interoperability.
"""


import struct
import math

# ── Binary format constants ──────────────────────────────────────────

_FAMILY = 15          # KLL family ID in DataSketches
_SER_V1 = 1           # serial version for empty and full sketches
_SER_V2 = 2           # serial version for single-item sketches
_PRE_SHORT = 2        # preamble ints for empty / single-item (8 bytes)
_PRE_FULL = 5         # preamble ints for multi-item (20 bytes)
_DEFAULT_K = 200
_DEFAULT_M = 8

# Flag bits (byte 3 of preamble)
_F_EMPTY = 0x01
_F_SORTED = 0x02      # IS_LEVEL_ZERO_SORTED
_F_SINGLE = 0x04      # IS_SINGLE_ITEM

# Binary format layout for full sketch (20-byte preamble):
#   byte  0:    preamble_ints (5)
#   byte  1:    serial_version (1)
#   byte  2:    family (15)
#   byte  3:    flags
#   bytes 4-5:  k (uint16 LE)
#   byte  6:    m (uint8)
#   byte  7:    reserved (0)
#   bytes 8-15: n (uint64 LE)
#   bytes 16-17: min_k (uint16 LE)
#   byte  18:   num_levels (uint8)
#   byte  19:   reserved (0)
# Then: levels array (num_levels × uint32 LE)
# Then: min_value (float64 LE)
# Then: max_value (float64 LE)
# Then: retained items (num_retained × float64 LE)


# ── Capacity helpers (must match DataSketches integer arithmetic) ─────

def _icap(k, depth):
    """Compute level capacity at given depth: approximately ceil(k * (2/3)^depth).

    Uses the exact integer formula from DataSketches C++:
        result = (2*k * 2^depth / 3^depth + 1) / 2   (integer division)
    Handles large depths by splitting the computation.
    """
    if depth == 0:
        return k
    if depth <= 30:
        return (2 * k * (1 << depth) // (3 ** depth) + 1) >> 1
    h = depth // 2
    return _icap(_icap(k, h), depth - h)


def _lcap(k, nl, lv, m):
    """Level capacity for level `lv` when there are `nl` levels total."""
    return max(m, _icap(k, nl - 1 - lv))


# ── KLL Doubles Sketch ───────────────────────────────────────────────

class KllDoublesSketch:
    """KLL quantile sketch for float64 values with DataSketches binary format support."""

    __slots__ = ("_k", "_m", "_n", "_mk", "_mn", "_mx",
                 "_nl", "_lvls", "_odd", "_lzs")

    def __init__(self, k=_DEFAULT_K):
        k = int(k)
        if not 8 <= k <= 65535:
            raise ValueError(f"k must be in [8, 65535], got {k}")
        self._k = k
        self._m = _DEFAULT_M
        self._n = 0
        self._mk = k           # min_k (tracks smallest k across merges)
        self._mn = float("inf")  # min value
        self._mx = float("-inf") # max value
        self._nl = 1            # num_levels
        self._lvls = [[]]       # per-level item lists
        self._odd = [False]     # compaction direction per level
        self._lzs = False       # level-zero-sorted flag

    # ── read-only properties ────────────────────────────────

    @property
    def n(self):
        return self._n

    @property
    def min_value(self):
        return self._mn

    @property
    def max_value(self):
        return self._mx

    @property
    def is_empty(self):
        return self._n == 0

    @property
    def k(self):
        return self._k

    @property
    def is_estimation_mode(self):
        return self._nl > 1

    @property
    def num_retained(self):
        return sum(len(lv) for lv in self._lvls)

    # ── update ──────────────────────────────────────────────

    def update(self, value):
        """Insert a float64 value. NaN values are silently ignored."""
        value = float(value)
        if math.isnan(value):
            return
        if self._n == 0:
            self._mn = self._mx = value
        else:
            if value < self._mn:
                self._mn = value
            if value > self._mx:
                self._mx = value
        self._n += 1
        self._lvls[0].append(value)
        self._lzs = False
        if len(self._lvls[0]) >= _lcap(self._k, self._nl, 0, self._m):
            self._compress()

    # ── compaction engine ───────────────────────────────────

    def _add_level(self):
        self._nl += 1
        self._lvls.append([])
        self._odd.append(False)

    def _compact(self, lv):
        """Sort items at level `lv`, promote every other item to level lv+1."""
        items = self._lvls[lv]
        items.sort()
        if lv == 0:
            self._lzs = True
        start = 1 if self._odd[lv] else 0
        self._odd[lv] = not self._odd[lv]
        survivors = items[start::2]
        self._lvls[lv] = []
        self._lvls[lv + 1].extend(survivors)

    def _compress(self):
        """Compact the lowest overflowing level; cascade upward as needed."""
        while True:
            found = False
            for lv in range(self._nl):
                if len(self._lvls[lv]) >= _lcap(self._k, self._nl, lv, self._m):
                    if lv == self._nl - 1:
                        self._add_level()
                    self._compact(lv)
                    found = True
                    break   # restart from level 0 after each compaction
            if not found:
                break

    # ── quantile / rank queries ─────────────────────────────

    def _weighted_items(self):
        """Return list of (value, weight) for all retained items."""
        out = []
        for lv in range(self._nl):
            w = 1 << lv
            for v in self._lvls[lv]:
                out.append((v, w))
        return out

    def get_quantile(self, rank):
        """Return the approximate value at the given normalized rank in [0, 1]."""
        if self._n == 0:
            raise ValueError("sketch is empty")
        rank = float(rank)
        if rank <= 0.0:
            return self._mn
        if rank >= 1.0:
            return self._mx
        items = sorted(self._weighted_items())
        if not items:
            return self._mn
        total = sum(w for _, w in items)
        target = rank * total
        cumul = 0.0
        for v, w in items:
            cumul += w
            if cumul > target:
                return v
        return items[-1][0]

    def get_rank(self, value):
        """Return the approximate fraction of items strictly less than `value`."""
        if self._n == 0:
            raise ValueError("sketch is empty")
        value = float(value)
        total = 0
        below = 0
        for lv in range(self._nl):
            w = 1 << lv
            for v in self._lvls[lv]:
                total += w
                if v < value:
                    below += w
        return below / total

    # ── merge ───────────────────────────────────────────────

    def merge(self, other):
        """Merge another KllDoublesSketch into this one."""
        if other.is_empty:
            return
        if self.is_empty:
            self._mn = other._mn
            self._mx = other._mx
        else:
            if other._mn < self._mn:
                self._mn = other._mn
            if other._mx > self._mx:
                self._mx = other._mx
        self._n += other._n
        self._mk = min(self._mk, other._mk)
        # extend level structure
        while self._nl < other._nl:
            self._add_level()
        # copy items level-by-level
        for lv in range(other._nl):
            self._lvls[lv].extend(list(other._lvls[lv]))
        # compact overflowing levels
        self._compress()

    # ── serialize (DataSketches binary format) ──────────────

    def serialize(self):
        """Serialize to Apache DataSketches KLL doubles binary format."""
        if self._n == 0:
            # Empty: 8 bytes. serial_version=1, flags=IS_EMPTY
            return struct.pack("<BBBBHBB",
                               _PRE_SHORT, _SER_V1, _FAMILY,
                               _F_EMPTY,
                               self._k, self._m, 0)

        if self._n == 1:
            # Single item: 16 bytes. serial_version=2, flags=IS_SINGLE_ITEM
            hdr = struct.pack("<BBBBHBB",
                              _PRE_SHORT, _SER_V2, _FAMILY,
                              _F_SINGLE,
                              self._k, self._m, 0)
            return hdr + struct.pack("<d", self._mn)

        # ── full (multi-item) sketch ──
        # serial_version=1, no IS_DOUBLES flag
        flags = 0
        if self._lzs:
            flags |= _F_SORTED

        # Compute the flat-array levels index matching DataSketches layout.
        # The reference deserializer allocates total_capacity items and
        # expects num_retained = total_capacity - levels[0].
        nr = self.num_retained
        total_cap = sum(_lcap(self._k, self._nl, lv, self._m)
                        for lv in range(self._nl))

        # Build levels array (num_levels entries — start index of each level)
        la = [0] * self._nl
        la[0] = total_cap - nr     # first used index in level 0
        for lv in range(1, self._nl):
            la[lv] = la[lv - 1] + len(self._lvls[lv - 1])

        # preamble (20 bytes = 5 ints)
        #   bytes 0-7:   pre_ints, ser_ver, family, flags, k, m, reserved(0)
        #   bytes 8-15:  n
        #   bytes 16-19: min_k, num_levels, reserved(0)
        buf = struct.pack("<BBBBHBB",
                          _PRE_FULL, _SER_V1, _FAMILY, flags,
                          self._k, self._m, 0)
        buf += struct.pack("<Q", self._n)
        buf += struct.pack("<HBB", self._mk, self._nl, 0)

        # levels array: num_levels × uint32
        for i in range(self._nl):
            buf += struct.pack("<I", la[i])

        # min and max values
        buf += struct.pack("<dd", self._mn, self._mx)

        # retained items in flat-array order (level 0, then level 1, ...)
        for v in self._lvls[0]:
            buf += struct.pack("<d", v)
        for lv in range(1, self._nl):
            for v in self._lvls[lv]:
                buf += struct.pack("<d", v)

        return buf

    # ── deserialize (DataSketches binary format) ────────────

    @classmethod
    def deserialize(cls, data):
        """Deserialize from Apache DataSketches KLL doubles binary format."""
        p = 0
        # First 8 bytes: pre_ints, ser_ver, family, flags, k, m, reserved
        pi, sv, fam, fl, k, m, _ = struct.unpack_from("<BBBBHBB", data, p)
        p += 8

        if fam != _FAMILY:
            raise ValueError(f"not a KLL sketch (family={fam})")

        sk = cls.__new__(cls)
        sk._k = k
        sk._m = m
        sk._mk = k
        sk._lzs = bool(fl & _F_SORTED)

        # ── empty ──
        if fl & _F_EMPTY:
            sk._n = 0
            sk._mn = float("inf")
            sk._mx = float("-inf")
            sk._nl = 1
            sk._lvls = [[]]
            sk._odd = [False]
            return sk

        # ── single item ──
        if fl & _F_SINGLE:
            val = struct.unpack_from("<d", data, p)[0]
            sk._n = 1
            sk._mn = sk._mx = val
            sk._nl = 1
            sk._lvls = [[val]]
            sk._odd = [False]
            return sk

        # ── full (multi-item) sketch ──
        # bytes 8-15: n
        n = struct.unpack_from("<Q", data, p)[0]
        p += 8
        # bytes 16-19: min_k (2), num_levels (1), reserved (1)
        mk, nl, _ = struct.unpack_from("<HBB", data, p)
        p += 4

        sk._n = n
        sk._nl = nl
        sk._mk = mk

        # levels array: num_levels × uint32 (start index of each level)
        la = []
        for _ in range(nl):
            la.append(struct.unpack_from("<I", data, p)[0])
            p += 4

        # min and max
        sk._mn = struct.unpack_from("<d", data, p)[0]
        p += 8
        sk._mx = struct.unpack_from("<d", data, p)[0]
        p += 8

        # read retained items (rest of data)
        num_retained = (len(data) - p) // 8
        raw = []
        for _ in range(num_retained):
            raw.append(struct.unpack_from("<d", data, p)[0])
            p += 8

        # split into per-level lists using levels array boundaries
        sk._lvls = []
        idx = 0
        for lv in range(nl):
            if lv < nl - 1:
                cnt = la[lv + 1] - la[lv]
            else:
                # last level: remaining items
                cnt = num_retained - idx
            sk._lvls.append(raw[idx : idx + cnt])
            idx += cnt

        sk._odd = [False] * nl
        return sk
