
"""
Tests for the equational theory lattice pipeline.
Independently recomputes all ground truth from source data and validates
agent output across Z3 counterexamples, isomorphism classes, implications,
Hasse diagram (JSON + SVG), and SQLite database.
"""

import json
import os
import itertools
import sqlite3
import pytest


# ---------------------------------------------------------------------------
# Core evaluation helpers (independent ground-truth computation)
# ---------------------------------------------------------------------------

def eval_term(term, env, table):
    """Evaluate an AST term given variable bindings and an operation table."""
    if isinstance(term, str):
        return env[term]
    left = eval_term(term["args"][0], env, table)
    right = eval_term(term["args"][1], env, table)
    return table[left][right]


def check_equation(eq, table):
    """Return True iff table satisfies eq under every variable assignment."""
    n = len(table)
    for assignment in itertools.product(range(n), repeat=len(eq["vars"])):
        env = dict(zip(eq["vars"], assignment))
        if eval_term(eq["lhs"], env, table) != eval_term(eq["rhs"], env, table):
            return False
    return True


def canonical_form(table, n):
    """Compute canonical (lex-min) form of a magma table under Sym(n)."""
    min_form = None
    for perm in itertools.permutations(range(n)):
        new_flat = [0] * (n * n)
        for i in range(n):
            for j in range(n):
                new_flat[perm[i] * n + perm[j]] = perm[table[i][j]]
        t = tuple(new_flat)
        if min_form is None or t < min_form:
            min_form = t
    return min_form


def compute_hasse(implications, eq_names):
    """Transitive reduction of the strict implication graph."""
    strict = {e: set() for e in eq_names}
    for ei in eq_names:
        for ej in eq_names:
            if ei != ej and implications[f"{ei}->{ej}"] and not implications[f"{ej}->{ei}"]:
                strict[ei].add(ej)

    hasse = {}
    for ei in eq_names:
        hasse[ei] = []
        for ej in strict[ei]:
            redundant = any(
                ek in strict[ei] and ej in strict[ek]
                for ek in eq_names
                if ek != ei and ek != ej
            )
            if not redundant:
                hasse[ei].append(ej)
        hasse[ei].sort()
    return hasse


# ---------------------------------------------------------------------------
# Session-scoped fixture: compute all ground truth exactly once
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def ground_truth():
    with open("/app/equations.json") as f:
        equations = json.load(f)
    with open("/app/magmas.json") as f:
        magmas = json.load(f)

    eq_names = sorted(equations.keys())
    n = 3

    # --- full size-3 enumeration with isomorphism classification ---
    counts = {e: 0 for e in eq_names}
    satisfying_sets = {e: set() for e in eq_names}
    iso_class_eq_sets = {e: set() for e in eq_names}
    all_iso_classes = set()

    for idx, flat in enumerate(itertools.product(range(n), repeat=n * n)):
        table = [list(flat[i * n:(i + 1) * n]) for i in range(n)]
        canon = canonical_form(table, n)
        all_iso_classes.add(canon)

        for ename in eq_names:
            if check_equation(equations[ename], table):
                counts[ename] += 1
                satisfying_sets[ename].add(idx)
                iso_class_eq_sets[ename].add(canon)

    # --- implications ---
    implications = {}
    for ei in eq_names:
        for ej in eq_names:
            implications[f"{ei}->{ej}"] = satisfying_sets[ei].issubset(
                satisfying_sets[ej]
            )

    # --- Hasse diagram ---
    hasse = compute_hasse(implications, eq_names)

    return {
        "equations": equations,
        "magmas": magmas,
        "eq_names": eq_names,
        "size3_counts": counts,
        "satisfying_sets": satisfying_sets,
        "implications": implications,
        "hasse": hasse,
        "total_iso_classes": len(all_iso_classes),
        "iso_class_per_eq": {e: len(iso_class_eq_sets[e]) for e in eq_names},
    }


