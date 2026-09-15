
import json
import os
import pytest

RESULT_DIR = "/app/results"
QC_DIR = "/app/data/qc_instances"
EDP_DIR = "/app/data/edp_instances"
VALIDATION_FILE = "/app/data/validation.json"
CONFIG_FILE = "/app/experiments/config.json"


@pytest.fixture(scope="session")
def validation():
    with open(VALIDATION_FILE) as f:
        return json.load(f)


@pytest.fixture(scope="session")
def config():
    with open(CONFIG_FILE) as f:
        return json.load(f)


def load_result(inst_id):
    path = os.path.join(RESULT_DIR, f"{inst_id}_result.json")
    with open(path) as f:
        return json.load(f)


def validate_queens(n, solution):
    """Validate standard n-queens properties: one per row, column, no diag conflict."""
    assert len(solution) == n, f"Expected {n} queens, got {len(solution)}"
    queens = [(int(r), int(c)) for r, c in solution]
    for r, c in queens:
        assert 0 <= r < n and 0 <= c < n, f"({r},{c}) out of bounds for n={n}"
    rows = sorted(r for r, c in queens)
    assert rows == list(range(n)), f"Rows not fully covered: {rows}"
    cols = sorted(c for r, c in queens)
    assert cols == list(range(n)), f"Columns not fully covered: {cols}"
    for i in range(n):
        for j in range(i + 1, n):
            r1, c1 = queens[i]
            r2, c2 = queens[j]
            assert abs(r1 - r2) != abs(c1 - c2), (
                f"Diagonal conflict between ({r1},{c1}) and ({r2},{c2})"
            )


# ---- n-Queens Completion Tests ----

QC_IDS = ["qc_01", "qc_02", "qc_03", "qc_04", "qc_05", "qc_06"]


class TestQCResultsExist:
    @pytest.mark.parametrize("inst_id", QC_IDS)
    def test_result_file_exists(self, inst_id):
        path = os.path.join(RESULT_DIR, f"{inst_id}_result.json")
        assert os.path.isfile(path), f"Result file {path} not found"

    @pytest.mark.parametrize("inst_id", QC_IDS)
    def test_result_has_required_fields(self, inst_id):
        result = load_result(inst_id)
        assert "id" in result, "Missing 'id' field"
        assert "satisfiable" in result, "Missing 'satisfiable' field"
        assert "solution" in result, "Missing 'solution' field"


class TestQCSatisfiability:
    @pytest.mark.parametrize("inst_id", QC_IDS)
    def test_matches_validation(self, inst_id, validation):
        result = load_result(inst_id)
        expected = validation[inst_id]["satisfiable"]
        assert result["satisfiable"] == expected, (
            f"{inst_id}: expected {'SAT' if expected else 'UNSAT'}, "
            f"got {'SAT' if result['satisfiable'] else 'UNSAT'}"
        )


class TestQCSolutionValidity:
    @pytest.mark.parametrize("inst_id", QC_IDS)
    def test_sat_solution_valid(self, inst_id, validation):
        if not validation[inst_id]["satisfiable"]:
            pytest.skip("UNSAT instance — no solution to validate")
        result = load_result(inst_id)
        assert result["solution"] is not None, "SAT result must include solution"
        with open(os.path.join(QC_DIR, f"{inst_id}.json")) as f:
            inst = json.load(f)
        validate_queens(inst["n"], result["solution"])
        # Pre-placed queens must be included
        pre_set = {(int(r), int(c)) for r, c in inst["pre_placed"]}
        sol_set = {(int(r), int(c)) for r, c in result["solution"]}
        missing = pre_set - sol_set
        assert not missing, f"Pre-placed queens missing from solution: {missing}"


# ---- Excluded Diagonals Problem Tests ----

EDP_IDS = ["edp_01", "edp_02", "edp_03", "edp_04", "edp_05"]


def parse_edp_file(inst_id):
    """Parse .edp file to extract n and excluded diagonals."""
    filepath = os.path.join(EDP_DIR, f"{inst_id}.edp")
    n = None
    fwd = []
    bwd = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("%"):
                continue
            if line.startswith("n="):
                n = int(line.split("=")[1].strip())
            elif line.startswith("D+"):
                content = line.split("=", 1)[1].strip().strip("{}")
                if content:
                    fwd = [int(x.strip()) for x in content.split(",")]
            elif line.startswith("D-"):
                content = line.split("=", 1)[1].strip().strip("{}")
                if content:
                    bwd = [int(x.strip()) for x in content.split(",")]
    return n, fwd, bwd


class TestEDPResultsExist:
    @pytest.mark.parametrize("inst_id", EDP_IDS)
    def test_result_file_exists(self, inst_id):
        path = os.path.join(RESULT_DIR, f"{inst_id}_result.json")
        assert os.path.isfile(path), f"Result file {path} not found"


