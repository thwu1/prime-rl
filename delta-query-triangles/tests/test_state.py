
import csv
import json
import os
import random
import shutil
import sqlite3
import subprocess
import tempfile
from collections import defaultdict


def _count_triangles_bf(fwd):
    """Brute force triangle count: ordered triples (a,b,c) with a->b, b->c, a->c."""
    count = 0
    for a, na in fwd.items():
        for b in na:
            fb = fwd.get(b)
            if fb is None:
                continue
            for c in fb:
                if c != a and c in na:
                    count += 1
    return count


def _write_sqlite_graph(edges, db_path):
    """Write edges to a SQLite database."""
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE edges (src INTEGER NOT NULL, dst INTEGER NOT NULL)")
    conn.executemany("INSERT INTO edges VALUES (?, ?)", sorted(edges))
    conn.execute("CREATE INDEX idx_src ON edges (src)")
    conn.execute("CREATE INDEX idx_dst ON edges (dst)")
    conn.execute("CREATE UNIQUE INDEX idx_edge ON edges (src, dst)")
    conn.commit()
    conn.close()


def _write_updates_parquet(batches, parquet_path):
    """Write update batches to Parquet format via DuckDB."""
    import duckdb

    csv_fd, csv_path = tempfile.mkstemp(suffix=".csv")
    try:
        with os.fdopen(csv_fd, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["batch_id", "src", "dst", "diff"])
            for i, batch in enumerate(batches):
                for s, d, diff in batch:
                    writer.writerow([i, s, d, diff])

        if os.path.exists(parquet_path):
            os.remove(parquet_path)

        con = duckdb.connect()
        con.execute(
            f"COPY (SELECT CAST(batch_id AS INTEGER) AS batch_id, "
            f"CAST(src AS INTEGER) AS src, "
            f"CAST(dst AS INTEGER) AS dst, "
            f"CAST(diff AS TINYINT) AS diff "
            f"FROM read_csv('{csv_path}')) "
            f"TO '{parquet_path}' (FORMAT 'parquet')"
        )
        con.close()
    finally:
        if os.path.exists(csv_path):
            os.remove(csv_path)


class TestSolutionExists:

    def test_incremental_py_exists(self):
        assert os.path.exists("/app/incremental.py"), (
            "/app/incremental.py not found — the solution must create this file"
        )


class TestMainDataset:
    """Run solution on the preloaded 50K-node graph and verify counts."""

    def test_main_correctness(self):
        # Load precomputed expected values
        with open("/app/data/.expected.json") as f:
            expected = json.load(f)

        # Run agent's solution with a timeout that excludes brute-force recomputation
        result = subprocess.run(
            ["python3", "/app/incremental.py"],
            capture_output=True,
            text=True,
            timeout=90,
            cwd="/app",
        )
        assert result.returncode == 0, (
            f"incremental.py exited with code {result.returncode}.\n"
            f"stderr: {result.stderr[-2000:]}"
        )

        assert os.path.exists("/app/results.json"), (
            "/app/results.json was not created by incremental.py"
        )

        with open("/app/results.json") as f:
            actual = json.load(f)

        assert isinstance(actual, list), "results.json must contain a JSON array"
        assert len(actual) == len(expected), (
            f"Expected {len(expected)} values (initial + 200 batches), got {len(actual)}"
        )

        mismatches = []
        for i, (exp, act) in enumerate(zip(expected, actual)):
            if exp != act:
                mismatches.append((i, exp, act))

        assert len(mismatches) == 0, (
            f"{len(mismatches)} mismatches found. First 5: "
            + "; ".join(
                f"step {i}: expected {e}, got {a}" for i, e, a in mismatches[:5]
            )
        )


