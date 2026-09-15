
"""
Tests for the magma equational theory audit task.
Verifies corrected matrix, counterexamples, error report, and Hasse diagram.
"""

import json
import csv
import os
import re
import pytest


# --- Ground truth ---

CORRECT_MATRIX = [
    [1, 0, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1],
    [0, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 1],
    [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 1, 0, 0, 0, 0, 0, 1, 0, 0],
    [0, 0, 0, 0, 1, 0, 0, 1, 1, 1, 0, 0],
    [0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0],
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1],
]

EXPECTED_ERRORS = {
    (1, 9, 0, 1),
    (1, 11, 0, 1),
    (2, 12, 0, 1),
    (3, 6, 1, 0),
    (4, 5, 1, 0),
    (5, 10, 0, 1),
    (6, 7, 1, 0),
    (8, 9, 1, 0),
}

EXPECTED_HASSE_EDGES = {
    (1, 3), (1, 5), (1, 6), (1, 7), (1, 11), (1, 12),
    (2, 3), (2, 5), (2, 6), (2, 7), (2, 11), (2, 12),
    (4, 10),
    (5, 8), (5, 9), (5, 10),
}


# --- Equation checker (self-contained, independent of solution code) ---

def _f(table, n, a, b):
    """Apply the magma binary operation."""
    return table[a * n + b]


def check_equation(eq_id, table, n):
    """Check if equation eq_id holds universally on a magma of order n."""
    rng = range(n)
    if eq_id == 1:  # f(x,y) = x
        return all(_f(table, n, x, y) == x
                   for x in rng for y in rng)
    elif eq_id == 2:  # f(x,y) = y
        return all(_f(table, n, x, y) == y
                   for x in rng for y in rng)
    elif eq_id == 3:  # f(x,x) = x
        return all(_f(table, n, x, x) == x
                   for x in rng)
    elif eq_id == 4:  # f(x,y) = f(y,x)
        return all(_f(table, n, x, y) == _f(table, n, y, x)
                   for x in rng for y in rng)
    elif eq_id == 5:  # f(f(x,y),z) = f(x,f(y,z))
        return all(_f(table, n, _f(table, n, x, y), z) ==
                   _f(table, n, x, _f(table, n, y, z))
                   for x in rng for y in rng for z in rng)
    elif eq_id == 6:  # f(x,f(x,y)) = f(x,y)
        return all(_f(table, n, x, _f(table, n, x, y)) ==
                   _f(table, n, x, y)
                   for x in rng for y in rng)
    elif eq_id == 7:  # f(f(x,y),y) = f(x,y)
        return all(_f(table, n, _f(table, n, x, y), y) ==
                   _f(table, n, x, y)
                   for x in rng for y in rng)
    elif eq_id == 8:  # f(f(x,x),y) = f(x,f(x,y))
        return all(_f(table, n, _f(table, n, x, x), y) ==
                   _f(table, n, x, _f(table, n, x, y))
                   for x in rng for y in rng)
    elif eq_id == 9:  # f(x,f(y,y)) = f(f(x,y),y)
        return all(_f(table, n, x, _f(table, n, y, y)) ==
                   _f(table, n, _f(table, n, x, y), y)
                   for x in rng for y in rng)
    elif eq_id == 10:  # f(f(x,y),x) = f(x,f(y,x))
        return all(_f(table, n, _f(table, n, x, y), x) ==
                   _f(table, n, x, _f(table, n, y, x))
                   for x in rng for y in rng)
    elif eq_id == 11:  # f(x,f(y,z)) = f(f(x,y),f(x,z))
        return all(_f(table, n, x, _f(table, n, y, z)) ==
                   _f(table, n, _f(table, n, x, y), _f(table, n, x, z))
                   for x in rng for y in rng for z in rng)
    elif eq_id == 12:  # f(f(x,y),f(z,w)) = f(f(x,z),f(y,w))
        return all(_f(table, n, _f(table, n, x, y), _f(table, n, z, w)) ==
                   _f(table, n, _f(table, n, x, z), _f(table, n, y, w))
                   for x in rng for y in rng for z in rng for w in rng)
    return False


