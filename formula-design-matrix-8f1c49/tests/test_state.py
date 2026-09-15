
import pytest
import numpy as np
import sys
import subprocess
import csv
import io
import json
import os

sys.path.insert(0, "/app")
from design_matrix import dmatrix


class TestBasicNumeric:
    def test_single_numeric(self):
        cols, mat = dmatrix("x", {"x": [1.0, 2.0, 3.0]})
        assert cols == ["Intercept", "x"]
        assert np.allclose(mat, [[1, 1], [1, 2], [1, 3]])

    def test_two_numeric(self):
        cols, mat = dmatrix("x + y", {"x": [1.0, 2.0], "y": [3.0, 4.0]})
        assert cols == ["Intercept", "x", "y"]
        assert np.allclose(mat, [[1, 1, 3], [1, 2, 4]])

    def test_numeric_no_intercept(self):
        cols, mat = dmatrix("0 + x", {"x": [1.0, 2.0, 3.0]})
        assert cols == ["x"]
        assert np.allclose(mat, [[1], [2], [3]])


class TestCategorical:
    def test_treatment_with_intercept(self):
        data = {"a": ["a1", "a2", "a3", "a1", "a2", "a3"]}
        cols, mat = dmatrix("a", data)
        assert cols == ["Intercept", "a[T.a2]", "a[T.a3]"]
        expected = [[1, 0, 0], [1, 1, 0], [1, 0, 1], [1, 0, 0], [1, 1, 0], [1, 0, 1]]
        assert np.allclose(mat, expected)

    def test_treatment_no_intercept(self):
        data = {"a": ["a1", "a2", "a3", "a1", "a2", "a3"]}
        cols, mat = dmatrix("0 + a", data)
        assert cols == ["a[a1]", "a[a2]", "a[a3]"]
        expected = [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 0], [0, 1, 0], [0, 0, 1]]
        assert np.allclose(mat, expected)


class TestInteractions:
    def test_star_operator(self):
        data = {
            "a": ["a1", "a1", "a2", "a2"],
            "b": ["b1", "b2", "b1", "b2"],
        }
        cols, mat = dmatrix("a * b", data)
        assert cols == [
            "Intercept",
            "a[T.a2]",
            "b[T.b2]",
            "a[T.a2]:b[T.b2]",
        ]
        expected = [
            [1, 0, 0, 0],
            [1, 0, 1, 0],
            [1, 1, 0, 0],
            [1, 1, 1, 1],
        ]
        assert np.allclose(mat, expected)

    def test_cat_num_interaction(self):
        data = {"a": ["a1", "a1", "a2", "a2"], "x": [1.0, 2.0, 3.0, 4.0]}
        cols, mat = dmatrix("a:x", data)
        assert cols == ["Intercept", "a[a1]:x", "a[a2]:x"]
        expected = [[1, 1, 0], [1, 2, 0], [1, 0, 3], [1, 0, 4]]
        assert np.allclose(mat, expected)

    def test_num_num_interaction(self):
        data = {"x1": [1.0, 2.0, 3.0], "x2": [4.0, 5.0, 6.0]}
        cols, mat = dmatrix("x1:x2", data)
        assert cols == ["Intercept", "x1:x2"]
        assert np.allclose(mat, [[1, 4], [1, 10], [1, 18]])


class TestRedundancy:
    def test_intercept_plus_interaction_colnames(self):
        """R bug #1: 1 + a:b should produce 4 columns, not 5."""
        data = {
            "a": ["a1", "a1", "a2", "a2"],
            "b": ["b1", "b2", "b1", "b2"],
        }
        cols, mat = dmatrix("1 + a:b", data)
        assert len(cols) == 4
        assert cols[0] == "Intercept"
        mat_np = np.array(mat, dtype=float)
        assert np.linalg.matrix_rank(mat_np) == 4
        expected = [[1, 0, 0, 0], [1, 1, 0, 0], [1, 0, 1, 0], [1, 1, 0, 1]]
        assert np.allclose(mat, expected)

    def test_numeric_interaction_rank(self):
        """R bug #2: 0 + a:x + a:b with numeric x should give 6 columns, not 4."""
        data = {
            "a": ["a1", "a1", "a2", "a2"],
            "b": ["b1", "b2", "b1", "b2"],
            "x": [1.0, 2.0, 3.0, 4.0],
        }
        cols, mat = dmatrix("0 + a:x + a:b", data)
        assert len(cols) == 6
        mat_np = np.array(mat, dtype=float)
        assert np.linalg.matrix_rank(mat_np) == 4

    def test_full_rank_no_intercept(self):
        """0 + a:b should give full-rank (dummy) coding for both factors."""
        data = {
            "a": ["a1", "a1", "a2", "a2"],
            "b": ["b1", "b2", "b1", "b2"],
        }
        cols, mat = dmatrix("0 + a:b", data)
        assert len(cols) == 4
        expected = [[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]]
        assert np.allclose(mat, expected)


