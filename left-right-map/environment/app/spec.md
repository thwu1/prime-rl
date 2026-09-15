# Concurrent Map System — Specification

## Base Map (`/app/left_right_map.py`)

The base implementation is a concurrent multi-value map using the left-right
concurrency pattern. Its correctness requirements are defined by the test suite
at `/app/tests/test_left_right.py`.

## Sharded Map (`/app/sharded_map.py`)

A sharded version that distributes keys across N independent left-right map
instances.

### `ShardedMap.new(num_shards: int) -> Tuple[ShardedWriteHandle, ShardedReadHandle]`

Create a sharded map with `num_shards` independent left-right map instances.

### ShardedWriteHandle

| Method                      | Description                                    |
|-----------------------------|------------------------------------------------|
| `insert(key, value)`       | Route key to its shard and insert              |
| `remove_value(key, value)` | Route key to its shard and remove value        |
| `remove_entry(key)`        | Route key to its shard and remove entry        |
| `clear()`                  | Clear all shards                               |
| `publish()`                | Publish all shards                             |
| `shard_for_key(key) -> int`| Return the shard index for a key (0-indexed)   |
| `has_pending() -> bool`    | True if any shard has pending operations       |
| `destroy()`                | Destroy all shards                             |

### ShardedReadHandle

| Method                          | Description                              |
|---------------------------------|------------------------------------------|
| `get(key) -> Optional[List]`   | Route key to its shard and get values    |
| `contains_key(key) -> bool`    | Check if key exists in its shard         |
| `len() -> int`                 | Total key count across all shards        |
| `keys() -> List`               | All keys across all shards               |
| `shard_lens() -> Dict[int, int]` | Key count per shard (shard_id -> count)|
| `clone() -> ShardedReadHandle` | Clone all per-shard readers              |

### Design requirements

- `shard_for_key` must be deterministic: the same key always maps to the same
  shard for a given `num_shards`.
- Shard index must be in `[0, num_shards)`.
- `publish()` must publish each shard's pending writes.
- `get()` returns a copy of the value list, not a reference to internal state.

## Required Output Artifacts (`/app/output/`)

For each workload in `/app/workloads.json` and each shard count in
`[1, 2, 4, 8, 16]`, produce the following:

### Profile data files

`/app/output/<workload_name>_<num_shards>.prof` — Binary Python profile data
loadable by the `pstats` module, containing function-level timing and call
count information.

### Benchmark database (`/app/output/bench.db`)

SQLite database with the following schema:

```sql
CREATE TABLE workload_results (
    workload_name TEXT,
    num_shards INTEGER,
    total_ops INTEGER,
    elapsed_seconds REAL,
    throughput_ops_per_sec REAL
);

CREATE TABLE shard_distribution (
    workload_name TEXT,
    num_shards INTEGER,
    shard_id INTEGER,
    key_count INTEGER
);

CREATE TABLE profile_stats (
    workload_name TEXT,
    num_shards INTEGER,
    function_name TEXT,
    cumulative_time REAL,
    call_count INTEGER
);

CREATE TABLE memory_snapshots (
    workload_name TEXT,
    num_shards INTEGER,
    peak_memory_bytes INTEGER
);
```

### Performance analysis report (`/app/output/report.json`)

```json
{
    "workloads": {
        "<workload_name>": {
            "shard_counts_tested": [1, 2, 4, 8, 16],
            "throughput": {"1": "<float>", "2": "<float>", "...": ""},
            "distribution_cv": {"1": "<float>", "2": "<float>", "...": ""},
            "peak_memory_bytes": {"1": "<int>", "2": "<int>", "...": ""}
        }
    },
    "optimal_shard_count": "<int>",
    "recommendation": "<justification string, at least 50 characters>",
    "crossover_analysis": "<analysis string, at least 50 characters>"
}
```

- `distribution_cv` = coefficient of variation of key counts across shards
  (standard deviation / mean). For `num_shards=1`, this is `0.0`.
- `optimal_shard_count` = the shard count that provides the best trade-off
  between throughput and distribution balance across all workloads.
- `recommendation` = a written justification for the chosen shard count.
- `crossover_analysis` = description of when adding more shards helps vs. hurts,
  with reference to the measured data.

## Workload Execution

For each workload, generate an operation sequence based on its parameters:
- Key selection follows the specified `key_distribution`
- Operations are reads (with probability `read_fraction`) or writes
- Publish periodically during execution to make writes visible

## Workload Format (`/app/workloads.json`)

Each workload entry has:
- `name`: string identifier
- `num_keys`: size of the key space
- `num_operations`: total operations to execute
- `read_fraction`: fraction of reads (0.0 to 1.0)
- `key_distribution`: `"uniform"`, `"zipf"`, or `"hotspot"`
- `seed`: random seed for reproducibility

For `"zipf"` distribution, `zipf_alpha` controls skewness (higher = more skewed).
For `"hotspot"` distribution, `hot_fraction` is the fraction of keys that are hot
and `hot_weight` is the probability of accessing a hot key.
