
import json
import math
import os
import pytest


RESULTS_PATH = "/app/results.json"

# Ground truth values (NOT exposed to the solver)
TRUE_A = 8.478
TRUE_B = 5.396
TRUE_C = 6.958
TRUE_ZERO = 0.042

# Impurity peak indices in the observed data (0-based)
TRUE_IMPURITY_INDICES = {1, 4, 11, 16, 39, 72, 98}
N_TOTAL_PEAKS = 121
N_MAIN_PEAKS = 114
N_IMPURITY_PEAKS = 7

# True Miller indices for main-phase peaks (in order of observed 2theta,
# skipping impurity indices)
TRUE_HKL_MAP = {}
_main_hkl_list = [
    [1,0,1],[0,1,1],[2,0,0],[1,1,1],[2,0,1],[0,0,2],[2,1,0],[1,0,2],
    [2,1,1],[1,1,2],[0,2,0],[2,0,2],[3,0,1],[1,2,1],[2,1,2],[3,1,1],
    [2,2,0],[1,0,3],[3,0,2],[2,2,1],[0,2,2],[0,1,3],[4,0,0],[1,2,2],
    [1,1,3],[2,0,3],[3,1,2],[4,0,1],[4,1,0],[2,2,2],[2,1,3],[4,1,1],
    [3,2,1],[4,0,2],[3,0,3],[0,3,1],[0,0,4],[1,2,3],[4,1,2],[1,3,1],
    [1,0,4],[3,2,2],[3,1,3],[4,2,0],[2,3,0],[5,0,1],[1,1,4],[2,2,3],
    [4,2,1],[2,3,1],[2,0,4],[5,1,1],[1,3,2],[4,0,3],[2,1,4],[5,0,2],
    [4,2,2],[4,1,3],[2,3,2],[3,2,3],[3,3,1],[3,0,4],[5,1,2],[0,2,4],
    [1,2,4],[3,1,4],[0,3,3],[6,0,0],[5,2,1],[1,3,3],[3,3,2],[6,0,1],
    [2,2,4],[1,0,5],[4,3,0],[5,0,3],[6,1,0],[4,2,3],[0,4,0],[2,3,3],
    [0,1,5],[4,3,1],[4,0,4],[6,1,1],[1,1,5],[5,2,2],[5,1,3],[2,0,5],
    [6,0,2],[1,4,1],[4,1,4],[3,2,4],[2,4,0],[2,1,5],[4,3,2],[6,1,2],
    [3,3,3],[2,4,1],[0,4,2],[6,2,0],[3,0,5],[1,4,2],[1,3,4],[6,2,1],
    [1,2,5],[5,2,3],[3,1,5],[5,3,1],[5,0,4],[6,0,3],[2,4,2],[4,2,4],
    [2,3,4],[3,4,1],
]

_obs_idx = 0
for i in range(N_TOTAL_PEAKS):
    if i in TRUE_IMPURITY_INDICES:
        continue
    if _obs_idx < len(_main_hkl_list):
        TRUE_HKL_MAP[i] = tuple(_main_hkl_list[_obs_idx])
    _obs_idx += 1


@pytest.fixture
def results():
    assert os.path.exists(RESULTS_PATH), f"Results file not found at {RESULTS_PATH}"
    with open(RESULTS_PATH) as f:
        return json.load(f)


class TestResultsStructure:
    def test_results_file_exists(self):
        assert os.path.exists(RESULTS_PATH), "results.json not found"

    def test_has_required_keys(self, results):
        required = [
            "refined_lattice_parameters_angstrom",
            "zero_shift_degrees",
            "peak_assignments",
            "rms_residual_degrees",
            "n_indexed",
            "n_impurity",
        ]
        for key in required:
            assert key in results, f"Missing key: {key}"

    def test_lattice_has_abc(self, results):
        lp = results["refined_lattice_parameters_angstrom"]
        for k in ["a", "b", "c"]:
            assert k in lp, f"Missing lattice parameter: {k}"

    def test_peak_assignments_length(self, results):
        assert len(results["peak_assignments"]) == N_TOTAL_PEAKS, (
            f"Expected {N_TOTAL_PEAKS} peak assignments, got {len(results['peak_assignments'])}"
        )


class TestLatticeParameters:
    def test_a(self, results):
        a = results["refined_lattice_parameters_angstrom"]["a"]
        assert abs(a - TRUE_A) < 0.015, f"a={a}, expected ~{TRUE_A}"

    def test_b(self, results):
        b = results["refined_lattice_parameters_angstrom"]["b"]
        assert abs(b - TRUE_B) < 0.015, f"b={b}, expected ~{TRUE_B}"

    def test_c(self, results):
        c = results["refined_lattice_parameters_angstrom"]["c"]
        assert abs(c - TRUE_C) < 0.015, f"c={c}, expected ~{TRUE_C}"