# ---------------------------------------------------------------------------
# Tests: Z3 counterexamples
# ---------------------------------------------------------------------------

class TestZ3Counterexamples:
    def test_file_exists(self):
        assert os.path.exists("/app/results/z3_counterexamples.json"), \
            "z3_counterexamples.json not found"

    def test_all_56_pairs_present(self, ground_truth):
        with open("/app/results/z3_counterexamples.json") as f:
            results = json.load(f)
        eq_names = ground_truth["eq_names"]
        for ei in eq_names:
            for ej in eq_names:
                if ei != ej:
                    key = f"{ei}->{ej}"
                    assert key in results, f"Missing pair {key}"

    def test_counterexamples_valid(self, ground_truth):
        """Each non-null counterexample must satisfy premise and violate conclusion."""
        with open("/app/results/z3_counterexamples.json") as f:
            results = json.load(f)
        equations = ground_truth["equations"]
        for key, value in results.items():
            if value is None:
                continue
            ei, ej = key.split("->")
            table = value["table"]
            sz = value["size"]
            assert 2 <= sz <= 3, f"{key}: size {sz} not in [2, 3]"
            assert len(table) == sz, f"{key}: table has {len(table)} rows, expected {sz}"
            for r, row in enumerate(table):
                assert len(row) == sz, f"{key}: row {r} has {len(row)} cols, expected {sz}"
                for v in row:
                    assert 0 <= v < sz, f"{key}: invalid entry {v} for size {sz}"
            assert check_equation(equations[ei], table), \
                f"{key}: counterexample does not satisfy premise {ei}"
            assert not check_equation(equations[ej], table), \
                f"{key}: counterexample satisfies conclusion {ej} (should violate it)"

    def test_counterexamples_minimal(self, ground_truth):
        """If counterexample has size 3, no size-2 counterexample may exist."""
        with open("/app/results/z3_counterexamples.json") as f:
            results = json.load(f)
        equations = ground_truth["equations"]
        for key, value in results.items():
            if value is None or value["size"] <= 2:
                continue
            ei, ej = key.split("->")
            # Exhaustively check all 16 size-2 operation tables
            for flat in itertools.product(range(2), repeat=4):
                tbl = [list(flat[0:2]), list(flat[2:4])]
                if check_equation(equations[ei], tbl) and \
                   not check_equation(equations[ej], tbl):
                    pytest.fail(
                        f"{key}: reported size {value['size']} but size-2 "
                        f"counterexample exists: {tbl}"
                    )

    def test_consistency_with_enumeration(self, ground_truth):
        """Z3 results must be consistent with brute-force enumeration."""
        with open("/app/results/z3_counterexamples.json") as f:
            results = json.load(f)
        impl = ground_truth["implications"]
        for key, value in results.items():
            # If Z3 found no counterexample, enum must confirm implication
            if value is None:
                assert impl[key], \
                    f"{key}: Z3 found no counterexample but enumeration " \
                    f"shows non-implication over size-3"
            # If enumeration shows non-implication, Z3 must have found something
            if not impl[key]:
                assert value is not None, \
                    f"{key}: enumeration shows non-implication but Z3 " \
                    f"reports no counterexample"


# ---------------------------------------------------------------------------
# Tests: Isomorphism classes
# ---------------------------------------------------------------------------

class TestIsoClasses:
    def test_file_exists(self):
        assert os.path.exists("/app/results/iso_classes.json"), \
            "iso_classes.json not found"

    def test_total_classes(self, ground_truth):
        with open("/app/results/iso_classes.json") as f:
            result = json.load(f)
        expected = ground_truth["total_iso_classes"]
        assert result["total_classes"] == expected, \
            f"Expected {expected} total iso classes, got {result['total_classes']}"

    def test_per_equation_classes(self, ground_truth):
        with open("/app/results/iso_classes.json") as f:
            result = json.load(f)
        for ename in ground_truth["eq_names"]:
            assert ename in result["per_equation"], \
                f"Missing equation {ename} in per_equation"
            expected = ground_truth["iso_class_per_eq"][ename]
            actual = result["per_equation"][ename]
            assert actual == expected, \
                f"{ename}: expected {expected} iso classes, got {actual}"


