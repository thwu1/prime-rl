A broken LSM-tree compaction engine is at `/app/`. It reads SSTable data files, merges them with conflict resolution, and selects compaction candidates using Size-Tiered (STCS) and Leveled (LCS) strategies. Build and run: `cd /app && ./build.sh && java -cp bin compaction.Main <command> <config.properties>`.

Commands: `merge`, `select-stcs`, `select-lcs`.

**SSTable format**: Tab-separated text. Line 1: `#META level=<int> created_at=<long> size_bytes=<long> first_key=<str> last_key=<str> read_hotness=<double>`. Lines 2+: `key\ttimestamp\ttype\tvalue\tttl` sorted by key. Types: `V` (value), `D` (tombstone), `T` (TTL value expiring at `timestamp + ttl`).

**Config format**: `key=value` per line. Keys: `sstables` (comma-separated paths to merge), `all_sstables` (all SSTables in system), `gc_grace_seconds`, `current_time`, `output`, `stcs.bucket_high`, `stcs.bucket_low`, `stcs.min_sstable_size`, `stcs.min_threshold`, `stcs.max_threshold`, `lcs.max_sstable_size_mb`, `lcs.fanout_size`.

**Merge semantics**: For each key, highest timestamp wins. A `T` entry where `timestamp + ttl <= current_time` becomes an implicit `D` tombstone at effective timestamp `timestamp + ttl`; this effective timestamp is used for both conflict resolution and gc_grace calculation. Tombstones shadow lower-timestamp values. A tombstone is purgeable (omitted from output) only if `current_time - effective_timestamp >= gc_grace_seconds` AND every SSTable in `all_sstables` whose key range covers that key is included in the merge set. Non-purgeable tombstones must appear in output. On timestamp tie, `D` takes precedence over `V`/`T`.

**STCS selection** (stdout: one selected path per line): Sort SSTables by size. Iterate sorted list; for each, find a bucket whose average satisfies `size > avg * bucket_low AND size < avg * bucket_high`, OR both `size < min_sstable_size` and `avg < min_sstable_size`. If found, add to that bucket and update average; otherwise create a new bucket. From buckets with `>= min_threshold` SSTables, select the one with highest total `read_hotness`. Trim to `max_threshold` by sorting descending by `read_hotness` and keeping the hottest.

**LCS selection** (stdout: one selected path per line): For levels 1..N (scanning highest level first), compute `score = total_level_bytes / max_bytes(level)` where `max_bytes(0) = 4 * max_sstable_size_bytes` and `max_bytes(i) = fanout^i * max_sstable_size_bytes`. Pick the first (highest) level with `score > 1.001`. From that level, select the SSTable with the lexicographically smallest `first_key`. Add all SSTables from the next level whose key range overlaps the candidate's range. Output the combined set.

All bugs are in the Java source files. Fix them to pass the verification tests.
