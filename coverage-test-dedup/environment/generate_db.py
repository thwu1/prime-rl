#!/usr/bin/env python3
"""Generate synthetic Hypothesis Corpus multi-database for test suite analysis."""
import sqlite3
import json
import random

random.seed(42)

# ── Main database ────────────────────────────────────────────────────────────
conn_main = sqlite3.connect("/data/corpus.db")
conn_main.executescript("""
CREATE TABLE core_repository (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT UNIQUE NOT NULL,
    size_bytes INTEGER NOT NULL,
    stargazers_count INTEGER NOT NULL,
    is_fork BOOLEAN DEFAULT 0,
    status TEXT DEFAULT 'valid',
    status_reason TEXT,
    requirements TEXT,
    node_ids TEXT,
    commit_hash TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE core_node (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo_id INTEGER NOT NULL,
    node_id TEXT NOT NULL,
    canonical_parametrization BOOLEAN DEFAULT 1,
    source_code TEXT,
    is_stateful BOOLEAN DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repo_id) REFERENCES core_repository(id),
    UNIQUE(repo_id, node_id)
);

CREATE TABLE runtime_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER NOT NULL,
    status TEXT DEFAULT 'passed',
    execution_time REAL,
    error_message TEXT,
    count_test_cases INTEGER,
    coverage TEXT,
    line_execution_counts TEXT,
    unique_lines_covered INTEGER,
    settings TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (node_id) REFERENCES core_node(id)
);

CREATE INDEX idx_node_repo ON core_node(repo_id);
CREATE INDEX idx_runtime_node ON runtime_summary(node_id);
CREATE INDEX idx_repo_status ON core_repository(status);
""")

# ── Companion database for per-test-case data ────────────────────────────────
conn_tc = sqlite3.connect("/data/corpus_test_cases.db")
conn_tc.executescript("""
CREATE TABLE runtime_test_case (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id INTEGER NOT NULL,
    test_case_number INTEGER NOT NULL,
    coverage TEXT NOT NULL,
    timing TEXT NOT NULL DEFAULT '{}',
    predicates TEXT NOT NULL DEFAULT '{}',
    features TEXT NOT NULL DEFAULT '{}',
    data_status INTEGER DEFAULT 2,
    status_reason TEXT,
    choices_size INTEGER NOT NULL DEFAULT 0,
    how_generated TEXT NOT NULL DEFAULT 'generate'
);

CREATE INDEX idx_testcase_node ON runtime_test_case(node_id);
CREATE INDEX idx_testcase_status ON runtime_test_case(data_status);
""")

SOURCE_FILES = [f"src/module_{chr(97 + i)}.py" for i in range(5)]


def gen_coverage():
    """Generate random coverage dict with 2-4 files, 15-50 lines each."""
    cov = {}
    for f in random.sample(SOURCE_FILES, random.randint(2, 4)):
        n = random.randint(15, 50)
        cov[f] = sorted(random.sample(range(1, 201), n))
    return cov


def clone_coverage(cov):
    """Create near-duplicate coverage (Jaccard > 0.90 with original)."""
    new_cov = {}
    for f, lines in cov.items():
        kept = list(lines)
        if len(kept) > 2 and random.random() < 0.7:
            kept.remove(random.choice(kept))
        avail = [x for x in range(1, 201) if x not in lines]
        if avail and random.random() < 0.5:
            kept.append(random.choice(avail))
        new_cov[f] = sorted(set(kept))
    return new_cov


def insert_test_cases(conn_tc_db, node_db_id, cov, node_status):
    """Insert test cases for a node, return (n_test_cases, summary_coverage)."""
    n_tc = random.randint(5, 10)
    covered = {f: set() for f in cov}
    summary_cov = {f: list(lines) for f, lines in cov.items()}

    for tc in range(n_tc):
        tc_cov = {}
        for f, lines in cov.items():
            sz = max(1, int(len(lines) * random.uniform(0.3, 0.8)))
            tc_lines = sorted(random.sample(lines, sz))
            tc_cov[f] = tc_lines
            covered[f].update(tc_lines)

        # Last valid test case fills in remaining uncovered lines
        if tc == n_tc - 1:
            for f, lines in cov.items():
                missing = set(lines) - covered[f]
                if missing:
                    tc_cov[f] = sorted(set(tc_cov.get(f, [])) | missing)

        conn_tc_db.execute(
            "INSERT INTO runtime_test_case (node_id, test_case_number, coverage, data_status) VALUES (?, ?, ?, ?)",
            (node_db_id, tc, json.dumps(tc_cov), 2),
        )

    # ~15% chance: add a failure-inducing test case (data_status=3) with
    # overlapping coverage — should be INCLUDED in aggregation
    if node_status == "passed" and random.random() < 0.15:
        fail_file = random.choice(list(cov.keys()))
        fail_lines = sorted(random.sample(cov[fail_file], min(3, len(cov[fail_file]))))
        conn_tc_db.execute(
            "INSERT INTO runtime_test_case (node_id, test_case_number, coverage, data_status) VALUES (?, ?, ?, ?)",
            (node_db_id, n_tc, json.dumps({fail_file: fail_lines}), 3),
        )
        n_tc += 1

    # ~30% chance: add POISONED overrun test case (data_status=0) with lines
    # in 201-250 range that must NOT be included in analysis.
    # runtime_summary.coverage will include these, creating a data quality trap.
    if node_status == "passed" and random.random() < 0.3:
        poison_file = random.choice(list(cov.keys()))
        poison_lines = sorted(random.sample(range(201, 251), 5))
        conn_tc_db.execute(
            "INSERT INTO runtime_test_case (node_id, test_case_number, coverage, data_status) VALUES (?, ?, ?, ?)",
            (node_db_id, n_tc, json.dumps({poison_file: poison_lines}), 0),
        )
        summary_cov[poison_file] = sorted(
            set(summary_cov.get(poison_file, [])) | set(poison_lines)
        )
        n_tc += 1

    # ~20% chance: add POISONED filtered test case (data_status=1) with lines
    # in 251-300 range — also must NOT be included.
    if node_status == "passed" and random.random() < 0.2:
        filt_file = random.choice(list(cov.keys()))
        filt_lines = sorted(random.sample(range(251, 301), 3))
        conn_tc_db.execute(
            "INSERT INTO runtime_test_case (node_id, test_case_number, coverage, data_status) VALUES (?, ?, ?, ?)",
            (node_db_id, n_tc, json.dumps({filt_file: filt_lines}), 1),
        )
        summary_cov[filt_file] = sorted(
            set(summary_cov.get(filt_file, [])) | set(filt_lines)
        )
        n_tc += 1

    return n_tc, summary_cov


