#!/usr/bin/env python3
"""Generate SQLite database, manifest, and problem description for Robot Obstacle Navigation."""
import random
import os
import json
import sqlite3

os.makedirs('/data', exist_ok=True)

db_path = '/data/obstacles.db'
conn = sqlite3.connect(db_path)
c = conn.cursor()

# --- Schema ---
c.execute('''CREATE TABLE test_suites (
    suite_id INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    num_obstacles INTEGER NOT NULL,
    num_queries INTEGER NOT NULL,
    max_height INTEGER NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)''')

c.execute('''CREATE TABLE obstacles (
    suite_id INTEGER NOT NULL REFERENCES test_suites(suite_id),
    position INTEGER NOT NULL,
    height INTEGER NOT NULL,
    PRIMARY KEY (suite_id, position)
)''')

c.execute('''CREATE TABLE queries (
    suite_id INTEGER NOT NULL REFERENCES test_suites(suite_id),
    query_id INTEGER NOT NULL,
    range_start INTEGER NOT NULL,
    range_end INTEGER NOT NULL,
    priority INTEGER DEFAULT 1,
    PRIMARY KEY (suite_id, query_id)
)''')

c.execute('''CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
)''')

c.execute('''CREATE TABLE suite_tags (
    suite_id INTEGER NOT NULL REFERENCES test_suites(suite_id),
    tag TEXT NOT NULL,
    PRIMARY KEY (suite_id, tag)
)''')

c.execute('CREATE INDEX idx_obs_suite ON obstacles(suite_id)')
c.execute('CREATE INDEX idx_obs_height ON obstacles(height)')
c.execute('CREATE INDEX idx_qry_suite ON queries(suite_id)')
c.execute('CREATE INDEX idx_qry_range ON queries(range_start, range_end)')

c.execute('''CREATE VIEW suite_summary AS
    SELECT ts.suite_id, ts.description, ts.num_obstacles, ts.num_queries,
           ts.max_height, MIN(o.height) AS min_obstacle,
           MAX(o.height) AS max_obstacle,
           CAST(AVG(o.height) AS INTEGER) AS avg_obstacle
    FROM test_suites ts
    LEFT JOIN obstacles o ON ts.suite_id = o.suite_id
    GROUP BY ts.suite_id
''')

c.execute('''CREATE VIEW query_stats AS
    SELECT suite_id, COUNT(*) AS total_queries,
           AVG(range_end - range_start + 1) AS avg_range_length,
           MAX(range_end - range_start + 1) AS max_range_length
    FROM queries GROUP BY suite_id
''')

# --- Metadata ---
for k, v in [
    ("version", "3.0"),
    ("format", "relational"),
    ("collision_model", "subtract"),
    ("pass_model", "unchanged"),
    ("notes", "Heights stored as raw integers. Position indexing is 1-based."),
]:
    c.execute('INSERT INTO metadata VALUES (?, ?)', (k, v))

# --- Test cases: (description, n, q, d, obstacles, queries) ---
test_cases = []

# Suite 1: Small example from problem statement
test_cases.append(("basic_corridor", 5, 3, 5,
    [0, 2, 6, 1, 3],
    [(5, 5), (1, 5), (1, 3)]))

# Suite 2: Medium example
test_cases.append(("medium_corridor", 7, 5, 10,
    [7, 6, 2, 5, 0, 1, 4],
    [(1, 3), (1, 7), (4, 7), (2, 5), (4, 6)]))

# Suite 3: Large d values (10^9)
test_cases.append(("large_values", 10, 8, 1000000000,
    [0, 0, 0, 500000000, 1, 999999999, 0, 500000001, 999999999, 1],
    [(1, 1), (1, 10), (3, 6), (7, 8), (1, 4), (5, 10), (1, 6), (2, 9)]))

# Suite 4: d=0 edge case (all answers must be 0)
test_cases.append(("zero_height", 5, 5, 0,
    [100, 200, 0, 400, 500],
    [(1, 5), (1, 1), (3, 3), (2, 4), (5, 5)]))

# Suite 5: Large performance test (n=q=100000)
rng = random.Random(42)
n5, q5, d5 = 100000, 100000, 1000000000
a5 = [rng.randint(0, 1000000000) for _ in range(n5)]
queries5 = []
for _ in range(q5):
    l = rng.randint(1, n5)
    r = rng.randint(l, n5)
    queries5.append((l, r))
test_cases.append(("stress_large", n5, q5, d5, a5, queries5))

# --- Insert data ---
for suite_idx, (desc, n, q, d, obstacles, queries) in enumerate(test_cases, 1):
    c.execute(
        'INSERT INTO test_suites (suite_id, description, num_obstacles, '
        'num_queries, max_height) VALUES (?, ?, ?, ?, ?)',
        (suite_idx, desc, n, q, d))

    for pos, h in enumerate(obstacles, 1):
        c.execute('INSERT INTO obstacles VALUES (?, ?, ?)',
                  (suite_idx, pos, h))

    for qid, (l, r) in enumerate(queries, 1):
        c.execute(
            'INSERT INTO queries (suite_id, query_id, range_start, range_end) '
            'VALUES (?, ?, ?, ?)',
            (suite_idx, qid, l, r))

    tags = ["small" if n <= 10 else ("medium" if n <= 1000 else "large")]
    if d == 0:
        tags.append("edge_case")
    if d >= 10**9:
        tags.append("large_values")
    for tag in tags:
        c.execute('INSERT INTO suite_tags VALUES (?, ?)', (suite_idx, tag))

conn.commit()
conn.close()

# --- Manifest ---
total_q = sum(tc[2] for tc in test_cases)
manifest = {
    "format_version": "3.0",
    "database": "/data/obstacles.db",
    "problem_statement": "/data/problem.md",
    "output": {
        "path": "/app/output.txt",
        "format": "one_integer_per_line",
        "ordering": "ascending_suite_id_then_ascending_query_id"
    },
    "suites": [
        {"id": i + 1, "description": tc[0], "expected_answers": tc[2]}
        for i, tc in enumerate(test_cases)
    ],
    "validation": {
        "total_answers": total_q,
        "tool": "/usr/local/bin/validate-output"
    }
}

with open('/data/manifest.json', 'w') as f:
    json.dump(manifest, f, indent=2)

# --- Problem statement ---
with open('/data/problem.md', 'w') as f:
    f.write("""# Robot Obstacle Navigation

## Problem

You have the ability to create robots of height lying in [0, d].
To test them, you constructed a line of length n with obstacles.
The obstacle at position i has height a_i >= 0 (a_i = 0 means no obstacle).

To test a robot, select a segment [l, r] and run it from position l to r.
When the robot encounters an obstacle with height a_i > 0:
- If h < a_i: nothing happens (robot is too short).
- If h >= a_i: height becomes h - a_i.

For each query [l, r], determine the maximum possible final height,
where the initial height is chosen optimally from {0, 1, ..., d}.

## Data Source

All test data is in the SQLite database at `/data/obstacles.db`.
Configuration at `/data/manifest.json`. Explore the schema to understand
table relationships, views, and metadata.

## Output

Write to `/app/output.txt`: one integer per line for every query across
all suites. Suites in ascending suite_id order; queries within each
suite in ascending query_id order.

## Validation

    validate-output /app/output.txt

## Constraints

- 1 <= n <= 10^5
- 1 <= q <= 10^5
- 0 <= d <= 10^9
- 0 <= a_i <= 10^9
- 1 <= l <= r <= n
""")

print("Generated {} suites, {} total queries".format(len(test_cases), total_q))
