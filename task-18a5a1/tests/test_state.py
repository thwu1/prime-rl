"""Tests for forensic column-store recovery — verifies both file repair and query output."""

import struct
import random
import os

import duckdb
import pytest


# ---------------------------------------------------------------------------
# Data regeneration (must match generate_data.py exactly)
# ---------------------------------------------------------------------------

def gen_correct_data():
    """Regenerate the original correct relation data from the same seed."""
    random.seed(42)

    def gen_col(n, lo, hi):
        return [random.randint(lo, hi) for _ in range(n)]

    r0 = [gen_col(400, 0, 9999), gen_col(400, 0, 99), gen_col(400, 0, 9999)]
    r1 = [gen_col(250, 0, 4999), gen_col(250, 0, 49), gen_col(250, 0, 99),
          gen_col(250, 0, 9999)]
    r2 = [gen_col(300, 0, 5999), gen_col(300, 0, 49), gen_col(300, 0, 4999)]
    r3 = [gen_col(500, 0, 99), gen_col(500, 0, 9), gen_col(500, 0, 49),
          gen_col(500, 0, 199), gen_col(500, 0, 9999)]
    r4 = [gen_col(180, 0, 99), gen_col(180, 0, 49)]

    return {
        'r0': (400, 3, r0),
        'r1': (250, 4, r1),
        'r2': (300, 3, r2),
        'r3': (500, 5, r3),
        'r4': (180, 2, r4),
    }


# ---------------------------------------------------------------------------
# DuckDB helpers
# ---------------------------------------------------------------------------

def load_data_to_duckdb(data):
    """Load relation data dict into a DuckDB connection."""
    conn = duckdb.connect()
    for name in sorted(data.keys()):
        nt, nc, cols = data[name]
        col_defs = ", ".join(f"c{i} UBIGINT" for i in range(nc))
        conn.execute(f"CREATE TABLE {name} ({col_defs})")
        if nt > 0:
            batch_size = 100
            for start in range(0, nt, batch_size):
                end = min(start + batch_size, nt)
                rows = []
                for row_idx in range(start, end):
                    vals = ", ".join(str(cols[c][row_idx]) for c in range(nc))
                    rows.append(f"({vals})")
                conn.execute(
                    f"INSERT INTO {name} VALUES {', '.join(rows)}"
                )
    return conn


def load_repaired_binary(filepath):
    """Load a binary column-store relation file."""
    with open(filepath, 'rb') as f:
        nt, nc = struct.unpack('<QQ', f.read(16))
        cols = []
        for _ in range(nc):
            cols.append(list(struct.unpack(f'<{nt}Q', f.read(8 * nt))))
    return nt, nc, cols


def load_repaired_data():
    """Load all repaired binary files as a relation data dict."""
    data = {}
    data_dir = '/app/data'
    idx = 0
    while os.path.exists(os.path.join(data_dir, f'r{idx}')):
        filepath = os.path.join(data_dir, f'r{idx}')
        nt, nc, cols = load_repaired_binary(filepath)
        data[f'r{idx}'] = (nt, nc, cols)
        idx += 1
    return data


def get_queries():
    """Read SQL queries from the queries file."""
    queries = []
    with open('/app/queries.sql') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('--'):
                queries.append(line.rstrip(';'))
    return queries


def run_queries(conn, queries):
    """Execute queries and return results as formatted strings."""
    results = []
    for q in queries:
        row = conn.execute(q).fetchone()
        if row is None or all(v is None for v in row):
            results.append("NULL")
        else:
            results.append(
                " ".join("NULL" if v is None else str(v) for v in row)
            )
    return results


