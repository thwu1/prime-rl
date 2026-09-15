
import json
import os
import glob
import re
import base64
import pytest


def _load_ref():
    """Load verification data (encoded to prevent trivial extraction)."""
    _ENC = (
        "fTYxMzY5LjQ5NDUyMjoiZWx0dGlsZGEiLDQ3MDQy"
        "MjM3LjUxNC06ImIyZXJhaHMiLDk5MjEwMDkuOTQ3"
        "MS06IjJiayIsMC4wNy06ImIwNWNzIiw2ODI0MTM1"
        "Ny40NjQtOiJvcmlmYSJ7"
    )
    return json.loads(base64.b64decode(_ENC).decode()[::-1])


REFERENCE = _load_ref()
REL_TOL = 1e-4  # 0.01% relative tolerance
PROBLEM_NAMES = ["afiro", "sc50b", "kb2", "share2b", "adlittle"]


class TestDecompression:
    """Verify agent compiled emps and decompressed MPS files."""

    def test_problems_directory_exists(self):
        assert os.path.isdir("/app/problems"), (
            "/app/problems/ directory not found — did you decompress the benchmark files?"
        )

    @pytest.mark.parametrize("name", PROBLEM_NAMES)
    def test_mps_file_exists(self, name):
        path = f"/app/problems/{name}.mps"
        assert os.path.exists(path), (
            f"{path} not found — compile emps.c and use it to decompress /app/compressed/{name}"
        )

    @pytest.mark.parametrize("name", PROBLEM_NAMES)
    def test_mps_file_has_content(self, name):
        path = f"/app/problems/{name}.mps"
        if not os.path.exists(path):
            pytest.skip(f"{path} missing")
        size = os.path.getsize(path)
        assert size > 200, (
            f"{path} is only {size} bytes — likely not a valid decompressed MPS file"
        )

    @pytest.mark.parametrize("name", PROBLEM_NAMES)
    def test_mps_file_has_rows_section(self, name):
        path = f"/app/problems/{name}.mps"
        if not os.path.exists(path):
            pytest.skip(f"{path} missing")
        with open(path) as f:
            content = f.read()
        assert "ROWS" in content and "COLUMNS" in content, (
            f"{path} does not contain ROWS/COLUMNS sections — not valid MPS format"
        )


class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), (
            "results.json not found at /app/results.json"
        )

    def test_all_problems_present(self):
        with open("/app/results.json") as f:
            results = json.load(f)
        for name in PROBLEM_NAMES:
            assert name in results, f"Problem '{name}' missing from results.json"
            assert results[name] is not None, (
                f"Problem '{name}' has null result (solver likely failed)"
            )


class TestOptimalValues:
    """Each problem gets its own test for clear reporting."""

    def _check(self, name):
        with open("/app/results.json") as f:
            results = json.load(f)
        assert name in results and results[name] is not None, (
            f"Problem '{name}' not solved"
        )
        val = float(results[name])
        ref = REFERENCE[name]
        rel_err = abs(val - ref) / max(abs(ref), 1e-10)
        assert rel_err < REL_TOL, (
            f"{name}: computed={val:.10e}, relative_error={rel_err:.2e} "
            f"(exceeds tolerance {REL_TOL})"
        )

    def test_afiro(self):
        self._check("afiro")

    def test_sc50b(self):
        self._check("sc50b")

    def test_kb2(self):
        self._check("kb2")

    def test_share2b(self):
        self._check("share2b")

    def test_adlittle(self):
        self._check("adlittle")


class TestSolverCodeIntegrity:
    """Verify agent wrote genuine solver code, not a trivial bypass."""

    def test_solver_code_exists(self):
        py_files = glob.glob("/app/**/*.py", recursive=True)
        assert len(py_files) >= 1, (
            "No Python files found in /app/ — solver must be implemented in Python"
        )

    def test_solver_code_has_minimum_complexity(self):
        total_lines = 0
        for pyfile in glob.glob("/app/**/*.py", recursive=True):
            with open(pyfile) as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        total_lines += 1
        assert total_lines >= 100, (
            f"Only {total_lines} non-blank non-comment lines of Python in /app/. "
            f"A genuine LP solver requires substantially more code."
        )

    def test_solver_code_has_matrix_operations(self):
        all_code = ""
        for pyfile in glob.glob("/app/**/*.py", recursive=True):
            with open(pyfile) as f:
                all_code += f.read()
        has_linalg = ("linalg" in all_code or "solve" in all_code or
                      "inv(" in all_code or "dot(" in all_code or
                      "matmul" in all_code or "np." in all_code)
        assert has_linalg, (
            "Solver code does not appear to contain matrix/linear algebra operations. "
            "A simplex implementation requires solving linear systems."
        )

    def test_solver_code_has_mps_parsing(self):
        all_code = ""
        for pyfile in glob.glob("/app/**/*.py", recursive=True):
            with open(pyfile) as f:
                all_code += f.read()
        has_mps = ("ROWS" in all_code or "COLUMNS" in all_code or
                   "mps" in all_code.lower())
        assert has_mps, (
            "Solver code does not appear to parse MPS format. "
            "The solver must read and parse .mps files."
        )


class TestNoBannedSolvers:
    """Ensure the agent implemented a solver from scratch."""

    BANNED = [
        r"from\s+scipy\.optimize\s+import",
        r"import\s+scipy\.optimize",
        r"from\s+pulp\b",
        r"import\s+pulp\b",
        r"from\s+cvxpy\b",
        r"import\s+cvxpy\b",
        r"from\s+gurobipy\b",
        r"import\s+gurobipy\b",
        r"from\s+cplex\b",
        r"import\s+cplex\b",
        r"from\s+ortools\b",
        r"import\s+ortools\b",
        r"from\s+highspy\b",
        r"import\s+highspy\b",
        r"from\s+cylp\b",
        r"import\s+cylp\b",
        r"from\s+pyomo\b",
        r"import\s+pyomo\b",
        r"from\s+docplex\b",
        r"import\s+docplex\b",
        r"from\s+mip\s+import",
        r"import\s+mip\b",
        r"linprog\s*\(",
    ]

    def test_no_banned_imports(self):
        violations = []
        for pyfile in glob.glob("/app/**/*.py", recursive=True):
            with open(pyfile) as f:
                lines = f.readlines()
            for line_no, line in enumerate(lines, 1):
                code = line.split("#")[0]
                code = re.sub(r'"[^"]*"', '""', code)
                code = re.sub(r"'[^']*'", "''", code)
                for pat in self.BANNED:
                    m = re.search(pat, code)
                    if m:
                        violations.append(
                            f"{pyfile}:{line_no}: {m.group()}"
                        )
        assert not violations, (
            "Banned LP solver library usage detected:\n"
            + "\n".join(violations)
        )
