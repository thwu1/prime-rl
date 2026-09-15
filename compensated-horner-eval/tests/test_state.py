"""
Tests for high-accuracy polynomial evaluation pipeline.
Verifies database results, accuracy against exact rational arithmetic,
output file conformance, and Makefile structure.
"""

import pytest
import json
import sqlite3
import os
import math
from fractions import Fraction

DB_PATH = '/app/polyeval.db'
RESULTS_JSON = '/app/results.json'
SCHEMA_JSON = '/app/schema.json'
MAKEFILE_PATH = '/app/Makefile'


def exact_poly_eval(coefficients, x):
    """Evaluate polynomial exactly using Fraction arithmetic.
    coefficients[i] is the coefficient of x^i."""
    fx = Fraction(x)
    result = Fraction(0)
    for i, c in enumerate(coefficients):
        result += Fraction(c) * fx ** i
    return result


def naive_horner_ref(coefficients, x):
    """Reference standard Horner evaluation."""
    n = len(coefficients) - 1
    result = float(coefficients[n])
    for k in range(n - 1, -1, -1):
        result = result * x + float(coefficients[k])
    return result


def get_all_results():
    """Fetch all results joined with polynomial data from the database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT p.name, p.coefficients, p.eval_point,
               r.compensated_value, r.error_bound, r.naive_value
        FROM results r
        JOIN polynomials p ON r.poly_id = p.id
        ORDER BY p.id
    """).fetchall()
    conn.close()
    return rows


class TestDatabaseResults:
    """Verify the results table exists with correct structure and data."""

    def test_results_table_exists(self):
        """Results table must exist in the database."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='results'"
        )
        assert cursor.fetchone() is not None, "results table does not exist in polyeval.db"
        conn.close()

    def test_results_count(self):
        """Must have one result per polynomial."""
        conn = sqlite3.connect(DB_PATH)
        poly_count = conn.execute("SELECT COUNT(*) FROM polynomials").fetchone()[0]
        result_count = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        assert result_count == poly_count, (
            f"Expected {poly_count} results, got {result_count}"
        )
        conn.close()

    def test_results_required_columns(self):
        """Results table must have the required columns."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.execute("PRAGMA table_info(results)")
        columns = {row[1] for row in cursor.fetchall()}
        required = {'poly_id', 'compensated_value', 'error_bound', 'naive_value'}
        assert required.issubset(columns), (
            f"Missing columns: {required - columns}"
        )
        conn.close()

    def test_all_poly_ids_present(self):
        """Every polynomial must have a corresponding result."""
        conn = sqlite3.connect(DB_PATH)
        poly_ids = {r[0] for r in conn.execute("SELECT id FROM polynomials").fetchall()}
        result_ids = {r[0] for r in conn.execute("SELECT poly_id FROM results").fetchall()}
        assert poly_ids == result_ids, (
            f"Missing poly_ids in results: {poly_ids - result_ids}"
        )
        conn.close()


class TestAccuracy:
    """Verify evaluation accuracy using exact rational arithmetic as ground truth."""

    def test_error_bounds_valid(self):
        """All certified error bounds must contain the true polynomial value."""
        for row in get_all_results():
            coeffs = json.loads(row['coefficients'])
            x = row['eval_point']
            comp_val = row['compensated_value']
            bound = row['error_bound']

            true_exact = exact_poly_eval(coeffs, x)
            actual_err = abs(Fraction(comp_val) - true_exact)
            # 1% margin for FP rounding in bound computation
            assert actual_err <= Fraction(bound) * Fraction(101, 100), (
                f"{row['name']}: actual error {float(actual_err):.3e} "
                f"exceeds certified bound {bound:.3e}"
            )

    def test_error_bounds_nonnegative(self):
        """All error bounds must be non-negative."""
        for row in get_all_results():
            assert row['error_bound'] >= 0, (
                f"{row['name']}: negative error bound {row['error_bound']}"
            )

    def test_compensated_beats_naive_ill_conditioned(self):
        """High-accuracy value must beat naive Horner for all ill-conditioned polynomials."""
        ill_conditioned = {'near_root_quartic', 'wilkinson_8', 'near_root_cubic'}
        for row in get_all_results():
            if row['name'] in ill_conditioned:
                coeffs = json.loads(row['coefficients'])
                x = row['eval_point']
                true_exact = exact_poly_eval(coeffs, x)

                comp_err = float(abs(Fraction(row['compensated_value']) - true_exact))
                naive_err = float(abs(Fraction(row['naive_value']) - true_exact))

                assert comp_err < naive_err, (
                    f"{row['name']}: compensated error ({comp_err:.3e}) "
                    f"not better than naive ({naive_err:.3e})"
                )

    def test_1000x_improvement_quartic(self):
        """Must achieve >1000x improvement for the near_root_quartic case."""
        for row in get_all_results():
            if row['name'] == 'near_root_quartic':
                coeffs = json.loads(row['coefficients'])
                x = row['eval_point']
                true_exact = exact_poly_eval(coeffs, x)

                comp_err = float(abs(Fraction(row['compensated_value']) - true_exact))
                naive_err = float(abs(Fraction(row['naive_value']) - true_exact))

                if comp_err == 0:
                    return  # Perfect result is acceptable

                improvement = naive_err / comp_err
                assert improvement > 1000, (
                    f"Expected >1000x improvement, got {improvement:.1f}x"
                )

    def test_1000x_improvement_wilkinson(self):
        """Must achieve >1000x improvement for the wilkinson_8 case."""
        for row in get_all_results():
            if row['name'] == 'wilkinson_8':
                coeffs = json.loads(row['coefficients'])
                x = row['eval_point']
                true_exact = exact_poly_eval(coeffs, x)

                comp_err = float(abs(Fraction(row['compensated_value']) - true_exact))
                naive_err = float(abs(Fraction(row['naive_value']) - true_exact))

                if comp_err == 0:
                    return

                improvement = naive_err / comp_err
                assert improvement > 1000, (
                    f"Expected >1000x improvement, got {improvement:.1f}x"
                )

    def test_naive_matches_horner(self):
        """The naive_value must match standard Horner evaluation exactly."""
        for row in get_all_results():
            coeffs = json.loads(row['coefficients'])
            x = row['eval_point']
            expected = naive_horner_ref(coeffs, x)
            assert row['naive_value'] == expected, (
                f"{row['name']}: naive_value {row['naive_value']} != "
                f"expected Horner result {expected}"
            )


