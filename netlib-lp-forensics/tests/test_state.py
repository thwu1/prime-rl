
import json
import os
import subprocess
import math
import pytest

# Known optimal values from the Netlib LP test set documentation
# Reference: MINOS 5.3 on VAX, double precision (from lp/data readme)
REFERENCE_OPTIMAL = {
    "afiro": -4.6475314286e+02,
    "blend": -3.0812149846e+01,
    "sc50a": -6.4575077059e+01,
    "sc50b": -7.0000000000e+01,
    "adlittle": 2.2549496316e+05,
    "kb2": -1.7499001299e+03,
}

# Known dimensions from Netlib PROBLEM SUMMARY TABLE
# Row counts in the table include the cost row; num_constraints = rows - 1
# Col counts are structural variables (excluding slacks)
KNOWN_DIMENSIONS = {
    "afiro": {"num_constraints": 27, "num_variables": 32},
    "blend": {"num_constraints": 74, "num_variables": 83},
    "sc50a": {"num_constraints": 50, "num_variables": 48},
    "sc50b": {"num_constraints": 50, "num_variables": 48},
    "adlittle": {"num_constraints": 56, "num_variables": 97},
    "kb2": {"num_constraints": 43, "num_variables": 41},
}

# Expected ranking by optimal value (ascending)
EXPECTED_RANKING = ["kb2", "afiro", "sc50b", "sc50a", "blend", "adlittle"]

PROBLEMS = ["afiro", "blend", "sc50a", "sc50b", "adlittle", "kb2"]


@pytest.fixture
def results():
    with open("/app/results.json") as f:
        return json.load(f)


class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists("/app/results.json"), \
            "results.json not found at /app/results.json"

    def test_problems_key(self, results):
        assert "problems" in results, "Missing 'problems' key in results"

    def test_ranking_key(self, results):
        assert "ranking_by_optimal_value" in results, \
            "Missing 'ranking_by_optimal_value' key"

    def test_all_problems_present(self, results):
        for prob in PROBLEMS:
            assert prob in results["problems"], \
                f"Problem '{prob}' missing from results"

    def test_required_fields(self, results):
        required = [
            "optimal_value", "num_constraints", "num_variables",
            "num_basic_variables", "max_primal_infeasibility",
            "max_dual_infeasibility",
            "max_complementary_slackness_violation",
            "num_degenerate_basics", "has_alternative_optima",
            "basis_condition_number_log10"
        ]
        for prob in PROBLEMS:
            for field in required:
                assert field in results["problems"][prob], \
                    f"Problem '{prob}' missing field '{field}'"


class TestOptimalValues:
    """Verify optimal values match Netlib MINOS 5.3 reference values."""

    def test_afiro(self, results):
        self._check_optimal("afiro", results)

    def test_blend(self, results):
        self._check_optimal("blend", results)

    def test_sc50a(self, results):
        self._check_optimal("sc50a", results)

    def test_sc50b(self, results):
        self._check_optimal("sc50b", results)

    def test_adlittle(self, results):
        self._check_optimal("adlittle", results)

    def test_kb2(self, results):
        self._check_optimal("kb2", results)

    def _check_optimal(self, prob, results):
        actual = results["problems"][prob]["optimal_value"]
        expected = REFERENCE_OPTIMAL[prob]
        if abs(expected) > 1e-10:
            rel_err = abs(actual - expected) / abs(expected)
            assert rel_err < 1e-6, \
                (f"{prob}: optimal_value {actual} differs from reference "
                 f"{expected} (rel_err={rel_err:.2e})")
        else:
            assert abs(actual - expected) < 1e-6, \
                f"{prob}: optimal_value {actual} differs from reference {expected}"


class TestDimensions:
    """Verify problem dimensions match the Netlib summary table."""

    @pytest.mark.parametrize("prob", PROBLEMS)
    def test_num_constraints(self, results, prob):
        actual = results["problems"][prob]["num_constraints"]
        expected = KNOWN_DIMENSIONS[prob]["num_constraints"]
        assert actual == expected, \
            f"{prob}: num_constraints {actual} != expected {expected}"

    @pytest.mark.parametrize("prob", PROBLEMS)
    def test_num_variables(self, results, prob):
        actual = results["problems"][prob]["num_variables"]
        expected = KNOWN_DIMENSIONS[prob]["num_variables"]
        assert actual == expected, \
            f"{prob}: num_variables {actual} != expected {expected}"


