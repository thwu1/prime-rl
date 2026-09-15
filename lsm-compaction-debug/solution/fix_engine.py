#!/usr/bin/env python3
"""
Fix the LSM-tree storage engine.

Fixes applied:
1. Compaction merge deduplication — keep only the newest value per key by
   processing older (target-level) entries before newer (source-level) entries
   and using a dict for last-write-wins.
2. Tombstone propagation — only drop tombstones when compacting into the
   bottommost level (no SSTables in any deeper level).
3. BloomFilter — implement with optimal bit-array sizing, multiple hash
   functions via double hashing (MD5 + SHA-1), and struct-based serialization.
4. Compaction scoring — score = current_tables / max_tables per level.
5. Bloom-filter integration in get() — skip SSTables whose bloom filter
   rejects the queried key.
"""

import math

# ---------------------------------------------------------------------------
# Compute optimal bloom-filter parameters to embed in the generated code.
# Formula: m = -n * ln(p) / (ln2)^2 ;  k = (m / n) * ln2
# ---------------------------------------------------------------------------

def _bloom_params(n, p):
    m = int(-n * math.log(p) / (math.log(2) ** 2))
    k = max(1, round((m / max(n, 1)) * math.log(2)))
    return max(m, 64), k


# Quick sanity check
m1000, k1000 = _bloom_params(1000, 0.01)
print(f"Bloom params for n=1000, p=0.01 → m={m1000} bits, k={k1000} hashes")
assert 8000 < m1000 < 12000, f"unexpected m={m1000}"
assert 5 <= k1000 <= 9, f"unexpected k={k1000}"

# ---------------------------------------------------------------------------
# Write the corrected engine to /app/lsm_engine.py
# ---------------------------------------------------------------------------

