-- Benchmark database schema for tiled attention engine.
-- Create this database at /app/benchmarks.db using this DDL.

CREATE TABLE IF NOT EXISTS benchmark_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mask_type TEXT NOT NULL,
    batch_size INTEGER NOT NULL,
    num_heads INTEGER NOT NULL,
    seq_len INTEGER NOT NULL,
    head_dim INTEGER NOT NULL,
    tile_q INTEGER NOT NULL,
    tile_k INTEGER NOT NULL,
    naive_time_sec REAL NOT NULL,
    tiled_time_sec REAL NOT NULL,
    speedup REAL NOT NULL,
    max_output_error REAL NOT NULL,
    max_lse_error REAL NOT NULL,
    correct INTEGER NOT NULL CHECK(correct IN (0, 1))
);

CREATE TABLE IF NOT EXISTS mask_call_counts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mask_type TEXT NOT NULL,
    seq_len INTEGER NOT NULL,
    tile_q INTEGER NOT NULL,
    tile_k INTEGER NOT NULL,
    total_tile_pairs INTEGER NOT NULL,
    actual_mask_calls INTEGER NOT NULL,
    calls_saved INTEGER NOT NULL
);
