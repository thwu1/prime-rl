
"""Tests for OCM ILP Pipeline: LP models, glpsol output, solutions, SQLite DB."""
import os
import re
import sqlite3
import pytest

INSTANCES_DIR = "/app/instances"
MODELS_DIR = "/app/models"
SOLUTIONS_DIR = "/app/solutions"
DB_PATH = "/app/results.db"

OPTIMAL_CROSSINGS = {
    "instance_01": 2,
    "instance_02": 18,
    "instance_03": 53,
    "instance_04": 125,
    "instance_05": 217,
    "instance_06": 361,
}

INSTANCE_PARAMS = {
    "instance_01": (3, 4, 7),
    "instance_02": (5, 7, 14),
    "instance_03": (7, 10, 22),
    "instance_04": (8, 14, 30),
    "instance_05": (12, 18, 42),
    "instance_06": (15, 22, 55),
}

ALL_NAMES = sorted(OPTIMAL_CROSSINGS.keys())


def parse_instance(filepath):
    n0 = n1 = m = 0
    edges = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("p"):
                parts = line.split()
                n0, n1, m = int(parts[2]), int(parts[3]), int(parts[4])
            else:
                parts = line.split()
                edges.append((int(parts[0]), int(parts[1])))
    return n0, n1, edges


def count_crossings(edges, perm):
    pos = {v: i for i, v in enumerate(perm)}
    crossings = 0
    for i in range(len(edges)):
        a1, b1 = edges[i]
        for j in range(i + 1, len(edges)):
            a2, b2 = edges[j]
            if a1 == a2 or b1 == b2:
                continue
            if (a1 < a2 and pos[b1] > pos[b2]) or (a1 > a2 and pos[b1] < pos[b2]):
                crossings += 1
    return crossings


# ---- LP Model Tests ----

class TestLPModels:
    """Verify ILP model files are valid CPLEX LP format."""

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_lp_file_exists(self, name):
        path = os.path.join(MODELS_DIR, f"{name}.lp")
        assert os.path.isfile(path), f"LP model missing: {path}"

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_lp_has_required_sections(self, name):
        path = os.path.join(MODELS_DIR, f"{name}.lp")
        with open(path) as f:
            content = f.read()
        low = content.lower()
        assert "minimize" in low or "maximize" in low, \
            "LP file missing Minimize/Maximize section"
        assert "subject to" in low or "\nst\n" in low or "\nst " in low, \
            "LP file missing Subject To section"
        assert "binary" in low, "LP file missing Binary section"
        assert re.search(r'(?m)^\s*end\s*$', low), "LP file missing End keyword"

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_lp_binary_variable_count(self, name):
        """Binary section should have at least C(n_b, 2) variables."""
        path = os.path.join(MODELS_DIR, f"{name}.lp")
        _, n_b, _ = INSTANCE_PARAMS[name]
        expected_min = n_b * (n_b - 1) // 2

        with open(path) as f:
            content = f.read()

        binary_match = re.search(
            r'(?i)\bbinary\b(.*?)(?:\bend\b|\bgeneral\b)',
            content, re.DOTALL
        )
        assert binary_match, "Could not find Binary section in LP file"
        var_names = binary_match.group(1).split()
        assert len(var_names) >= expected_min, (
            f"Expected >= {expected_min} binary vars for n_b={n_b}, "
            f"found {len(var_names)}"
        )

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_lp_has_constraints(self, name):
        """Subject To section must contain constraints."""
        path = os.path.join(MODELS_DIR, f"{name}.lp")
        with open(path) as f:
            content = f.read()
        # Extract text between Subject To and next section
        st_match = re.search(
            r'(?i)(?:subject\s+to|^st\b)(.*?)(?:bounds|binary|general|end)',
            content, re.DOTALL
        )
        assert st_match, "Could not parse Subject To section"
        constraints_text = st_match.group(1).strip()
        # Count lines with <= or >= or = operators (constraint lines)
        constraint_lines = re.findall(r'<=|>=|=', constraints_text)
        assert len(constraint_lines) >= 2, (
            f"Expected multiple constraints, found {len(constraint_lines)}"
        )


# ---- GLPK Output Tests ----