# ---------------------------------------------------------------------------
# Tests: Implication matrix
# ---------------------------------------------------------------------------

class TestImplications:
    def test_file_exists(self):
        assert os.path.exists("/app/results/implications.json"), \
            "implications.json not found"

    def test_all_64_pairs(self, ground_truth):
        with open("/app/results/implications.json") as f:
            result = json.load(f)
        for key in ground_truth["implications"]:
            assert key in result, f"Missing implication key {key}"

    def test_correct(self, ground_truth):
        with open("/app/results/implications.json") as f:
            result = json.load(f)
        for key, expected in ground_truth["implications"].items():
            assert result[key] == expected, \
                f"Implication {key}: expected {expected}, got {result.get(key)}"


# ---------------------------------------------------------------------------
# Tests: Hasse diagram (JSON)
# ---------------------------------------------------------------------------

class TestHasseJson:
    def test_file_exists(self):
        assert os.path.exists("/app/results/hasse.json"), \
            "hasse.json not found"

    def test_correct(self, ground_truth):
        with open("/app/results/hasse.json") as f:
            result = json.load(f)
        for ename in ground_truth["eq_names"]:
            assert ename in result, f"Missing equation {ename} in Hasse diagram"
            assert sorted(result[ename]) == sorted(ground_truth["hasse"][ename]), \
                f"Hasse {ename}: expected {ground_truth['hasse'][ename]}, " \
                f"got {result[ename]}"


# ---------------------------------------------------------------------------
# Tests: Hasse diagram (SVG via Graphviz)
# ---------------------------------------------------------------------------

class TestHasseSvg:
    def test_file_exists(self):
        assert os.path.exists("/app/results/hasse.svg"), \
            "hasse.svg not found"

    def test_is_valid_svg(self):
        with open("/app/results/hasse.svg") as f:
            content = f.read()
        assert len(content) > 200, \
            "SVG file is too small to be a valid rendering"
        assert "<svg" in content, \
            "File does not contain <svg> tag"
        assert "</svg>" in content, \
            "File does not contain closing </svg> tag"

    def test_contains_all_equation_ids(self, ground_truth):
        with open("/app/results/hasse.svg") as f:
            content = f.read()
        for ename in ground_truth["eq_names"]:
            assert ename in content, \
                f"SVG missing equation node label {ename}"

    def test_has_graph_structure(self):
        with open("/app/results/hasse.svg") as f:
            content = f.read()
        # Graphviz SVG uses path elements for edges and shapes
        has_paths = "<path" in content
        has_polygons = "<polygon" in content
        assert has_paths or has_polygons, \
            "SVG has no path or polygon elements (no graph structure)"


# ---------------------------------------------------------------------------
# Tests: SQLite database
# ---------------------------------------------------------------------------

