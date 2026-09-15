#!/usr/bin/env python3
"""Generate deterministic synthetic fuzzer coverage data for novelty coverage analysis task.

Produces coverage data in two formats:
- FCOV binary files for bloaty_fuzz_target and freetype2_ftfuzzer (cumulative edges)
- SQLite database for harfbuzz_shaping and libpng_read_fuzzer (incremental edges per interval)
Also stores experiment configuration in the SQLite database.
"""

import random
import struct
import os
import json
import sqlite3

FUZZERS = ["aflpp", "centipede", "libafl", "libfuzzer"]
BENCHMARKS = ["bloaty_fuzz_target", "freetype2_ftfuzzer", "harfbuzz_shaping", "libpng_read_fuzzer"]
FCOV_BENCHMARKS = ["bloaty_fuzz_target", "freetype2_ftfuzzer"]
DB_BENCHMARKS = ["harfbuzz_shaping", "libpng_read_fuzzer"]
N_TRIALS = 5
SNAPSHOTS = [3600, 14400]
EDGE_SPACE = 8192
TVERSKY_ALPHA = 0.7
TVERSKY_BETA = 1.0

DISC_PROBS = {
    ("aflpp", "bloaty_fuzz_target"): (0.58, 0.88),
    ("aflpp", "freetype2_ftfuzzer"): (0.55, 0.86),
    ("aflpp", "harfbuzz_shaping"): (0.44, 0.77),
    ("aflpp", "libpng_read_fuzzer"): (0.43, 0.76),
    ("centipede", "bloaty_fuzz_target"): (0.43, 0.76),
    ("centipede", "freetype2_ftfuzzer"): (0.45, 0.78),
    ("centipede", "harfbuzz_shaping"): (0.57, 0.88),
    ("centipede", "libpng_read_fuzzer"): (0.54, 0.85),
    ("libafl", "bloaty_fuzz_target"): (0.46, 0.79),
    ("libafl", "freetype2_ftfuzzer"): (0.56, 0.87),
    ("libafl", "harfbuzz_shaping"): (0.47, 0.80),
    ("libafl", "libpng_read_fuzzer"): (0.57, 0.88),
    ("libfuzzer", "bloaty_fuzz_target"): (0.56, 0.87),
    ("libfuzzer", "freetype2_ftfuzzer"): (0.46, 0.79),
    ("libfuzzer", "harfbuzz_shaping"): (0.55, 0.86),
    ("libfuzzer", "libpng_read_fuzzer"): (0.45, 0.78),
}

SHARED_THRESHOLDS = [
    [4500, 2800, 3200, 4300],
    [4200, 2900, 4500, 3100],
    [2900, 4500, 3100, 4300],
    [3100, 4300, 4500, 2900],
]


def edge_hash(fi, bi, ei):
    x = (fi + 1) * 1000003 + (bi + 1) * 999983 + (ei + 1) * 999961
    x = ((x >> 16) ^ x) * 0x45d9f3b & 0xFFFFFFFF
    x = ((x >> 16) ^ x) * 0x45d9f3b & 0xFFFFFFFF
    x = (x >> 16) ^ x
    return x % 10000


def is_reachable(fi, bi, ei):
    h = edge_hash(fi, bi, ei)
    if ei < 1000:
        return h < 7500
    region_owner = (ei - 1000) // 800
    if ei < 1000 + len(FUZZERS) * 800:
        if region_owner == fi:
            return h < 8000
        else:
            return h < 1500
    return h < SHARED_THRESHOLDS[bi][fi]