# ── Valid repositories (10 repos, 10-11 nodes each) ──────────────────────────
for i in range(10):
    repo_name = f"testorg/project-{chr(97 + i)}"
    conn_main.execute(
        "INSERT INTO core_repository (full_name, size_bytes, stargazers_count, status) VALUES (?, ?, ?, ?)",
        (repo_name, random.randint(50000, 500000), random.randint(10, 2000), "valid"),
    )
    repo_id = conn_main.execute("SELECT last_insert_rowid()").fetchone()[0]

    coverages = []
    nodes = []

    for j in range(10):
        node_str = f"tests/test_{chr(97 + i)}.py::test_func_{j}"

        # Even-indexed repos: nodes 8 and 9 are near-clones of 0 and 1
        if i % 2 == 0 and j >= 8:
            cov = clone_coverage(coverages[j - 8])
        else:
            cov = gen_coverage()

        # Error nodes: node 7 in repos 3 and 7
        if j == 7 and i in (3, 7):
            status = "error"
        else:
            status = "passed"

        conn_main.execute(
            "INSERT INTO core_node (repo_id, node_id) VALUES (?, ?)",
            (repo_id, node_str),
        )
        nid = conn_main.execute("SELECT last_insert_rowid()").fetchone()[0]
        coverages.append(cov)
        nodes.append({"db_id": nid, "node_id": node_str, "cov": cov, "status": status})

    # Even-indexed repos: add a skipped node (must be excluded from analysis)
    if i % 2 == 0:
        skip_str = f"tests/test_{chr(97 + i)}.py::test_func_skipped"
        conn_main.execute(
            "INSERT INTO core_node (repo_id, node_id) VALUES (?, ?)",
            (repo_id, skip_str),
        )
        skip_nid = conn_main.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn_main.execute(
            "INSERT INTO runtime_summary (node_id, status) VALUES (?, ?)",
            (skip_nid, "skipped"),
        )

    for node in nodes:
        if node["status"] == "error":
            conn_main.execute(
                "INSERT INTO runtime_summary (node_id, status, error_message) VALUES (?, ?, ?)",
                (node["db_id"], "error", "TimeoutExpired: test timed out after 300s"),
            )
            continue

        n_tc, summary_cov = insert_test_cases(conn_tc, node["db_id"], node["cov"], node["status"])
        total = sum(len(v) for v in summary_cov.values())
        conn_main.execute(
            "INSERT INTO runtime_summary (node_id, status, execution_time, count_test_cases, coverage, unique_lines_covered) VALUES (?, ?, ?, ?, ?, ?)",
            (
                node["db_id"],
                node["status"],
                round(random.uniform(0.1, 5.0), 3),
                n_tc,
                json.dumps(summary_cov),
                total,
            ),
        )

# ── Invalid repositories (must be excluded from analysis) ────────────────────
for i in range(2):
    repo_name = f"testorg/invalid-project-{chr(97 + i)}"
    conn_main.execute(
        "INSERT INTO core_repository (full_name, size_bytes, stargazers_count, status, status_reason) VALUES (?, ?, ?, ?, ?)",
        (repo_name, random.randint(10000, 100000), random.randint(1, 5), "invalid",
         f"minhash_duplicate (testorg/project-{chr(97 + i)}, 85%/82%)"),
    )
    repo_id = conn_main.execute("SELECT last_insert_rowid()").fetchone()[0]

    for j in range(5):
        node_str = f"tests/test_invalid_{chr(97 + i)}.py::test_func_{j}"
        cov = gen_coverage()

        conn_main.execute(
            "INSERT INTO core_node (repo_id, node_id) VALUES (?, ?)",
            (repo_id, node_str),
        )
        nid = conn_main.execute("SELECT last_insert_rowid()").fetchone()[0]

        n_tc, summary_cov = insert_test_cases(conn_tc, nid, cov, "passed")
        total = sum(len(v) for v in summary_cov.values())
        conn_main.execute(
            "INSERT INTO runtime_summary (node_id, status, execution_time, count_test_cases, coverage, unique_lines_covered) VALUES (?, ?, ?, ?, ?, ?)",
            (nid, "passed", round(random.uniform(0.1, 5.0), 3), n_tc, json.dumps(summary_cov), total),
        )

conn_main.commit()
conn_main.close()
conn_tc.commit()
conn_tc.close()
print("Generated /data/corpus.db and /data/corpus_test_cases.db")
