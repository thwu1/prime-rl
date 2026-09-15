CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    command TEXT,
    filepath TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    sample_index INTEGER NOT NULL,
    wall_time_ns REAL NOT NULL,
    cpu_cycles REAL NOT NULL,
    cache_misses REAL NOT NULL,
    peak_rss_bytes REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS metric_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL REFERENCES runs(id),
    metric_name TEXT NOT NULL,
    mean REAL NOT NULL,
    median REAL NOT NULL,
    std_dev REAL NOT NULL,
    q1 REAL NOT NULL,
    q3 REAL NOT NULL,
    n INTEGER NOT NULL,
    outlier_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS comparisons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    baseline_run_id INTEGER NOT NULL REFERENCES runs(id),
    candidate_run_id INTEGER NOT NULL REFERENCES runs(id),
    metric_name TEXT NOT NULL,
    mean_diff REAL NOT NULL,
    pct_change REAL NOT NULL,
    p_value_raw REAL NOT NULL,
    p_value_adjusted REAL NOT NULL,
    effect_size REAL NOT NULL,
    effect_size_class TEXT NOT NULL,
    ci_lower REAL NOT NULL,
    ci_upper REAL NOT NULL,
    verdict TEXT NOT NULL
);