class TestContrastCoding:
    def test_sum(self):
        data = {"a": ["a1", "a2", "a3", "a1", "a2", "a3"]}
        cols, mat = dmatrix("C(a, Sum)", data)
        assert cols == ["Intercept", "C(a, Sum)[S.a1]", "C(a, Sum)[S.a2]"]
        expected = [
            [1, 1, 0],
            [1, 0, 1],
            [1, -1, -1],
            [1, 1, 0],
            [1, 0, 1],
            [1, -1, -1],
        ]
        assert np.allclose(mat, expected)

    def test_poly(self):
        data = {"a": ["a1", "a2", "a3", "a1", "a2", "a3"]}
        cols, mat = dmatrix("C(a, Poly)", data)
        assert cols == [
            "Intercept",
            "C(a, Poly).Linear",
            "C(a, Poly).Quadratic",
        ]
        expected_contrast = [
            [-7.07106781186548e-01, 0.408248290463863],
            [0.0, -0.816496580927726],
            [7.07106781186547e-01, 0.408248290463863],
        ]
        for i in range(6):
            assert np.isclose(mat[i][0], 1.0), f"Row {i} intercept"
            level_idx = i % 3
            assert np.allclose(
                mat[i][1:], expected_contrast[level_idx], atol=1e-4
            ), f"Row {i} contrast"

    def test_helmert(self):
        data = {"a": ["a1", "a2", "a3", "a4"]}
        cols, mat = dmatrix("C(a, Helmert)", data)
        assert cols == [
            "Intercept",
            "C(a, Helmert)[H.a2]",
            "C(a, Helmert)[H.a3]",
            "C(a, Helmert)[H.a4]",
        ]
        expected = [
            [1, -1, -1, -1],
            [1, 1, -1, -1],
            [1, 0, 2, -1],
            [1, 0, 0, 3],
        ]
        assert np.allclose(mat, expected)

    def test_diff(self):
        data = {"a": ["a1", "a2", "a3", "a4"]}
        cols, mat = dmatrix("C(a, Diff)", data)
        assert cols == [
            "Intercept",
            "C(a, Diff)[D.a1]",
            "C(a, Diff)[D.a2]",
            "C(a, Diff)[D.a3]",
        ]
        expected = [
            [1, -3 / 4, -1 / 2, -1 / 4],
            [1, 1 / 4, -1 / 2, -1 / 4],
            [1, 1 / 4, 1 / 2, -1 / 4],
            [1, 1 / 4, 1 / 2, 3 / 4],
        ]
        assert np.allclose(mat, expected)


class TestStatefulTransforms:
    def test_center(self):
        cols, mat = dmatrix("center(x)", {"x": [1.0, 2.0, 3.0]})
        assert cols == ["Intercept", "center(x)"]
        assert np.allclose(mat, [[1, -1], [1, 0], [1, 1]])

    def test_standardize(self):
        cols, mat = dmatrix("standardize(x)", {"x": [12.0, 10.0]})
        assert cols == ["Intercept", "standardize(x)"]
        assert np.allclose(mat, [[1, 1], [1, -1]])

    def test_standardize_three(self):
        cols, mat = dmatrix("standardize(x)", {"x": [12.0, 11.0, 10.0]})
        assert cols == ["Intercept", "standardize(x)"]
        expected_std = np.sqrt(3.0 / 2)
        assert np.allclose(
            mat,
            [[1, expected_std], [1, 0], [1, -expected_std]],
        )


class TestFormulaOperators:
    def test_power_equals_star(self):
        data = {
            "a": ["a1", "a1", "a2", "a2"],
            "b": ["b1", "b2", "b1", "b2"],
        }
        cols1, mat1 = dmatrix("(a + b) ** 2", data)
        cols2, mat2 = dmatrix("a * b", data)
        assert cols1 == cols2
        assert np.allclose(mat1, mat2)

    def test_minus_removes_term(self):
        data = {
            "a": ["a1", "a1", "a2", "a2"],
            "b": ["b1", "b2", "b1", "b2"],
        }
        cols, mat = dmatrix("a * b - a:b", data)
        assert cols == ["Intercept", "a[T.a2]", "b[T.b2]"]

    def test_slash_operator(self):
        data = {
            "a": ["a1", "a1", "a2", "a2"],
            "b": ["b1", "b2", "b1", "b2"],
        }
        cols1, mat1 = dmatrix("a / b", data)
        cols2, mat2 = dmatrix("a + a:b", data)
        assert cols1 == cols2
        assert np.allclose(mat1, mat2)

    def test_intercept_removal_with_parens(self):
        """(a - 1) should RETAIN intercept; a - 1 should remove it."""
        data = {"a": ["a1", "a2", "a3"]}
        cols_no, _ = dmatrix("a - 1", data)
        assert "Intercept" not in cols_no

        cols_yes, _ = dmatrix("(a - 1)", data)
        assert "Intercept" in cols_yes