class TestEDPSatisfiability:
    @pytest.mark.parametrize("inst_id", EDP_IDS)
    def test_matches_validation(self, inst_id, validation):
        result = load_result(inst_id)
        expected = validation[inst_id]["satisfiable"]
        assert result["satisfiable"] == expected, (
            f"{inst_id}: expected {'SAT' if expected else 'UNSAT'}, "
            f"got {'SAT' if result['satisfiable'] else 'UNSAT'}"
        )


class TestEDPSolutionValidity:
    @pytest.mark.parametrize("inst_id", EDP_IDS)
    def test_sat_solution_valid(self, inst_id, validation):
        if not validation[inst_id]["satisfiable"]:
            pytest.skip("UNSAT instance — no solution to validate")
        result = load_result(inst_id)
        assert result["solution"] is not None, "SAT result must include solution"
        n, excl_fwd, excl_bwd = parse_edp_file(inst_id)
        validate_queens(n, result["solution"])
        # Check excluded diagonal violations
        for pos in result["solution"]:
            r, c = int(pos[0]), int(pos[1])
            assert (r - c) not in excl_fwd, (
                f"Queen ({r},{c}) on excluded forward diagonal {r - c}"
            )
            assert (r + c) not in excl_bwd, (
                f"Queen ({r},{c}) on excluded backward diagonal {r + c}"
            )


# ---- Phase Transition Tests ----

class TestPhaseTransition:
    def test_file_exists(self):
        path = os.path.join(RESULT_DIR, "phase_transition.json")
        assert os.path.isfile(path), "phase_transition.json not found"

    def test_board_size_matches_config(self, config):
        with open(os.path.join(RESULT_DIR, "phase_transition.json")) as f:
            pt = json.load(f)
        expected = config["phase_transition"]["board_size"]
        assert pt["board_size"] == expected, (
            f"board_size {pt['board_size']} != config value {expected}"
        )

    def test_required_fields(self):
        with open(os.path.join(RESULT_DIR, "phase_transition.json")) as f:
            pt = json.load(f)
        assert "results" in pt, "Missing 'results' field"
        assert "critical_m" in pt, "Missing 'critical_m' field"
        assert isinstance(pt["results"], list), "'results' must be a list"

    def test_sufficient_m_values(self):
        with open(os.path.join(RESULT_DIR, "phase_transition.json")) as f:
            pt = json.load(f)
        assert len(pt["results"]) >= 10, (
            f"Need at least 10 m values tested, got {len(pt['results'])}"
        )

    def test_sufficient_samples(self):
        with open(os.path.join(RESULT_DIR, "phase_transition.json")) as f:
            pt = json.load(f)
        for entry in pt["results"]:
            assert "m" in entry, "Each result entry must have 'm'"
            assert "total" in entry, "Each result entry must have 'total'"
            assert "sat_count" in entry, "Each result entry must have 'sat_count'"
            assert "sat_ratio" in entry, "Each result entry must have 'sat_ratio'"
            assert entry["total"] >= 30, (
                f"Need >= 30 instances for m={entry['m']}, got {entry['total']}"
            )
            assert 0.0 <= entry["sat_ratio"] <= 1.0

    def test_decreasing_trend(self):
        """SAT ratio should generally decrease as m increases."""
        with open(os.path.join(RESULT_DIR, "phase_transition.json")) as f:
            pt = json.load(f)
        results = sorted(pt["results"], key=lambda x: x["m"])
        if len(results) >= 6:
            early = results[:3]
            late = results[-3:]
            early_avg = sum(r["sat_ratio"] for r in early) / len(early)
            late_avg = sum(r["sat_ratio"] for r in late) / len(late)
            assert early_avg > late_avg, (
                f"SAT ratio should decrease: early avg={early_avg:.3f}, "
                f"late avg={late_avg:.3f}"
            )

    def test_critical_m_reasonable(self):
        with open(os.path.join(RESULT_DIR, "phase_transition.json")) as f:
            pt = json.load(f)
        cm = pt["critical_m"]
        assert isinstance(cm, int), f"critical_m must be int, got {type(cm)}"
        assert 3 <= cm <= 11, f"critical_m={cm} outside expected range [3, 11]"

    def test_transition_exists(self):
        """There must be m values on both sides of the transition."""
        with open(os.path.join(RESULT_DIR, "phase_transition.json")) as f:
            pt = json.load(f)
        ratios = [r["sat_ratio"] for r in pt["results"]]
        assert any(r >= 0.6 for r in ratios), (
            "No m value with sat_ratio >= 0.6 (no easy region found)"
        )
        assert any(r <= 0.4 for r in ratios), (
            "No m value with sat_ratio <= 0.4 (no hard region found)"
        )