class TestAntiCheat:
    """Generate a fresh random graph at test time to prevent hardcoded answers."""

    def test_anticheat_random_graph(self):
        rng = random.Random(77777)

        # Generate small graph
        ac_n, ac_m = 300, 3000
        ac_edges = set()
        while len(ac_edges) < ac_m:
            a = rng.randint(0, ac_n - 1)
            b = rng.randint(0, ac_n - 1)
            if a != b:
                ac_edges.add((a, b))

        # Generate batches with adversarial cases
        ac_batches = []
        ac_current = set(ac_edges)
        n_ac_batches = 15

        for bi in range(n_ac_batches):
            changes = []
            nc = rng.randint(5, 20)
            seen = set()
            for _ in range(nc):
                if rng.random() < 0.4 and ac_current:
                    e = rng.choice(list(ac_current))
                    if e not in seen:
                        seen.add(e)
                        ac_current.discard(e)
                        changes.append((e[0], e[1], -1))
                else:
                    for _ in range(30):
                        a = rng.randint(0, ac_n - 1)
                        b = rng.randint(0, ac_n - 1)
                        if a != b and (a, b) not in ac_current and (a, b) not in seen:
                            seen.add((a, b))
                            ac_current.add((a, b))
                            changes.append((a, b, 1))
                            break

            # Batch 5: simultaneous triangle insertion
            if bi == 5:
                tri = (ac_n - 3, ac_n - 2, ac_n - 1)
                for p in [(tri[0], tri[1]), (tri[1], tri[2]), (tri[0], tri[2])]:
                    if p in ac_current:
                        ac_current.discard(p)
                        changes.append((p[0], p[1], -1))
                for p in [(tri[0], tri[1]), (tri[1], tri[2]), (tri[0], tri[2])]:
                    ac_current.add(p)
                    changes.append((p[0], p[1], 1))

            # Batch 10: consolidation test
            if bi == 10:
                te = (ac_n - 5, ac_n - 4)
                if te not in ac_current:
                    changes.append((te[0], te[1], 1))
                    changes.append((te[0], te[1], -1))

            ac_batches.append(changes)

        # Compute expected via brute force
        ac_fwd = defaultdict(set)
        for a, b in ac_edges:
            ac_fwd[a].add(b)
        ac_expected = [_count_triangles_bf(ac_fwd)]

        test_edges = set(ac_edges)
        for batch in ac_batches:
            net = defaultdict(int)
            for s, d, diff in batch:
                net[(s, d)] += diff
            for (s, d), diff in net.items():
                if diff > 0:
                    test_edges.add((s, d))
                elif diff < 0:
                    test_edges.discard((s, d))
            tfwd = defaultdict(set)
            for a, b in test_edges:
                tfwd[a].add(b)
            ac_expected.append(_count_triangles_bf(tfwd))

        # Back up original data
        backup_dir = "/tmp/_tbench_backup"
        os.makedirs(backup_dir, exist_ok=True)
        for fname in ("graph.db", "updates.parquet"):
            src = f"/app/data/{fname}"
            if os.path.exists(src):
                shutil.copy2(src, f"{backup_dir}/{fname}")

        # Remove expected values file so solution cannot read it
        exp_path = "/app/data/.expected.json"
        exp_backup = f"{backup_dir}/.expected.json"
        if os.path.exists(exp_path):
            shutil.copy2(exp_path, exp_backup)
            os.remove(exp_path)

        try:
            # Write anti-cheat SQLite database
            _write_sqlite_graph(ac_edges, "/app/data/graph.db")

            # Write anti-cheat Parquet file
            _write_updates_parquet(ac_batches, "/app/data/updates.parquet")

            if os.path.exists("/app/results.json"):
                os.remove("/app/results.json")

            result = subprocess.run(
                ["python3", "/app/incremental.py"],
                capture_output=True,
                text=True,
                timeout=60,
                cwd="/app",
            )
            assert result.returncode == 0, (
                f"Solution failed on anti-cheat graph.\nstderr: {result.stderr[-2000:]}"
            )

            assert os.path.exists("/app/results.json"), (
                "/app/results.json not created for anti-cheat data"
            )

            with open("/app/results.json") as f:
                ac_actual = json.load(f)

            assert isinstance(ac_actual, list), "results.json must be a JSON array"
            assert len(ac_actual) == len(ac_expected), (
                f"Anti-cheat: expected {len(ac_expected)} values, got {len(ac_actual)}"
            )

            ac_mismatches = []
            for i, (exp, act) in enumerate(zip(ac_expected, ac_actual)):
                if exp != act:
                    ac_mismatches.append((i, exp, act))

            assert len(ac_mismatches) == 0, (
                f"Anti-cheat: {len(ac_mismatches)} mismatches. First 5: "
                + "; ".join(
                    f"step {i}: expected {e}, got {a}"
                    for i, e, a in ac_mismatches[:5]
                )
            )

        finally:
            # Restore original data
            for fname in ("graph.db", "updates.parquet"):
                bk = f"{backup_dir}/{fname}"
                if os.path.exists(bk):
                    shutil.copy2(bk, f"/app/data/{fname}")
            if os.path.exists(exp_backup):
                shutil.copy2(exp_backup, exp_path)
