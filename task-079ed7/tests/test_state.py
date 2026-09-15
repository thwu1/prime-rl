
import subprocess
import json
import os
import re

INSTANCES_DIR = "/app/instances"
OUTPUTS_DIR = "/app/outputs"

# Known optimal costs for each instance (None means UNSAT)
EXPECTED = {
    "inst01.wcnf": 5,
    "inst02.wcnf": None,
    "inst03.wcnf": 0,
    "inst04.wcnf": 30,
    "inst05.wcnf": 2500000000,
    "inst06.wcnf": None,
    "inst07.wcnf": 41,
    "inst08.wcnf": 17,
    "inst09.wcnf": 41,
}


def parse_wcnf(filepath):
    """Parse a WCNF file (both formats) for verification."""
    hard_clauses = []
    soft_clauses = []
    max_var = 0
    top = None

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c"):
                continue
            if line.startswith("p"):
                tokens = line.split()
                if len(tokens) >= 4 and tokens[1] == "wcnf":
                    top = int(tokens[3])
                break
            else:
                break

    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("c") or line.startswith("p"):
                continue
            tokens = line.split()

            if top is not None:
                weight = int(tokens[0])
                lits = []
                for t in tokens[1:]:
                    val = int(t)
                    if val == 0:
                        break
                    lits.append(val)
                    max_var = max(max_var, abs(val))
                if weight >= top:
                    hard_clauses.append(lits)
                else:
                    soft_clauses.append((weight, lits))
            else:
                if tokens[0] == "h":
                    lits = []
                    for t in tokens[1:]:
                        val = int(t)
                        if val == 0:
                            break
                        lits.append(val)
                        max_var = max(max_var, abs(val))
                    hard_clauses.append(lits)
                else:
                    weight = int(tokens[0])
                    lits = []
                    for t in tokens[1:]:
                        val = int(t)
                        if val == 0:
                            break
                        lits.append(val)
                        max_var = max(max_var, abs(val))
                    soft_clauses.append((weight, lits))

    return max_var, hard_clauses, soft_clauses


def eval_clause(clause, assignment):
    if not clause:
        return False
    for lit in clause:
        var = abs(lit)
        val = assignment.get(var, 0)
        if (lit > 0 and val == 1) or (lit < 0 and val == 0):
            return True
    return False


def parse_solver_output(text):
    status = None
    cost = None
    v_values = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if line.startswith("s "):
            status = line[2:].strip()
        elif line.startswith("o "):
            cost = int(line[2:].strip())
        elif line.startswith("v "):
            v_values.extend(line[2:].strip().split())
    assignment = [int(x) for x in v_values] if v_values else None
    return status, cost, assignment


# ============================================================
# CONVERTER TESTS
# ============================================================