class TestLPInvariants:
    """Verify fundamental LP theory invariants hold."""

    @pytest.mark.parametrize("prob", PROBLEMS)
    def test_basic_equals_constraints(self, results, prob):
        """Fundamental theorem of LP: num basic variables = num constraints."""
        nb = results["problems"][prob]["num_basic_variables"]
        nc = results["problems"][prob]["num_constraints"]
        assert nb == nc, \
            f"{prob}: num_basic_variables ({nb}) != num_constraints ({nc})"

    @pytest.mark.parametrize("prob", PROBLEMS)
    def test_primal_feasibility(self, results, prob):
        pi = results["problems"][prob]["max_primal_infeasibility"]
        assert isinstance(pi, (int, float)), \
            f"{prob}: max_primal_infeasibility not numeric"
        assert pi < 1e-6, \
            f"{prob}: max_primal_infeasibility {pi} >= 1e-6"

    @pytest.mark.parametrize("prob", PROBLEMS)
    def test_dual_feasibility(self, results, prob):
        di = results["problems"][prob]["max_dual_infeasibility"]
        assert isinstance(di, (int, float)), \
            f"{prob}: max_dual_infeasibility not numeric"
        assert di < 1e-6, \
            f"{prob}: max_dual_infeasibility {di} >= 1e-6"

    @pytest.mark.parametrize("prob", PROBLEMS)
    def test_complementary_slackness(self, results, prob):
        cs = results["problems"][prob][
            "max_complementary_slackness_violation"]
        assert isinstance(cs, (int, float)), \
            f"{prob}: max_complementary_slackness_violation not numeric"
        assert cs < 1e-6, \
            f"{prob}: max_complementary_slackness_violation {cs} >= 1e-6"

    @pytest.mark.parametrize("prob", PROBLEMS)
    def test_degenerate_count_in_range(self, results, prob):
        nd = results["problems"][prob]["num_degenerate_basics"]
        nb = results["problems"][prob]["num_basic_variables"]
        assert isinstance(nd, int), \
            f"{prob}: num_degenerate_basics not integer"
        assert 0 <= nd <= nb, \
            f"{prob}: num_degenerate_basics {nd} not in [0, {nb}]"

    @pytest.mark.parametrize("prob", PROBLEMS)
    def test_alternative_optima_is_bool(self, results, prob):
        ao = results["problems"][prob]["has_alternative_optima"]
        assert isinstance(ao, bool), \
            f"{prob}: has_alternative_optima should be bool, got {type(ao)}"

    @pytest.mark.parametrize("prob", PROBLEMS)
    def test_basis_condition_valid(self, results, prob):
        """Basis condition number must be a finite positive value."""
        bc = results["problems"][prob]["basis_condition_number_log10"]
        assert isinstance(bc, (int, float)), \
            f"{prob}: basis_condition_number_log10 not numeric"
        assert math.isfinite(bc), \
            f"{prob}: basis_condition_number_log10 is not finite"
        assert bc >= 0, \
            f"{prob}: basis_condition_number_log10 {bc} < 0 (condition number must be >= 1)"
        assert bc < 16, \
            f"{prob}: basis_condition_number_log10 {bc} >= 16 (suspiciously ill-conditioned for small LP)"


class TestRanking:
    """Verify problem ranking by optimal value."""

    def test_ranking_correct(self, results):
        ranking = results["ranking_by_optimal_value"]
        assert ranking == EXPECTED_RANKING, \
            f"Ranking {ranking} != expected {EXPECTED_RANKING}"

    def test_ranking_length(self, results):
        ranking = results["ranking_by_optimal_value"]
        assert len(ranking) == len(PROBLEMS), \
            f"Ranking has {len(ranking)} entries, expected {len(PROBLEMS)}"
        assert set(ranking) == set(PROBLEMS), \
            f"Ranking problems don't match expected set"

    def test_ranking_consistent_with_values(self, results):
        ranking = results["ranking_by_optimal_value"]
        values = [results["problems"][p]["optimal_value"] for p in ranking]
        for i in range(len(values) - 1):
            assert values[i] <= values[i + 1], \
                (f"Ranking not sorted: {ranking[i]}={values[i]} > "
                 f"{ranking[i+1]}={values[i+1]}")