def read_output():
    """Read the agent's output file."""
    with open('/app/output.txt') as f:
        return [line.strip() for line in f if line.strip()]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestForensicRecovery:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.correct_data = gen_correct_data()
        self.correct_conn = load_data_to_duckdb(self.correct_data)
        self.queries = get_queries()
        self.expected = run_queries(self.correct_conn, self.queries)
        self.correct_conn.close()

    # --- Output file ---

    def test_output_exists(self):
        assert os.path.exists('/app/output.txt'), \
            "Output file /app/output.txt not found."

    def test_result_count(self):
        actual = read_output()
        assert len(actual) == len(self.expected), \
            f"Expected {len(self.expected)} results, got {len(actual)}"

    # --- Structural integrity of repaired binary files ---

    def test_r0_intact(self):
        """r0 should remain unchanged (400 tuples, 3 columns)."""
        nt, nc, _ = load_repaired_binary('/app/data/r0')
        assert nt == 400, f"r0 should have 400 tuples, got {nt}"
        assert nc == 3, f"r0 should have 3 columns, got {nc}"

    def test_r1_header_fixed(self):
        """r1 header should report 4 columns after repair."""
        nt, nc, _ = load_repaired_binary('/app/data/r1')
        assert nt == 250, f"r1 should have 250 tuples, got {nt}"
        assert nc == 4, f"r1 should have 4 columns after repair, got {nc}"

    def test_r2_endianness_fixed(self):
        """r2.c2 values should be within expected range after fix."""
        nt, nc, cols = load_repaired_binary('/app/data/r2')
        assert nc == 3, f"r2 should have 3 columns, got {nc}"
        c2_max = max(cols[2])
        assert c2_max <= 4999, \
            f"r2.c2 max={c2_max}, expected <= 4999 (endianness not fixed?)"

    def test_r3_columns_ordered(self):
        """r3.c1 should have max <= 9 and r3.c3 max <= 199 after swap fix."""
        nt, nc, cols = load_repaired_binary('/app/data/r3')
        assert nc == 5, f"r3 should have 5 columns, got {nc}"
        c1_max = max(cols[1])
        assert c1_max <= 9, \
            f"r3.c1 max={c1_max}, expected <= 9 (columns still swapped?)"
        c3_max = max(cols[3])
        assert c3_max <= 199, \
            f"r3.c3 max={c3_max}, expected <= 199"

    def test_r3_c4_decoded(self):
        """r3.c4 values should be in [0, 9999] after delta decode."""
        nt, nc, cols = load_repaired_binary('/app/data/r3')
        assert nc == 5, f"r3 should have 5 columns, got {nc}"
        c4_max = max(cols[4])
        c4_min = min(cols[4])
        assert c4_max <= 9999, \
            f"r3.c4 max={c4_max}, expected <= 9999 (delta encoding not decoded?)"
        assert c4_min >= 0, \
            f"r3.c4 min={c4_min}, expected >= 0"

    def test_r4_header_fixed(self):
        """r4 header should report 180 tuples after repair."""
        nt, nc, _ = load_repaired_binary('/app/data/r4')
        assert nt == 180, f"r4 should have 180 tuples, got {nt}"
        assert nc == 2, f"r4 should have 2 columns, got {nc}"

    # --- Data correctness via DuckDB cross-check ---

    def test_repaired_data_matches_ground_truth(self):
        """Queries on repaired binary data must match ground truth."""
        repaired = load_repaired_data()
        rep_conn = load_data_to_duckdb(repaired)
        rep_results = run_queries(rep_conn, self.queries)
        rep_conn.close()
        for i, (rep, exp) in enumerate(zip(rep_results, self.expected)):
            assert rep == exp, \
                f"Q{i+1}: repaired data gives '{rep}', expected '{exp}'"

    # --- Per-query output checks ---

    def test_q1_baseline(self):
        """Q1: r0 only — baseline correctness check."""
        actual = read_output()
        assert actual[0] == self.expected[0], \
            f"Q1: got '{actual[0]}', expected '{self.expected[0]}'"

    def test_q2_r1_hidden_column(self):
        """Q2: requires r1's repaired 4th column (c3)."""
        actual = read_output()
        assert actual[1] == self.expected[1], \
            f"Q2: got '{actual[1]}', expected '{self.expected[1]}'"

    def test_q3_r2_endianness(self):
        """Q3: requires r2.c2 byte-order repair."""
        actual = read_output()
        assert actual[2] == self.expected[2], \
            f"Q3: got '{actual[2]}', expected '{self.expected[2]}'"

    def test_q4_r3_column_swap(self):
        """Q4: requires r3 column order repair."""
        actual = read_output()
        assert actual[3] == self.expected[3], \
            f"Q4: got '{actual[3]}', expected '{self.expected[3]}'"

    def test_q5_r4_tuple_count(self):
        """Q5: requires r4 header fix (all 180 rows counted)."""
        actual = read_output()
        assert actual[4] == self.expected[4], \
            f"Q5: got '{actual[4]}', expected '{self.expected[4]}'"

    def test_q6_cross_join_r2(self):
        """Q6: r0-r2 join depending on r2 endianness fix."""
        actual = read_output()
        assert actual[5] == self.expected[5], \
            f"Q6: got '{actual[5]}', expected '{self.expected[5]}'"

    def test_q7_r3_delta_and_r4(self):
        """Q7: r3-r4 join — requires r3.c4 delta decode and r4 header fix."""
        actual = read_output()
        assert actual[6] == self.expected[6], \
            f"Q7: got '{actual[6]}', expected '{self.expected[6]}'"

    def test_q8_three_way_join(self):
        """Q8: 3-way join across r0, r1 (header), r3 (swap + delta)."""
        actual = read_output()
        assert actual[7] == self.expected[7], \
            f"Q8: got '{actual[7]}', expected '{self.expected[7]}'"

    def test_q9_null_result(self):
        """Q9: impossible filter should yield NULL."""
        actual = read_output()
        assert actual[8] == "NULL", \
            f"Q9: expected NULL, got '{actual[8]}'"

    def test_q10_r3_all_corruptions(self):
        """Q10: requires r3 swap + delta decode (filters on c1, c3, sums c4)."""
        actual = read_output()
        assert actual[9] == self.expected[9], \
            f"Q10: got '{actual[9]}', expected '{self.expected[9]}'"

    def test_all_results(self):
        """Every query result must match expected."""
        actual = read_output()
        for i, (a, e) in enumerate(zip(actual, self.expected)):
            assert a == e, f"Q{i+1}: got '{a}', expected '{e}'"