class TestResultsJson:
    """Verify the exported results.json file."""

    def test_file_exists(self):
        """results.json must exist."""
        assert os.path.exists(RESULTS_JSON), "results.json not found at /app/results.json"

    def test_valid_json_array(self):
        """results.json must be a valid JSON array."""
        with open(RESULTS_JSON) as f:
            data = json.load(f)
        assert isinstance(data, list), "results.json must be a JSON array"

    def test_correct_count(self):
        """results.json must have one entry per polynomial."""
        with open(RESULTS_JSON) as f:
            data = json.load(f)
        conn = sqlite3.connect(DB_PATH)
        expected = conn.execute("SELECT COUNT(*) FROM polynomials").fetchone()[0]
        conn.close()
        assert len(data) == expected, f"Expected {expected} entries, got {len(data)}"

    def test_schema_conformance(self):
        """results.json must conform to the JSON schema."""
        import jsonschema
        with open(RESULTS_JSON) as f:
            data = json.load(f)
        with open(SCHEMA_JSON) as f:
            schema = json.load(f)
        jsonschema.validate(instance=data, schema=schema)

    def test_matches_database(self):
        """results.json entries must correspond to database results."""
        with open(RESULTS_JSON) as f:
            json_data = json.load(f)

        db_rows = get_all_results()
        json_by_name = {entry['name']: entry for entry in json_data}
        db_by_name = {row['name']: row for row in db_rows}

        assert set(json_by_name.keys()) == set(db_by_name.keys()), (
            f"Name mismatch: JSON has {set(json_by_name.keys())}, "
            f"DB has {set(db_by_name.keys())}"
        )

        for name in json_by_name:
            j = json_by_name[name]
            d = db_by_name[name]
            assert math.isclose(
                j['compensated_value'], d['compensated_value'],
                rel_tol=1e-14, abs_tol=1e-300
            ), f"{name}: compensated_value mismatch"
            assert math.isclose(
                j['error_bound'], d['error_bound'],
                rel_tol=1e-14, abs_tol=1e-300
            ), f"{name}: error_bound mismatch"
            assert math.isclose(
                j['naive_value'], d['naive_value'],
                rel_tol=1e-14, abs_tol=1e-300
            ), f"{name}: naive_value mismatch"

    def test_error_bounds_valid_in_json(self):
        """Error bounds in results.json must also be valid against exact computation."""
        with open(RESULTS_JSON) as f:
            json_data = json.load(f)

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        polys = conn.execute("SELECT * FROM polynomials ORDER BY id").fetchall()
        conn.close()
        poly_by_name = {p['name']: p for p in polys}

        for entry in json_data:
            poly = poly_by_name[entry['name']]
            coeffs = json.loads(poly['coefficients'])
            x = poly['eval_point']

            true_exact = exact_poly_eval(coeffs, x)
            actual_err = abs(Fraction(entry['compensated_value']) - true_exact)
            bound_frac = Fraction(entry['error_bound'])

            assert actual_err <= bound_frac * Fraction(101, 100), (
                f"{entry['name']}: error {float(actual_err):.3e} "
                f"exceeds bound {entry['error_bound']:.3e} in results.json"
            )


class TestMakefile:
    """Verify Makefile exists with required targets."""

    def test_makefile_exists(self):
        """Makefile must exist at /app/Makefile."""
        assert os.path.exists(MAKEFILE_PATH), "Makefile not found at /app/Makefile"

    def test_has_all_target(self):
        """Makefile must define an 'all' target."""
        with open(MAKEFILE_PATH) as f:
            content = f.read()
        assert 'all' in content, "Makefile must have 'all' target"

    def test_has_evaluate_target(self):
        """Makefile must define an 'evaluate' target."""
        with open(MAKEFILE_PATH) as f:
            content = f.read()
        assert 'evaluate' in content, "Makefile must have 'evaluate' target"

    def test_has_export_target(self):
        """Makefile must define an 'export' target."""
        with open(MAKEFILE_PATH) as f:
            content = f.read()
        assert 'export' in content, "Makefile must have 'export' target"

    def test_export_uses_sqlite3_and_jq(self):
        """The export target must use sqlite3 and jq."""
        with open(MAKEFILE_PATH) as f:
            content = f.read()
        assert 'sqlite3' in content, "Export target must use sqlite3 CLI"
        assert 'jq' in content, "Export target must use jq"
