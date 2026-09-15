# Data Format Reference

## Directory Structure

```
/app/data/
├── meta.json
├── experiment.db
└── {fuzzer}/
    └── {benchmark}/
        └── trial_{NN}/
            └── coverage.cov      (FCOV benchmarks only)
```

## meta.json

```json
{
  "fuzzers": ["fuzzer1", ...],
  "benchmarks": ["bench1", ...],
  "trials": <int>,
  "snapshots_seconds": [t1, t2, ...],
  "edge_space": <int>,
  "fcov_benchmarks": ["bench_a", "bench_b"],
  "db_benchmarks": ["bench_c", "bench_d"],
  "db_path": "/app/data/experiment.db"
}
```

Note: Tversky-index parameters (`tversky_alpha`, `tversky_beta`) are stored
exclusively in the SQLite experiment database, not in `meta.json`.

## Binary Coverage File Format (`.cov`)

Used for benchmarks listed in `fcov_benchmarks`. All integer fields are
**unsigned 32-bit little-endian**. Each file stores **cumulative** edge
coverage at each snapshot — the edge set at snapshot time T contains all
edges discovered from the start of the trial up through time T.

### Header (16 bytes)

| Offset | Field          | Type     | Description                        |
|--------|----------------|----------|------------------------------------|
| 0      | magic          | char[4]  | `"FCOV"` (0x46 0x43 0x4F 0x56)    |
| 4      | version        | uint32   | Format version (must be `1`)       |
| 8      | edge_space     | uint32   | Total possible edges (N)           |
| 12     | num_snapshots  | uint32   | Number of time snapshots (S)       |

### Followed by S snapshot entries, each:

| Offset | Field     | Type      | Description                             |
|--------|-----------|-----------|-----------------------------------------|
| 0      | timestamp | uint32    | Snapshot time in seconds                |
| 4      | num_edges | uint32    | Number of covered edges (K)             |
| 8      | edges     | uint32[K] | Covered edge indices, sorted ascending  |

Edge indices are zero-based integers in `[0, N)`.

## SQLite Database (experiment.db)

Used for benchmarks listed in `db_benchmarks` and for experiment configuration.
Inspect with `sqlite3 /app/data/experiment.db`.

### Tables

**config** — Experiment parameters as key-value pairs:
```sql
CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT);
```

**coverage** — Edge coverage observations:
```sql
CREATE TABLE coverage (
    benchmark TEXT NOT NULL,
    fuzzer TEXT NOT NULL,
    trial INTEGER NOT NULL,
    snapshot_time INTEGER NOT NULL,
    edge_id INTEGER NOT NULL
);
```

Note: The FCOV binary format stores cumulative coverage at each snapshot.
The semantics of the SQLite coverage data may differ — inspect the data
to determine the correct query strategy for reconstructing coverage sets.
