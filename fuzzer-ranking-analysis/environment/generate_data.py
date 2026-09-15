#!/usr/bin/env python3
"""Generate synthetic FuzzBench experiment data into a SQLite database."""

import sqlite3
import random
import math

random.seed(42)

fuzzers = ['afl', 'aflplusplus', 'eclipser', 'honggfuzz', 'libfuzzer']
benchmarks = [
    'freetype2_ftfuzzer',
    'harfbuzz_hb-shape-fuzzer',
    'libpng_read_fuzzer',
    'libxml2_xml',
    'openssl_x509',
    'sqlite3_ossfuzz',
]

n_trials = 10
max_time = 86400
snapshot_interval = 900
n_cycles = max_time // snapshot_interval  # 96

# Coverage parameters: (mean_final, std_dev)
# Designed so: aflplusplus > libfuzzer > afl > honggfuzz > eclipser
params = {
    ('afl', 'freetype2_ftfuzzer'): (5100, 200),
    ('afl', 'harfbuzz_hb-shape-fuzzer'): (4200, 180),
    ('afl', 'libpng_read_fuzzer'): (3200, 150),
    ('afl', 'libxml2_xml'): (2800, 130),
    ('afl', 'openssl_x509'): (1900, 100),
    ('afl', 'sqlite3_ossfuzz'): (3500, 160),
    ('aflplusplus', 'freetype2_ftfuzzer'): (5600, 190),
    ('aflplusplus', 'harfbuzz_hb-shape-fuzzer'): (4700, 170),
    ('aflplusplus', 'libpng_read_fuzzer'): (3700, 140),
    ('aflplusplus', 'libxml2_xml'): (3300, 120),
    ('aflplusplus', 'openssl_x509'): (2300, 95),
    ('aflplusplus', 'sqlite3_ossfuzz'): (4000, 150),
    ('eclipser', 'freetype2_ftfuzzer'): (4300, 220),
    ('eclipser', 'harfbuzz_hb-shape-fuzzer'): (3400, 200),
    ('eclipser', 'libpng_read_fuzzer'): (2500, 170),
    ('eclipser', 'libxml2_xml'): (2100, 150),
    ('eclipser', 'openssl_x509'): (1300, 110),
    ('eclipser', 'sqlite3_ossfuzz'): (2700, 180),
    ('honggfuzz', 'freetype2_ftfuzzer'): (4700, 210),
    ('honggfuzz', 'harfbuzz_hb-shape-fuzzer'): (3800, 190),
    ('honggfuzz', 'libpng_read_fuzzer'): (2900, 160),
    ('honggfuzz', 'libxml2_xml'): (2500, 140),
    ('honggfuzz', 'openssl_x509'): (1600, 100),
    ('honggfuzz', 'sqlite3_ossfuzz'): (3100, 170),
    ('libfuzzer', 'freetype2_ftfuzzer'): (5400, 195),
    ('libfuzzer', 'harfbuzz_hb-shape-fuzzer'): (4500, 175),
    ('libfuzzer', 'libpng_read_fuzzer'): (3500, 145),
    ('libfuzzer', 'libxml2_xml'): (3100, 125),
    ('libfuzzer', 'openssl_x509'): (2100, 98),
    ('libfuzzer', 'sqlite3_ossfuzz'): (3800, 155),
}

db = sqlite3.connect('/app/experiment/fuzzbench.db')
db.execute('''CREATE TABLE coverage (
    fuzzer TEXT NOT NULL,
    benchmark TEXT NOT NULL,
    trial_id INTEGER NOT NULL,
    time INTEGER NOT NULL,
    edges_covered INTEGER NOT NULL
)''')

db.execute('''CREATE TABLE experiment_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)''')
db.execute("INSERT INTO experiment_config VALUES ('fuzzers', ?)",
           [','.join(fuzzers)])
db.execute("INSERT INTO experiment_config VALUES ('benchmarks', ?)",
           [','.join(benchmarks)])
db.execute("INSERT INTO experiment_config VALUES ('trials', ?)",
           [str(n_trials)])
db.execute("INSERT INTO experiment_config VALUES ('max_time', ?)",
           [str(max_time)])

total_rows = 0
for fuzzer in fuzzers:
    for benchmark in benchmarks:
        mean_final, std_final = params[(fuzzer, benchmark)]
        for trial_id in range(n_trials):
            final_cov = int(random.gauss(mean_final, std_final))
            final_cov = max(final_cov, 500)

            prev = 0
            for cycle in range(n_cycles):
                t = (cycle + 1) * snapshot_interval
                progress = math.pow(t / max_time, 0.35)
                expected_cov = int(final_cov * progress)
                noise = int(random.gauss(0, std_final * 0.03))
                cov = max(prev, expected_cov + noise)
                prev = cov

                db.execute(
                    'INSERT INTO coverage VALUES (?, ?, ?, ?, ?)',
                    (fuzzer, benchmark, trial_id, t, cov)
                )
                total_rows += 1

db.execute(
    'CREATE INDEX idx_coverage_fbt ON coverage(fuzzer, benchmark, trial_id)'
)
db.commit()
db.close()

print(f"Generated {total_rows} coverage rows in /app/experiment/fuzzbench.db")