class TestZeroShift:
    def test_zero_shift(self, results):
        z = results["zero_shift_degrees"]
        assert abs(z - TRUE_ZERO) < 0.02, f"zero_shift={z}, expected ~{TRUE_ZERO}"


class TestRMSResidual:
    def test_rms_below_threshold(self, results):
        rms = results["rms_residual_degrees"]
        assert rms < 0.03, f"RMS residual {rms} exceeds 0.03 degrees"

    def test_rms_positive(self, results):
        rms = results["rms_residual_degrees"]
        assert rms > 0, "RMS residual should be positive"


class TestImpurityDetection:
    def test_impurity_count(self, results):
        n_imp = results["n_impurity"]
        assert n_imp >= 5, f"Detected only {n_imp} impurity peaks, expected at least 5"
        assert n_imp <= 12, f"Detected {n_imp} impurity peaks, too many (expected ~7)"

    def test_impurity_peaks_identified(self, results):
        detected_impurity = set()
        for pa in results["peak_assignments"]:
            if pa["is_impurity"]:
                detected_impurity.add(pa["peak_index"])
        correct = detected_impurity & TRUE_IMPURITY_INDICES
        assert len(correct) >= 5, (
            f"Only {len(correct)} of {N_IMPURITY_PEAKS} impurity peaks correctly identified. "
            f"Detected: {sorted(detected_impurity)}, True: {sorted(TRUE_IMPURITY_INDICES)}"
        )


class TestMillerIndexAssignment:
    def test_indexed_count(self, results):
        n_idx = results["n_indexed"]
        assert n_idx >= 100, f"Only {n_idx} peaks indexed, expected at least 100"

    def test_hkl_correctness(self, results):
        correct = 0
        total_checked = 0
        for pa in results["peak_assignments"]:
            idx = pa["peak_index"]
            if idx in TRUE_HKL_MAP and not pa["is_impurity"]:
                total_checked += 1
                if pa["hkl"] is not None:
                    assigned = tuple(pa["hkl"])
                    if assigned == TRUE_HKL_MAP[idx]:
                        correct += 1
        fraction = correct / max(total_checked, 1)
        assert fraction >= 0.95, (
            f"Only {correct}/{total_checked} ({fraction:.1%}) Miller indices correct, need >= 95%"
        )

    def test_hkl_are_integers(self, results):
        for pa in results["peak_assignments"]:
            if pa["hkl"] is not None:
                assert len(pa["hkl"]) == 3, f"hkl must be 3-element list, got {pa['hkl']}"
                for v in pa["hkl"]:
                    assert isinstance(v, int), f"hkl elements must be integers, got {type(v)}"

    def test_no_forbidden_reflections(self, results):
        """Check that no assigned hkl violates Pnma systematic absences."""
        for pa in results["peak_assignments"]:
            if pa["hkl"] is None:
                continue
            h, k, l = pa["hkl"]
            if h == 0:
                if (k + l) % 2 != 0:
                    pytest.fail(f"Peak {pa['peak_index']}: 0kl=({h},{k},{l}) violates k+l even")
            if l == 0:
                if h % 2 != 0:
                    pytest.fail(f"Peak {pa['peak_index']}: hk0=({h},{k},{l}) violates h even")
            if k == 0 and l == 0:
                if h % 2 != 0:
                    pytest.fail(f"Peak {pa['peak_index']}: h00=({h},0,0) violates h even")
            if h == 0 and l == 0:
                if k % 2 != 0:
                    pytest.fail(f"Peak {pa['peak_index']}: 0k0=(0,{k},0) violates k even")
            if h == 0 and k == 0:
                if l % 2 != 0:
                    pytest.fail(f"Peak {pa['peak_index']}: 00l=(0,0,{l}) violates l even")


class TestConsistency:
    def test_n_indexed_plus_impurity(self, results):
        n_idx = results["n_indexed"]
        n_imp = results["n_impurity"]
        assert n_idx + n_imp == N_TOTAL_PEAKS, (
            f"n_indexed ({n_idx}) + n_impurity ({n_imp}) != total peaks ({N_TOTAL_PEAKS})"
        )

    def test_assignment_consistency(self, results):
        n_imp_from_assignments = sum(
            1 for pa in results["peak_assignments"] if pa["is_impurity"]
        )
        assert n_imp_from_assignments == results["n_impurity"], (
            f"n_impurity field ({results['n_impurity']}) doesn't match "
            f"impurity count in assignments ({n_imp_from_assignments})"
        )

    def test_peak_indices_complete(self, results):
        indices = sorted(pa["peak_index"] for pa in results["peak_assignments"])
        expected = list(range(N_TOTAL_PEAKS))
        assert indices == expected, "peak_assignments should cover all peak indices 0..120"