def main():
    rng = random.Random(20250425)

    reachable = {}
    for fi in range(len(FUZZERS)):
        for bi in range(len(BENCHMARKS)):
            reachable[(fi, bi)] = [e for e in range(EDGE_SPACE) if is_reachable(fi, bi, e)]

    os.makedirs('/app/data', exist_ok=True)

    # Generate all coverage data in memory first
    # all_data[(fuzzer, benchmark, trial)] = [(snap_time, cumul_edges_sorted, incr_edges_sorted)]
    all_data = {}

    for fi, fuzzer in enumerate(FUZZERS):
        for bi, benchmark in enumerate(BENCHMARKS):
            R = reachable[(fi, bi)]
            p_early, p_late = DISC_PROBS[(fuzzer, benchmark)]

            for trial in range(N_TRIALS):
                snapshots_data = []
                prev_cov = set()

                for snap_idx, snap_time in enumerate(SNAPSHOTS):
                    p = p_early if snap_idx == 0 else p_late
                    new_edges = set()
                    for e in R:
                        if e not in prev_cov and rng.random() < p:
                            new_edges.add(e)
                    cumul = prev_cov | new_edges
                    snapshots_data.append((snap_time, sorted(cumul), sorted(new_edges)))
                    prev_cov = cumul

                all_data[(fuzzer, benchmark, trial)] = snapshots_data

    # Write FCOV binary files for FCOV_BENCHMARKS (cumulative format)
    for fuzzer in FUZZERS:
        for benchmark in FCOV_BENCHMARKS:
            for trial in range(N_TRIALS):
                trial_dir = f'/app/data/{fuzzer}/{benchmark}/trial_{trial:02d}'
                os.makedirs(trial_dir, exist_ok=True)

                snaps = all_data[(fuzzer, benchmark, trial)]
                filepath = f'{trial_dir}/coverage.cov'
                with open(filepath, 'wb') as f:
                    f.write(b'FCOV')
                    f.write(struct.pack('<I', 1))
                    f.write(struct.pack('<I', EDGE_SPACE))
                    f.write(struct.pack('<I', len(snaps)))
                    for snap_time, cumul_edges, _ in snaps:
                        f.write(struct.pack('<I', snap_time))
                        f.write(struct.pack('<I', len(cumul_edges)))
                        for e in cumul_edges:
                            f.write(struct.pack('<I', e))

    # Write SQLite database for DB_BENCHMARKS (incremental edge format)
    db = sqlite3.connect('/app/data/experiment.db')
    c = db.cursor()

    # Config table — experiment parameters
    c.execute('CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)')
    for k, v in [
        ('experiment_name', 'sbft2025_novelty_eval'),
        ('tversky_alpha', str(TVERSKY_ALPHA)),
        ('tversky_beta', str(TVERSKY_BETA)),
        ('edge_space', str(EDGE_SPACE)),
        ('num_trials', str(N_TRIALS)),
    ]:
        c.execute('INSERT INTO config VALUES (?, ?)', (k, v))

    # Coverage table — stores edges discovered per measurement interval
    c.execute('''CREATE TABLE coverage (
        benchmark TEXT NOT NULL,
        fuzzer TEXT NOT NULL,
        trial INTEGER NOT NULL,
        snapshot_time INTEGER NOT NULL,
        edge_id INTEGER NOT NULL
    )''')

    for fuzzer in FUZZERS:
        for benchmark in DB_BENCHMARKS:
            for trial in range(N_TRIALS):
                snaps = all_data[(fuzzer, benchmark, trial)]
                for snap_time, _, incr_edges in snaps:
                    for e in incr_edges:
                        c.execute('INSERT INTO coverage VALUES (?, ?, ?, ?, ?)',
                                  (benchmark, fuzzer, trial, snap_time, e))

    c.execute('CREATE INDEX idx_cov_lookup ON coverage (benchmark, fuzzer, trial, snapshot_time)')

    db.commit()
    db.close()

    # Write meta.json — note: tversky params are ONLY in the SQLite database
    meta = {
        "fuzzers": FUZZERS,
        "benchmarks": BENCHMARKS,
        "trials": N_TRIALS,
        "snapshots_seconds": SNAPSHOTS,
        "edge_space": EDGE_SPACE,
        "fcov_benchmarks": FCOV_BENCHMARKS,
        "db_benchmarks": DB_BENCHMARKS,
        "db_path": "/app/data/experiment.db"
    }
    with open('/app/data/meta.json', 'w') as f:
        json.dump(meta, f, indent=2)

    print(f"Generated: {len(FUZZERS)} fuzzers x {len(BENCHMARKS)} benchmarks x {N_TRIALS} trials")
    print(f"FCOV binary files: {', '.join(FCOV_BENCHMARKS)}")
    print(f"SQLite database:   {', '.join(DB_BENCHMARKS)}")


if __name__ == '__main__':
    main()