class TestGLPKOutput:
    """Verify glpsol was executed and produced valid output."""

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_glpsol_output_exists(self, name):
        path = os.path.join(MODELS_DIR, f"{name}.out")
        assert os.path.isfile(path), f"glpsol output missing: {path}"

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_glpsol_reports_optimal(self, name):
        path = os.path.join(MODELS_DIR, f"{name}.out")
        with open(path) as f:
            content = f.read()
        assert re.search(r'(?i)status.*optimal', content), (
            f"glpsol output for {name} does not indicate OPTIMAL status"
        )

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_glpsol_output_has_columns(self, name):
        """Output must contain a Column section with variable activities."""
        path = os.path.join(MODELS_DIR, f"{name}.out")
        with open(path) as f:
            content = f.read()
        assert "Column name" in content, (
            "glpsol output missing Column section — was --output flag used?"
        )


# ---- Solution Tests ----

class TestSolutions:
    """Verify solution files are correct and optimal."""

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_solution_exists(self, name):
        path = os.path.join(SOLUTIONS_DIR, f"{name}.sol")
        assert os.path.isfile(path), f"Solution file missing: {path}"

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_solution_valid_permutation(self, name):
        n0, n1, _ = INSTANCE_PARAMS[name]
        sol_path = os.path.join(SOLUTIONS_DIR, f"{name}.sol")
        with open(sol_path) as f:
            perm = [
                int(line.strip()) for line in f
                if line.strip() and not line.startswith("c")
            ]
        expected = set(range(n0 + 1, n0 + n1 + 1))
        assert len(perm) == n1, f"Expected {n1} vertices, got {len(perm)}"
        assert set(perm) == expected, (
            f"Not a valid permutation of B vertices. "
            f"Missing: {expected - set(perm)}, Extra: {set(perm) - expected}"
        )

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_solution_optimal_crossings(self, name):
        inst_path = os.path.join(INSTANCES_DIR, f"{name}.gr")
        sol_path = os.path.join(SOLUTIONS_DIR, f"{name}.sol")

        n0, n1, edges = parse_instance(inst_path)
        with open(sol_path) as f:
            perm = [
                int(line.strip()) for line in f
                if line.strip() and not line.startswith("c")
            ]

        crossings = count_crossings(edges, perm)
        expected = OPTIMAL_CROSSINGS[name]
        assert crossings == expected, (
            f"{name}: got {crossings} crossings, expected optimal {expected}"
        )


# ---- SQLite Database Tests ----

class TestDatabase:
    """Verify the SQLite results database schema and content."""

    def test_database_exists(self):
        assert os.path.isfile(DB_PATH), f"Database missing: {DB_PATH}"

    def test_instances_table_schema(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(instances)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        for col in ("name", "n_a", "n_b", "n_edges"):
            assert col in cols, f"Missing column in instances table: {col}"

    def test_solutions_table_schema(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(solutions)")
        cols = {row[1] for row in cur.fetchall()}
        conn.close()
        for col in ("instance_name", "crossings", "permutation", "solve_status"):
            assert col in cols, f"Missing column in solutions table: {col}"

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_instances_table_data(self, name):
        n_a, n_b, n_e = INSTANCE_PARAMS[name]
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT n_a, n_b, n_edges FROM instances WHERE name = ?", (name,)
        )
        row = cur.fetchone()
        conn.close()
        assert row is not None, f"No row for '{name}' in instances table"
        assert row == (n_a, n_b, n_e), (
            f"{name}: expected ({n_a}, {n_b}, {n_e}), got {row}"
        )

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_solutions_table_crossings(self, name):
        expected_crossings = OPTIMAL_CROSSINGS[name]
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT crossings, solve_status FROM solutions "
            "WHERE instance_name = ?",
            (name,),
        )
        row = cur.fetchone()
        conn.close()
        assert row is not None, f"No row for '{name}' in solutions table"
        assert row[0] == expected_crossings, (
            f"{name}: DB says {row[0]} crossings, expected {expected_crossings}"
        )
        assert "optimal" in row[1].lower(), (
            f"{name}: unexpected solve_status '{row[1]}'"
        )

    @pytest.mark.parametrize("name", ALL_NAMES)
    def test_solutions_table_permutation(self, name):
        n_a, n_b, _ = INSTANCE_PARAMS[name]
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT permutation FROM solutions WHERE instance_name = ?",
            (name,),
        )
        row = cur.fetchone()
        conn.close()
        assert row is not None, f"No row for '{name}' in solutions table"
        perm = [int(x) for x in row[0].split(",")]
        expected = set(range(n_a + 1, n_a + n_b + 1))
        assert len(perm) == n_b, f"Permutation length mismatch in DB for {name}"
        assert set(perm) == expected, (
            f"{name}: permutation in DB is not a valid permutation of B vertices"
        )