def _parse_dot_edges(content):
    """Extract directed edges from DOT source, skipping comment lines."""
    edges = set()
    for line in content.split('\n'):
        stripped = line.strip()
        if stripped.startswith('//') or stripped.startswith('#'):
            continue
        for m in re.finditer(
            r'["\']?E?(\d+)["\']?\s*->\s*["\']?E?(\d+)["\']?', stripped
        ):
            edges.add((int(m.group(1)), int(m.group(2))))
    return edges


# --- Tests ---

class TestCorrectedMatrix:
    def test_file_exists(self):
        assert os.path.exists("/app/results/corrected_matrix.csv"), \
            "corrected_matrix.csv not found"

    def test_dimensions(self):
        with open("/app/results/corrected_matrix.csv") as fp:
            reader = csv.reader(fp)
            rows = [row for row in reader if row]
        assert len(rows) == 12, f"Expected 12 rows, got {len(rows)}"
        for i, row in enumerate(rows):
            assert len(row) == 12, f"Row {i}: expected 12 cols, got {len(row)}"

    def test_matrix_correct(self):
        with open("/app/results/corrected_matrix.csv") as fp:
            reader = csv.reader(fp)
            rows = [[int(x) for x in row] for row in reader if row]
        for i in range(12):
            for j in range(12):
                assert rows[i][j] == CORRECT_MATRIX[i][j], (
                    f"corrected_matrix[{i}][{j}] (E{i+1}->E{j+1}): "
                    f"expected {CORRECT_MATRIX[i][j]}, got {rows[i][j]}"
                )

    def test_diagonal_ones(self):
        with open("/app/results/corrected_matrix.csv") as fp:
            reader = csv.reader(fp)
            rows = [[int(x) for x in row] for row in reader if row]
        for i in range(12):
            assert rows[i][i] == 1, f"Diagonal [{i}][{i}] should be 1"

    def test_implication_count(self):
        with open("/app/results/corrected_matrix.csv") as fp:
            reader = csv.reader(fp)
            rows = [[int(x) for x in row] for row in reader if row]
        total = sum(rows[i][j] for i in range(12) for j in range(12))
        assert total == 34, f"Expected 34 total 1s, got {total}"


class TestCounterexamples:
    def test_file_exists(self):
        assert os.path.exists("/app/results/counterexamples.json"), \
            "counterexamples.json not found"

    def test_completeness(self):
        """Every non-implication must have a counterexample."""
        with open("/app/results/counterexamples.json") as fp:
            ce = json.load(fp)
        for i in range(12):
            for j in range(12):
                if CORRECT_MATRIX[i][j] == 0:
                    key = f"{i+1},{j+1}"
                    assert key in ce, \
                        f"Missing counterexample for E{i+1} -/-> E{j+1}"

    def test_no_spurious_entries(self):
        """No counterexample should exist for actual implications."""
        with open("/app/results/counterexamples.json") as fp:
            ce = json.load(fp)
        for key in ce:
            i_s, j_s = key.split(",")
            i, j = int(i_s) - 1, int(j_s) - 1
            assert CORRECT_MATRIX[i][j] == 0, (
                f"Spurious counterexample for implication E{i+1} -> E{j+1}"
            )

    def test_counterexample_validity(self):
        """Each counterexample must satisfy E_i but not E_j."""
        with open("/app/results/counterexamples.json") as fp:
            ce = json.load(fp)
        for key, data in ce.items():
            i_s, j_s = key.split(",")
            ei, ej = int(i_s), int(j_s)
            n = data["order"]
            table = data["table"]
            assert len(table) == n * n, \
                f"CE {key}: table length {len(table)} != {n}*{n}"
            assert all(0 <= v < n for v in table), \
                f"CE {key}: table values out of range"
            assert check_equation(ei, table, n), \
                f"CE {key}: magma does not satisfy E{i_s}"
            assert not check_equation(ej, table, n), \
                f"CE {key}: magma should NOT satisfy E{j_s}"

    def test_counterexample_order_bounds(self):
        with open("/app/results/counterexamples.json") as fp:
            ce = json.load(fp)
        for key, data in ce.items():
            assert data["order"] <= 3, \
                f"CE {key}: order {data['order']} > 3"

    def test_counterexample_count(self):
        with open("/app/results/counterexamples.json") as fp:
            ce = json.load(fp)
        assert len(ce) == 110, f"Expected 110 counterexamples, got {len(ce)}"