class TestTermOrdering:
    def test_numeric_groups_ordered(self):
        data = {
            "a": ["a1", "a1", "a2", "a2"],
            "b": ["b1", "b2", "b1", "b2"],
            "x1": [1.0, 2.0, 3.0, 4.0],
            "x2": [5.0, 6.0, 7.0, 8.0],
        }
        cols, mat = dmatrix("x1:x2 + a:b + b + a", data)
        assert cols == [
            "Intercept",
            "b[T.b2]",
            "a[T.a2]",
            "a[T.a2]:b[T.b2]",
            "x1:x2",
        ]
        assert np.allclose(mat[0], [1, 0, 0, 0, 5.0])
        assert np.allclose(mat[3], [1, 1, 1, 1, 32.0])


class TestCLIIntegration:
    def test_cli_csv_output(self):
        """CLI wrapper must produce valid CSV with correct headers."""
        input_csv = "x\n1.0\n2.0\n3.0\n"
        result = subprocess.run(
            ["python3", "/app/cli.py", "x"],
            input=input_csv,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        reader = csv.reader(io.StringIO(result.stdout))
        rows = list(reader)
        assert rows[0] == ["Intercept", "x"]
        assert len(rows) == 4  # header + 3 data rows

    def test_cli_json_output(self):
        """CLI --json flag must produce valid JSON with columns and matrix."""
        input_csv = "x\n1.0\n2.0\n3.0\n"
        result = subprocess.run(
            ["python3", "/app/cli.py", "x", "--json"],
            input=input_csv,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"CLI failed: {result.stderr}"
        output = json.loads(result.stdout)
        assert output["columns"] == ["Intercept", "x"]
        assert len(output["matrix"]) == 3


class TestValidation:
    def test_validate_passes(self):
        """The validate.py tool must pass all reference golden outputs."""
        result = subprocess.run(
            ["python3", "/app/validate.py"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Validation failed:\n{result.stdout}\n{result.stderr}"
        )


class TestPipeline:
    """Tests for the multi-tool sqlite3/jq/CLI validation pipeline."""

    @classmethod
    def setup_class(cls):
        """Run the pipeline once for all pipeline tests."""
        result = subprocess.run(
            ["bash", "/app/pipeline.sh"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        cls._stdout = result.stdout
        cls._stderr = result.stderr
        cls._exit_code = result.returncode

    def test_pipeline_exits_zero(self):
        """pipeline.sh must complete successfully."""
        assert self._exit_code == 0, (
            f"Pipeline failed (exit {self._exit_code}):\n"
            f"{self._stdout}\n{self._stderr}"
        )

    def test_results_db_has_correct_schema(self):
        """Pipeline must create results.db with all required tables."""
        import sqlite3 as sq3

        assert os.path.exists("/app/results.db"), "results.db not created"
        conn = sq3.connect("/app/results.db")
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t[0] for t in tables]
        conn.close()
        for required in [
            "test_suites",
            "test_cases",
            "expected_outputs",
            "pipeline_results",
        ]:
            assert required in table_names, f"Table {required} missing"

    def test_all_cases_have_results(self):
        """Every test case must have a corresponding pipeline result."""
        import sqlite3 as sq3

        conn = sq3.connect("/app/results.db")
        total = conn.execute("SELECT COUNT(*) FROM test_cases").fetchone()[0]
        results = conn.execute(
            "SELECT COUNT(*) FROM pipeline_results"
        ).fetchone()[0]
        conn.close()
        assert total > 0, "No test cases in database"
        assert results == total, (
            f"Only {results}/{total} test cases have pipeline results"
        )

    def test_all_pipeline_results_pass(self):
        """All pipeline results must have status 'pass'."""
        import sqlite3 as sq3

        conn = sq3.connect("/app/results.db")
        failures = conn.execute(
            "SELECT tc.name, pr.status, pr.error_message "
            "FROM pipeline_results pr "
            "JOIN test_cases tc ON pr.test_case_id = tc.id "
            "WHERE pr.status != 'pass'"
        ).fetchall()
        conn.close()
        assert len(failures) == 0, f"Pipeline failures: {failures}"

    def test_pipeline_results_have_data(self):
        """Passing pipeline results must store columns and matrix JSON."""
        import sqlite3 as sq3

        conn = sq3.connect("/app/results.db")
        empty = conn.execute(
            "SELECT COUNT(*) FROM pipeline_results "
            "WHERE status = 'pass' AND (columns_json IS NULL OR matrix_json IS NULL)"
        ).fetchone()[0]
        conn.close()
        assert empty == 0, "Some passing results have NULL columns/matrix"

    def test_make_report_works(self):
        """make report must produce output from results.db."""
        result = subprocess.run(
            ["make", "report"],
            capture_output=True,
            text=True,
            cwd="/app",
        )
        assert result.returncode == 0, f"make report failed: {result.stderr}"
        assert "pass" in result.stdout.lower(), (
            "Report output should contain pass status"
        )