class TestIndependentVerification:
    """Cross-validate by independently solving AFIRO with HiGHS."""

    def test_cross_validate_afiro(self, results):
        try:
            import highspy
        except ImportError:
            pytest.skip("highspy not available for cross-validation")

        mps_file = self._get_mps_file("afiro")
        if mps_file is None:
            pytest.skip("Could not obtain AFIRO MPS file for "
                        "cross-validation")

        h = highspy.Highs()
        h.setOptionValue("output_flag", False)
        h.readModel(mps_file)
        h.run()

        status, ref_obj = h.getInfoValue("objective_function_value")
        agent_obj = results["problems"]["afiro"]["optimal_value"]

        assert abs(agent_obj - ref_obj) < 1e-6, \
            f"Cross-validation failed: agent={agent_obj}, HiGHS={ref_obj}"

        assert h.getNumRow() == \
            results["problems"]["afiro"]["num_constraints"]
        assert h.getNumCol() == \
            results["problems"]["afiro"]["num_variables"]

    def test_cross_validate_condition_afiro(self, results):
        """Cross-validate basis condition number for AFIRO."""
        try:
            import highspy
            import numpy as np
        except ImportError:
            pytest.skip("highspy/numpy not available for cross-validation")

        mps_file = self._get_mps_file("afiro")
        if mps_file is None:
            pytest.skip("Could not obtain AFIRO MPS file")

        h = highspy.Highs()
        h.setOptionValue("output_flag", False)
        h.readModel(mps_file)
        h.run()

        try:
            ref_cond_log10 = self._compute_basis_cond_log10(h)
        except Exception:
            pytest.skip("Could not compute reference basis condition number")

        agent_cond = results["problems"]["afiro"][
            "basis_condition_number_log10"]

        assert abs(agent_cond - ref_cond_log10) < 2.0, \
            (f"Basis condition cross-validation: agent={agent_cond:.2f}, "
             f"reference={ref_cond_log10:.2f}, diff > 2.0 in log10 space")

    def _compute_basis_cond_log10(self, h):
        """Compute log10 of 1-norm condition number of optimal basis."""
        import numpy as np

        nr = h.getNumRow()
        nc = h.getNumCol()

        basis = h.getBasis()
        col_status = [int(s) for s in basis.col_status]
        row_status = [int(s) for s in basis.row_status]

        BASIC = 1

        lp = h.getLp()
        starts = list(lp.a_matrix_.start_)
        indices = list(lp.a_matrix_.index_)
        values = list(lp.a_matrix_.value_)

        B = np.zeros((nr, nr))
        b_col = 0

        for j in range(nc):
            if col_status[j] == BASIC:
                for k in range(starts[j], starts[j + 1]):
                    B[indices[k], b_col] = values[k]
                b_col += 1

        for i in range(nr):
            if row_status[i] == BASIC:
                B[i, b_col] = 1.0
                b_col += 1

        cond = np.linalg.cond(B, 1)
        return math.log10(max(cond, 1.0))

    def _get_mps_file(self, prob):
        """Find an existing MPS file or decompress from raw data."""
        for loc in ['/app/mps', '/app/problems', '/app/data/mps', '/app']:
            candidate = os.path.join(loc, f'{prob}.mps')
            if os.path.exists(candidate):
                return candidate

        compressed = f'/app/data/{prob}'
        if not os.path.exists(compressed):
            return None

        emps = self._get_emps()
        if emps is None:
            return None

        mps_file = f'/tmp/{prob}_verify.mps'
        try:
            with open(compressed, 'r') as fin:
                with open(mps_file, 'w') as fout:
                    subprocess.run([emps], stdin=fin, stdout=fout,
                                   check=True, timeout=30)
            return mps_file
        except Exception:
            return None

    def _get_emps(self):
        """Find or compile the emps decompressor."""
        for loc in ['/tmp/emps', '/usr/local/bin/emps', '/app/emps']:
            if os.path.exists(loc) and os.access(loc, os.X_OK):
                return loc

        try:
            subprocess.run(
                ['curl', '-sfL', '-o', '/tmp/emps_verify.c',
                 'https://www.netlib.org/lp/data/emps.c'],
                check=True, timeout=30
            )
            subprocess.run(
                ['gcc', '-o', '/tmp/emps_verify', '/tmp/emps_verify.c'],
                check=True, timeout=30
            )
            return '/tmp/emps_verify'
        except Exception:
            return None