class TestErrorReport:
    def test_file_exists(self):
        assert os.path.exists("/app/results/error_report.json"), \
            "error_report.json not found"

    def test_error_count(self):
        with open("/app/results/error_report.json") as fp:
            errors = json.load(fp)
        assert len(errors) == 8, f"Expected 8 errors, got {len(errors)}"

    def test_all_errors_found(self):
        with open("/app/results/error_report.json") as fp:
            errors = json.load(fp)
        found = {(e["row"], e["col"], e["claimed"], e["correct"])
                 for e in errors}
        for expected in EXPECTED_ERRORS:
            assert expected in found, f"Missing error: row={expected[0]}, " \
                f"col={expected[1]}, claimed={expected[2]}, correct={expected[3]}"

    def test_no_spurious_errors(self):
        with open("/app/results/error_report.json") as fp:
            errors = json.load(fp)
        found = {(e["row"], e["col"], e["claimed"], e["correct"])
                 for e in errors}
        for err in found:
            assert err in EXPECTED_ERRORS, f"Spurious error: {err}"


class TestHasseDiagram:
    def test_dot_file_exists(self):
        assert os.path.exists("/app/results/hasse.dot"), \
            "hasse.dot not found"

    def test_png_file_exists(self):
        assert os.path.exists("/app/results/hasse.png"), \
            "hasse.png not found"

    def test_png_valid(self):
        with open("/app/results/hasse.png", "rb") as fp:
            header = fp.read(8)
        assert header[:4] == b'\x89PNG', \
            "hasse.png is not a valid PNG file"

    def test_dot_edges_correct(self):
        with open("/app/results/hasse.dot") as fp:
            content = fp.read()
        edges = _parse_dot_edges(content)
        assert edges == EXPECTED_HASSE_EDGES, (
            f"Hasse edges mismatch.\n"
            f"Expected: {sorted(EXPECTED_HASSE_EDGES)}\n"
            f"Actual:   {sorted(edges)}"
        )

    def test_dot_edge_count(self):
        with open("/app/results/hasse.dot") as fp:
            content = fp.read()
        edges = _parse_dot_edges(content)
        assert len(edges) == 16, f"Expected 16 Hasse edges, got {len(edges)}"

    def test_dot_edges_are_implications(self):
        """Every Hasse edge must be an implication in the corrected matrix."""
        with open("/app/results/hasse.dot") as fp:
            content = fp.read()
        edges = _parse_dot_edges(content)
        for i, j in edges:
            assert CORRECT_MATRIX[i - 1][j - 1] == 1, \
                f"Hasse edge E{i}->E{j} is not an implication"

    def test_dot_no_transitive_edges(self):
        """No Hasse edge should be a transitive consequence of others."""
        with open("/app/results/hasse.dot") as fp:
            content = fp.read()
        edges = _parse_dot_edges(content)
        adj = {i: set() for i in range(1, 13)}
        for a, b in edges:
            adj[a].add(b)
        for a, b in list(edges):
            adj[a].discard(b)
            visited = set()
            stack = [a]
            reachable = False
            while stack:
                node = stack.pop()
                if node == b:
                    reachable = True
                    break
                for nb in adj.get(node, set()):
                    if nb not in visited:
                        visited.add(nb)
                        stack.append(nb)
            adj[a].add(b)
            assert not reachable, \
                f"Edge E{a}->E{b} is transitive through other edges"