class TestConverter:

    def test_converter_exists(self):
        assert os.path.isfile("/app/tools/wcnf2dimacs_fixed.py"), \
            "wcnf2dimacs_fixed.py not found at /app/tools/"

    def test_new_format_produces_valid_dimacs(self):
        """Converter must produce valid DIMACS CNF from new-format WCNF."""
        result = subprocess.run(
            ["python3", "/app/tools/wcnf2dimacs_fixed.py",
             f"{INSTANCES_DIR}/inst01.wcnf"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"Converter failed: {result.stderr}"
        lines = result.stdout.strip().split("\n")
        # Check p-line header
        assert lines[0].startswith("p cnf"), \
            f"Missing DIMACS p-line header, got: {lines[0]}"
        # Check clauses end with 0
        for line in lines[1:]:
            assert line.strip().endswith("0"), \
                f"DIMACS clause not terminated by 0: {line}"
        # Check no literal 0 (besides terminator)
        for line in lines[1:]:
            lits = line.strip().split()
            for lit in lits[:-1]:  # Exclude trailing 0
                assert lit != "0", \
                    f"Literal 0 found in clause body: {line}"

    def test_old_format_detection(self):
        """Converter must correctly handle old p-line format."""
        result = subprocess.run(
            ["python3", "/app/tools/wcnf2dimacs_fixed.py",
             f"{INSTANCES_DIR}/inst09.wcnf"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"Converter failed on old format: {result.stderr}"
        lines = result.stdout.strip().split("\n")
        assert lines[0].startswith("p cnf"), \
            f"Missing DIMACS header for old format: {lines[0]}"
        # Old format inst09 has 10 vars, 25 clauses total
        header = lines[0].split()
        n_vars = int(header[2])
        n_clauses = int(header[3])
        assert n_vars == 10, f"Expected 10 vars, got {n_vars}"
        assert n_clauses == 25, f"Expected 25 clauses, got {n_clauses}"

    def test_hards_only_new_format(self):
        """With -hards, converter must extract only hard clauses from new format."""
        result = subprocess.run(
            ["python3", "/app/tools/wcnf2dimacs_fixed.py", "-hards",
             f"{INSTANCES_DIR}/inst01.wcnf"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        lines = result.stdout.strip().split("\n")
        header = lines[0].split()
        n_clauses = int(header[3])
        # inst01 has 2 hard clauses
        assert n_clauses == 2, \
            f"Expected 2 hard clauses from inst01, got {n_clauses}"

    def test_hards_only_old_format(self):
        """With -hards, converter must extract hard clauses from old format."""
        result = subprocess.run(
            ["python3", "/app/tools/wcnf2dimacs_fixed.py", "-hards",
             f"{INSTANCES_DIR}/inst09.wcnf"],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0
        lines = result.stdout.strip().split("\n")
        header = lines[0].split()
        n_clauses = int(header[3])
        # inst09 (Petersen graph old format) has 15 hard clauses
        assert n_clauses == 15, \
            f"Expected 15 hard clauses from inst09 (old format), got {n_clauses}"


# ============================================================
# SOLVER TESTS
# ============================================================

class TestSolver:

    def test_solver_exists(self):
        assert os.path.isfile("/app/maxsat_solver"), \
            "maxsat_solver not found at /app/maxsat_solver"

    def test_solver_executable(self):
        """The solver must be executable."""
        assert os.access("/app/maxsat_solver", os.X_OK), \
            "/app/maxsat_solver is not executable"

    def _run_solver(self, instance_name, timeout=120):
        result = subprocess.run(
            ["/app/maxsat_solver", f"{INSTANCES_DIR}/{instance_name}"],
            capture_output=True, text=True, timeout=timeout
        )
        return result

    def test_solver_inst01_optimal(self):
        """Solver must find optimal cost 5 for inst01."""
        result = self._run_solver("inst01.wcnf")
        status, cost, assignment = parse_solver_output(result.stdout)
        assert status == "OPTIMUM FOUND", f"Expected OPTIMUM FOUND, got: {status}"
        assert cost == 5, f"Expected cost 5, got: {cost}"
        assert result.returncode == 30, f"Expected exit 30, got: {result.returncode}"

    def test_solver_inst01_valid_assignment(self):
        """Solver assignment for inst01 must satisfy hard clauses."""
        result = self._run_solver("inst01.wcnf")
        _, cost, assignment = parse_solver_output(result.stdout)
        assert assignment is not None
        num_vars, hard_clauses, soft_clauses = parse_wcnf(f"{INSTANCES_DIR}/inst01.wcnf")
        assert len(assignment) == num_vars
        asgn = {i + 1: assignment[i] for i in range(len(assignment))}
        for c in hard_clauses:
            assert eval_clause(c, asgn), f"Hard clause {c} violated"
        actual = sum(w for w, c in soft_clauses if not eval_clause(c, asgn))
        assert actual == cost, f"Actual cost {actual} != claimed {cost}"

    def test_solver_inst02_unsat(self):
        result = self._run_solver("inst02.wcnf")
        status, _, _ = parse_solver_output(result.stdout)
        assert status == "UNSATISFIABLE", f"Expected UNSATISFIABLE, got: {status}"
        assert result.returncode == 20

    def test_solver_inst03_zero_cost(self):
        result = self._run_solver("inst03.wcnf")
        status, cost, _ = parse_solver_output(result.stdout)
        assert status == "OPTIMUM FOUND"
        assert cost == 0, f"Expected cost 0, got: {cost}"
        assert result.returncode == 30

    def test_solver_inst04_optimal(self):
        result = self._run_solver("inst04.wcnf")
        status, cost, _ = parse_solver_output(result.stdout)
        assert status == "OPTIMUM FOUND"
        assert cost == 30, f"Expected cost 30, got: {cost}"

    def test_solver_inst04_valid_assignment(self):
        result = self._run_solver("inst04.wcnf")
        _, cost, assignment = parse_solver_output(result.stdout)
        assert assignment is not None
        num_vars, hard_clauses, soft_clauses = parse_wcnf(f"{INSTANCES_DIR}/inst04.wcnf")
        assert len(assignment) == num_vars
        asgn = {i + 1: assignment[i] for i in range(len(assignment))}
        for c in hard_clauses:
            assert eval_clause(c, asgn), f"Hard clause {c} violated"
        actual = sum(w for w, c in soft_clauses if not eval_clause(c, asgn))
        assert actual == 30, f"Actual cost {actual} != 30"

    def test_solver_inst05_large_weights(self):
        result = self._run_solver("inst05.wcnf")
        status, cost, _ = parse_solver_output(result.stdout)
        assert status == "OPTIMUM FOUND"
        assert cost == 2500000000, f"Expected cost 2500000000, got: {cost}"

    def test_solver_inst05_valid_assignment(self):
        result = self._run_solver("inst05.wcnf")
        _, cost, assignment = parse_solver_output(result.stdout)
        assert assignment is not None
        num_vars, hard_clauses, soft_clauses = parse_wcnf(f"{INSTANCES_DIR}/inst05.wcnf")
        assert len(assignment) == num_vars
        asgn = {i + 1: assignment[i] for i in range(len(assignment))}
        for c in hard_clauses:
            assert eval_clause(c, asgn)
        actual = sum(w for w, c in soft_clauses if not eval_clause(c, asgn))
        assert actual == cost

    def test_solver_inst06_empty_hard(self):
        result = self._run_solver("inst06.wcnf")
        status, _, _ = parse_solver_output(result.stdout)
        assert status == "UNSATISFIABLE"
        assert result.returncode == 20

    def test_solver_inst07_petersen(self):
        result = self._run_solver("inst07.wcnf")
        status, cost, _ = parse_solver_output(result.stdout)
        assert status == "OPTIMUM FOUND"
        assert cost == 41, f"Expected cost 41, got: {cost}"

    def test_solver_inst07_valid_assignment(self):
        result = self._run_solver("inst07.wcnf")
        _, cost, assignment = parse_solver_output(result.stdout)
        assert assignment is not None
        num_vars, hard_clauses, soft_clauses = parse_wcnf(f"{INSTANCES_DIR}/inst07.wcnf")
        assert len(assignment) == num_vars
        asgn = {i + 1: assignment[i] for i in range(len(assignment))}
        for c in hard_clauses:
            assert eval_clause(c, asgn)
        actual = sum(w for w, c in soft_clauses if not eval_clause(c, asgn))
        assert actual == 41

    def test_solver_inst08_grid_optimal(self):
        """Solver must find optimal cost 17 for 5x7 grid vertex cover (35 vars).
        This instance has 35 variables — brute force (2^35 ~ 34 billion) is
        infeasible within the timeout, so the solver must use minisat.
        """
        result = self._run_solver("inst08.wcnf", timeout=120)
        status, cost, _ = parse_solver_output(result.stdout)
        assert status == "OPTIMUM FOUND", f"Expected OPTIMUM FOUND, got: {status}"
        assert cost == 17, f"Expected cost 17, got: {cost}"
        assert result.returncode == 30

    def test_solver_inst08_valid_assignment(self):
        """Solver assignment for the grid instance must be a valid vertex cover."""
        result = self._run_solver("inst08.wcnf", timeout=120)
        _, cost, assignment = parse_solver_output(result.stdout)
        assert assignment is not None, "No assignment returned"
        num_vars, hard_clauses, soft_clauses = parse_wcnf(f"{INSTANCES_DIR}/inst08.wcnf")
        assert len(assignment) == num_vars, \
            f"Assignment length {len(assignment)} != {num_vars}"
        asgn = {i + 1: assignment[i] for i in range(len(assignment))}
        for i, c in enumerate(hard_clauses):
            assert eval_clause(c, asgn), \
                f"Hard clause {i} {c} violated in grid VC"
        actual = sum(w for w, c in soft_clauses if not eval_clause(c, asgn))
        assert actual == 17, f"Actual cost {actual} != 17"

    def test_solver_inst09_old_format(self):
        """Solver must handle old p-line format and find optimal cost 41."""
        result = self._run_solver("inst09.wcnf")
        status, cost, _ = parse_solver_output(result.stdout)
        assert status == "OPTIMUM FOUND", \
            f"Expected OPTIMUM FOUND for old-format instance, got: {status}"
        assert cost == 41, f"Expected cost 41 for old-format Petersen, got: {cost}"

    def test_solver_inst09_valid_assignment(self):
        """Solver assignment for old-format instance must be valid."""
        result = self._run_solver("inst09.wcnf")
        _, cost, assignment = parse_solver_output(result.stdout)
        assert assignment is not None
        num_vars, hard_clauses, soft_clauses = parse_wcnf(f"{INSTANCES_DIR}/inst09.wcnf")
        assert len(assignment) == num_vars
        asgn = {i + 1: assignment[i] for i in range(len(assignment))}
        for c in hard_clauses:
            assert eval_clause(c, asgn), f"Hard clause {c} violated"
        actual = sum(w for w, c in soft_clauses if not eval_clause(c, asgn))
        assert actual == 41, f"Actual cost {actual} != 41"

    def test_solver_mse_format(self):
        """Solver output must contain s, o, and v lines in MSE format."""
        result = self._run_solver("inst01.wcnf")
        stdout = result.stdout
        has_s = any(l.strip().startswith("s ") for l in stdout.split("\n"))
        has_o = any(l.strip().startswith("o ") for l in stdout.split("\n"))
        has_v = any(l.strip().startswith("v ") for l in stdout.split("\n"))
        assert has_s, "Missing 's' status line"
        assert has_o, "Missing 'o' cost line"
        assert has_v, "Missing 'v' assignment line"


# ============================================================
# BUG REPORT TESTS
# ============================================================

class TestBugReport:

    def test_bug_report_exists(self):
        assert os.path.isfile("/app/bug_report.json"), \
            "bug_report.json not found"

    def test_bug_report_structure(self):
        with open("/app/bug_report.json") as f:
            report = json.load(f)
        expected_files = [
            "out01_correct.txt",
            "out01_bug_cost.txt",
            "out01_bug_hard.txt",
            "out03_bug_unsat.txt",
            "out04_bug_cost.txt",
            "out09_bug_format.txt",
        ]
        for fname in expected_files:
            assert fname in report, f"Missing entry for {fname}"
            entry = report[fname]
            assert "valid" in entry, f"Missing 'valid' for {fname}"
            assert "bugs" in entry, f"Missing 'bugs' for {fname}"
            assert isinstance(entry["valid"], bool)
            assert isinstance(entry["bugs"], list)

    def test_correct_output_classified(self):
        with open("/app/bug_report.json") as f:
            report = json.load(f)
        entry = report["out01_correct.txt"]
        assert entry["valid"] is True
        assert len(entry["bugs"]) == 0

    def test_cost_mismatch_detected(self):
        with open("/app/bug_report.json") as f:
            report = json.load(f)
        entry = report["out01_bug_cost.txt"]
        assert entry["valid"] is False
        assert any("cost" in b.lower() or "mismatch" in b.lower()
                    for b in entry["bugs"])

    def test_hard_violation_detected(self):
        with open("/app/bug_report.json") as f:
            report = json.load(f)
        entry = report["out01_bug_hard.txt"]
        assert entry["valid"] is False
        assert any("hard" in b.lower() or "violation" in b.lower()
                    for b in entry["bugs"])

    def test_false_unsat_detected(self):
        with open("/app/bug_report.json") as f:
            report = json.load(f)
        entry = report["out03_bug_unsat.txt"]
        assert entry["valid"] is False
        assert any("unsat" in b.lower() or "false" in b.lower()
                    for b in entry["bugs"])

    def test_cost_mismatch_inst04(self):
        with open("/app/bug_report.json") as f:
            report = json.load(f)
        entry = report["out04_bug_cost.txt"]
        assert entry["valid"] is False
        assert any("cost" in b.lower() or "mismatch" in b.lower()
                    for b in entry["bugs"])

    def test_old_format_bug_detected(self):
        """Bug report must detect hard clause violation in old-format output."""
        with open("/app/bug_report.json") as f:
            report = json.load(f)
        entry = report["out09_bug_format.txt"]
        assert entry["valid"] is False, \
            "out09_bug_format.txt should be invalid (hard clause violation)"
        assert any("hard" in b.lower() or "violation" in b.lower()
                    for b in entry["bugs"]), \
            f"Expected hard_clause_violation for old-format bug, got: {entry['bugs']}"