FIXED_CODE = r'''"""
LSM-Tree Storage Engine
=======================
A Log-Structured Merge-Tree implementation with leveled compaction.

Architecture:
- Memtable: in-memory sorted buffer (Python dict)
- SSTables: immutable sorted files on disk (JSON format)
- Levels: L0 (unsorted, may overlap), L1+ (sorted, non-overlapping)
- Compaction: merges SSTables across levels to maintain size invariants

Level sizing:
- L0 allows up to 4 SSTables before triggering compaction
- L1+ target: level_size_ratio ^ level SSTables per level
"""

import os
import json
import math
import struct
import hashlib
import base64
from typing import Optional, List, Tuple, Dict
from bisect import bisect_left

TOMBSTONE = "__TOMBSTONE__"


class BloomFilter:
    """Probabilistic set membership filter using a bit array and double hashing."""

    def __init__(self, expected_items: int, fp_rate: float = 0.01):
        self.expected_items = max(expected_items, 1)
        self.fp_rate = fp_rate
        # Optimal sizing: m = -n*ln(p) / (ln2)^2,  k = (m/n)*ln2
        self.num_bits = max(
            int(-self.expected_items * math.log(fp_rate) / (math.log(2) ** 2)),
            64,
        )
        self.num_hashes = max(
            1, round((self.num_bits / self.expected_items) * math.log(2))
        )
        self.bit_array = bytearray((self.num_bits + 7) // 8)

    def _hashes(self, key: str) -> List[int]:
        raw = key.encode("utf-8")
        h1 = int.from_bytes(hashlib.md5(raw).digest()[:8], "big")
        h2 = int.from_bytes(hashlib.sha1(raw).digest()[:8], "big")
        return [(h1 + i * h2) % self.num_bits for i in range(self.num_hashes)]

    def add(self, key: str):
        for pos in self._hashes(key):
            self.bit_array[pos // 8] |= 1 << (pos % 8)

    def might_contain(self, key: str) -> bool:
        for pos in self._hashes(key):
            if not (self.bit_array[pos // 8] & (1 << (pos % 8))):
                return False
        return True

    def serialize(self) -> bytes:
        header = struct.pack(
            "!IIId", self.num_bits, self.num_hashes, self.expected_items, self.fp_rate
        )
        return header + bytes(self.bit_array)

    @classmethod
    def deserialize(cls, data: bytes) -> "BloomFilter":
        hdr = struct.calcsize("!IIId")
        num_bits, num_hashes, expected_items, fp_rate = struct.unpack(
            "!IIId", data[:hdr]
        )
        bf = object.__new__(cls)
        bf.expected_items = expected_items
        bf.fp_rate = fp_rate
        bf.num_bits = num_bits
        bf.num_hashes = num_hashes
        bf.bit_array = bytearray(data[hdr:])
        return bf


class SSTable:
    """Sorted String Table -- an immutable, sorted key-value file on disk."""

    def __init__(self, path: str, entries: List[Tuple[str, str]], level: int):
        self.path = path
        self.level = level
        self.entries = sorted(entries, key=lambda x: x[0])
        self.min_key = self.entries[0][0] if self.entries else ""
        self.max_key = self.entries[-1][0] if self.entries else ""
        self.bloom = BloomFilter(len(self.entries))
        for k, v in self.entries:
            self.bloom.add(k)
        self._write()

    def _write(self):
        bloom_bytes = self.bloom.serialize()
        with open(self.path, "w") as f:
            json.dump(
                {
                    "level": self.level,
                    "entries": self.entries,
                    "min_key": self.min_key,
                    "max_key": self.max_key,
                    "bloom_data": base64.b64encode(bloom_bytes).decode("ascii"),
                },
                f,
            )

    @classmethod
    def load(cls, path: str) -> "SSTable":
        with open(path, "r") as f:
            data = json.load(f)
        sst = object.__new__(cls)
        sst.path = path
        sst.level = data["level"]
        sst.entries = [tuple(e) for e in data["entries"]]
        sst.min_key = data["min_key"]
        sst.max_key = data["max_key"]
        bloom_raw = data.get("bloom_data", "")
        if bloom_raw:
            sst.bloom = BloomFilter.deserialize(base64.b64decode(bloom_raw))
        else:
            sst.bloom = BloomFilter(len(sst.entries))
            for k, v in sst.entries:
                sst.bloom.add(k)
        return sst

    def get(self, key: str) -> Optional[str]:
        keys = [e[0] for e in self.entries]
        idx = bisect_left(keys, key)
        if idx < len(self.entries) and self.entries[idx][0] == key:
            return self.entries[idx][1]
        return None

    def overlaps(self, min_key: str, max_key: str) -> bool:
        return self.min_key <= max_key and self.max_key >= min_key


class Memtable:
    """In-memory sorted write buffer backed by a Python dict."""

    def __init__(self, max_size: int = 1000):
        self.entries: Dict[str, str] = {}
        self.max_size = max_size

    def put(self, key: str, value: str):
        self.entries[key] = value

    def delete(self, key: str):
        self.entries[key] = TOMBSTONE

    def get(self, key: str) -> Optional[str]:
        return self.entries.get(key)

    def is_full(self) -> bool:
        return len(self.entries) >= self.max_size

    def flush(self) -> List[Tuple[str, str]]:
        entries = sorted(self.entries.items())
        self.entries.clear()
        return entries


class LSMEngine:
    """LSM-tree storage engine with leveled compaction."""

    def __init__(
        self,
        data_dir: str,
        memtable_size: int = 1000,
        level_size_ratio: int = 10,
        max_levels: int = 5,
    ):
        self.data_dir = data_dir
        self.memtable = Memtable(memtable_size)
        self.level_size_ratio = level_size_ratio
        self.max_levels = max_levels
        self.levels: List[List[SSTable]] = [[] for _ in range(max_levels)]
        self.sst_counter = 0
        self.stats = {"sstables_read": 0, "bloom_filter_negatives": 0}
        os.makedirs(data_dir, exist_ok=True)
        self._load_existing()

    def _load_existing(self):
        """Reload SSTable metadata from disk."""
        for fname in sorted(os.listdir(self.data_dir)):
            if fname.endswith(".sst"):
                path = os.path.join(self.data_dir, fname)
                sst = SSTable.load(path)
                if sst.level < self.max_levels:
                    self.levels[sst.level].append(sst)
                num = int(fname.split("_")[0])
                self.sst_counter = max(self.sst_counter, num + 1)

    def _next_sst_path(self) -> str:
        path = os.path.join(self.data_dir, f"{self.sst_counter:06d}_table.sst")
        self.sst_counter += 1
        return path

    def put(self, key: str, value: str):
        self.memtable.put(key, value)
        if self.memtable.is_full():
            self._flush()

    def delete(self, key: str):
        self.memtable.delete(key)
        if self.memtable.is_full():
            self._flush()

    def get(self, key: str) -> Optional[str]:
        # Check memtable first (most recent data)
        val = self.memtable.get(key)
        if val is not None:
            return None if val == TOMBSTONE else val

        # Search each level from newest to oldest
        for level in self.levels:
            for sst in reversed(level):
                # Use bloom filter to skip SSTables that cannot contain the key
                if not sst.bloom.might_contain(key):
                    self.stats["bloom_filter_negatives"] += 1
                    continue
                self.stats["sstables_read"] += 1
                val = sst.get(key)
                if val is not None:
                    return None if val == TOMBSTONE else val

        return None

    def _flush(self):
        """Flush memtable contents to a new L0 SSTable."""
        entries = self.memtable.flush()
        if not entries:
            return
        sst = SSTable(self._next_sst_path(), entries, level=0)
        self.levels[0].append(sst)
        self._maybe_compact()

    def _maybe_compact(self):
        """Trigger compaction for any level that exceeds its size limit."""
        for level in range(self.max_levels - 1):
            if len(self.levels[level]) > self._max_tables_for_level(level):
                self._compact_level(level)

    def _max_tables_for_level(self, level: int) -> int:
        """Maximum number of SSTables allowed at a given level."""
        if level == 0:
            return 4
        return self.level_size_ratio ** level

    def _compact_level(self, level: int):
        """Compact SSTables from level into level+1."""
        if level >= self.max_levels - 1:
            return

        target_level = level + 1

        # Select tables to compact from the source level
        if level == 0:
            tables_to_compact = list(self.levels[level])
        else:
            if not self.levels[level]:
                return
            tables_to_compact = [self.levels[level][0]]

        # Determine the key range being compacted
        min_key = min(t.min_key for t in tables_to_compact)
        max_key = max(t.max_key for t in tables_to_compact)

        # Find overlapping tables in the target level
        overlapping = [
            t for t in self.levels[target_level] if t.overlaps(min_key, max_key)
        ]

        # Merge entries: older data first so newer data overwrites in the dict
        all_entries = []
        for t in overlapping:          # target level — older
            all_entries.extend(t.entries)
        for t in tables_to_compact:    # source level — newer
            all_entries.extend(t.entries)

        all_entries.sort(key=lambda x: x[0])

        # Deduplicate: last-write-wins (newest entry for each key kept)
        deduped: Dict[str, str] = {}
        for k, v in all_entries:
            deduped[k] = v

        # Tombstones may only be dropped at the bottommost level
        is_bottommost = all(
            len(self.levels[l]) == 0
            for l in range(target_level + 1, self.max_levels)
        )
        if is_bottommost:
            final_entries = sorted(
                [(k, v) for k, v in deduped.items() if v != TOMBSTONE]
            )
        else:
            final_entries = sorted(deduped.items())

        # Split into fixed-size SSTables
        new_tables = []
        chunk_size = 500
        for i in range(0, max(len(final_entries), 1), chunk_size):
            chunk = final_entries[i : i + chunk_size]
            if chunk:
                sst = SSTable(self._next_sst_path(), chunk, level=target_level)
                new_tables.append(sst)

        # Remove old tables from their respective levels
        for t in tables_to_compact:
            self.levels[level].remove(t)
            if os.path.exists(t.path):
                os.remove(t.path)
        for t in overlapping:
            self.levels[target_level].remove(t)
            if os.path.exists(t.path):
                os.remove(t.path)

        # Install new tables
        self.levels[target_level].extend(new_tables)

        # Cascade compaction if the target level is now over capacity
        self._maybe_compact()

    def compact_all(self):
        """Force compaction of all levels, moving data downward."""
        for level in range(self.max_levels - 1):
            while len(self.levels[level]) > 0:
                self._compact_level(level)

    def get_compaction_scores(self) -> List[float]:
        """Return a compaction urgency score for each level.

        Score = current_table_count / max_tables_for_level.
        Higher scores indicate a more urgent need for compaction.
        """
        return [
            len(self.levels[level]) / self._max_tables_for_level(level)
            for level in range(self.max_levels)
        ]

    def range_query(self, start_key: str, end_key: str) -> List[Tuple[str, str]]:
        """Return all non-deleted key-value pairs in [start_key, end_key]."""
        results: Dict[str, str] = {}

        # Scan from deepest (oldest) to shallowest (newest)
        for level_idx in range(self.max_levels - 1, -1, -1):
            for sst in self.levels[level_idx]:
                if sst.overlaps(start_key, end_key):
                    for k, v in sst.entries:
                        if start_key <= k <= end_key:
                            results[k] = v

        # Memtable entries are the newest and take precedence
        for k, v in self.memtable.entries.items():
            if start_key <= k <= end_key:
                results[k] = v

        return sorted([(k, v) for k, v in results.items() if v != TOMBSTONE])

    def close(self):
        """Flush any remaining memtable data to disk."""
        if self.memtable.entries:
            self._flush()
'''

with open("/app/lsm_engine.py", "w") as f:
    f.write(FIXED_CODE)

print("LSM engine fixed successfully.")