class TestSqliteDb:
    def test_file_exists(self):
        assert os.path.exists("/app/results/magma_theory.db"), \
            "magma_theory.db not found"

    def test_equations_table_schema(self):
        conn = sqlite3.connect("/app/results/magma_theory.db")
        c = conn.cursor()
        c.execute("PRAGMA table_info(equations)")
        cols = {row[1]: row[2].upper() for row in c.fetchall()}
        conn.close()
        assert "id" in cols, "equations table missing 'id' column"
        assert "name" in cols, "equations table missing 'name' column"
        assert "display" in cols, "equations table missing 'display' column"
        assert "num_vars" in cols, "equations table missing 'num_vars' column"

    def test_equations_data(self, ground_truth):
        conn = sqlite3.connect("/app/results/magma_theory.db")
        c = conn.cursor()
        c.execute("SELECT id, name, display, num_vars FROM equations ORDER BY id")
        rows = c.fetchall()
        conn.close()
        eq_names = ground_truth["eq_names"]
        assert len(rows) == len(eq_names), \
            f"Expected {len(eq_names)} equation rows, got {len(rows)}"
        for row, ename in zip(rows, eq_names):
            eq = ground_truth["equations"][ename]
            assert row[0] == ename, f"Expected id {ename}, got {row[0]}"
            assert row[1] == eq["name"], \
                f"Equation {ename}: expected name '{eq['name']}', got '{row[1]}'"
            assert row[2] == eq["display"], \
                f"Equation {ename}: expected display '{eq['display']}', got '{row[2]}'"
            assert row[3] == len(eq["vars"]), \
                f"Equation {ename}: expected {len(eq['vars'])} vars, got {row[3]}"

    def test_implications_table_schema(self):
        conn = sqlite3.connect("/app/results/magma_theory.db")
        c = conn.cursor()
        c.execute("PRAGMA table_info(implications)")
        cols = {row[1] for row in c.fetchall()}
        conn.close()
        assert "premise_id" in cols, "implications table missing 'premise_id'"
        assert "conclusion_id" in cols, "implications table missing 'conclusion_id'"
        assert "holds" in cols, "implications table missing 'holds'"
        assert "counterexample_size" in cols, \
            "implications table missing 'counterexample_size'"
        assert "counterexample_table" in cols, \
            "implications table missing 'counterexample_table'"

    def test_implications_data(self, ground_truth):
        conn = sqlite3.connect("/app/results/magma_theory.db")
        c = conn.cursor()
        c.execute(
            "SELECT premise_id, conclusion_id, holds FROM implications"
        )
        rows = c.fetchall()
        conn.close()
        db_impl = {f"{r[0]}->{r[1]}": bool(r[2]) for r in rows}
        expected = ground_truth["implications"]
        assert len(db_impl) == len(expected), \
            f"Expected {len(expected)} implication rows, got {len(db_impl)}"
        for key, exp_val in expected.items():
            assert key in db_impl, f"Missing implication {key} in database"
            assert db_impl[key] == exp_val, \
                f"DB implication {key}: expected {exp_val}, got {db_impl[key]}"

    def test_iso_class_stats_schema(self):
        conn = sqlite3.connect("/app/results/magma_theory.db")
        c = conn.cursor()
        c.execute("PRAGMA table_info(iso_class_stats)")
        cols = {row[1] for row in c.fetchall()}
        conn.close()
        assert "equation_id" in cols, \
            "iso_class_stats table missing 'equation_id'"
        assert "num_satisfying_classes" in cols, \
            "iso_class_stats table missing 'num_satisfying_classes'"
        assert "num_satisfying_tables" in cols, \
            "iso_class_stats table missing 'num_satisfying_tables'"

    def test_iso_class_stats_data(self, ground_truth):
        conn = sqlite3.connect("/app/results/magma_theory.db")
        c = conn.cursor()
        c.execute(
            "SELECT equation_id, num_satisfying_classes, num_satisfying_tables "
            "FROM iso_class_stats ORDER BY equation_id"
        )
        rows = c.fetchall()
        conn.close()
        eq_names = ground_truth["eq_names"]
        assert len(rows) == len(eq_names), \
            f"Expected {len(eq_names)} iso_class_stats rows, got {len(rows)}"
        for row in rows:
            ename = row[0]
            assert ename in ground_truth["iso_class_per_eq"], \
                f"Unknown equation {ename} in iso_class_stats"
            exp_classes = ground_truth["iso_class_per_eq"][ename]
            exp_tables = ground_truth["size3_counts"][ename]
            assert row[1] == exp_classes, \
                f"iso_class_stats {ename}: expected {exp_classes} classes, " \
                f"got {row[1]}"
            assert row[2] == exp_tables, \
                f"iso_class_stats {ename}: expected {exp_tables} tables, " \
                f"got {row[2]}"
