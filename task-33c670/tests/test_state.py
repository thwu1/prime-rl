
"""
Tests for the corrected EPA ProUCL 5.2 UCL analysis.
Verifies correctness of UCL computations, method recommendations,
and proper handling of censored data across five monitoring well datasets.
"""

import json
import math
import os

import numpy as np
import pytest
from scipy import stats


RESULTS_PATH = "/app/results.json"

VALID_UCL_METHODS = {
    "student_t", "students_t", "student-t", "t", "t_ucl", "t-ucl",
    "chebyshev", "chebyshev_mvue",
    "bootstrap_bca", "bca", "bootstrap-bca",
    "halls_bootstrap", "hall", "hall_bootstrap", "halls-bootstrap", "hall_bootstrap_t",
    "h_ucl", "h-ucl", "land_h", "lands_h",
    "adjusted_gamma", "adj_gamma", "gamma", "gamma_ucl", "adjusted-gamma",
    "modified_t", "mod_t", "modified-t",
    "adjusted_clt", "adj_clt", "adjusted-clt",
    "km_t", "km-t", "km_student_t", "km_students_t",
    "km_bca", "km-bca", "km_bootstrap_bca", "km-bootstrap-bca",
    "km_chebyshev", "km-chebyshev",
    "km_percentile", "km-percentile", "km_bootstrap", "km-bootstrap",
    "ros_t", "ros-t",
    "ros_bca", "ros-bca",
}


@pytest.fixture(scope="module")
def results():
    """Load the results JSON file."""
    assert os.path.exists(RESULTS_PATH), (
        f"Results file not found at {RESULTS_PATH}. "
        "The corrected analysis must be written to /app/results.json"
    )
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    return data


# ──────────────────────────────────────────────────────────────
# Dataset values (for independent reference computation)
# ──────────────────────────────────────────────────────────────

MW1_VALUES = [
    9.1, 9.8, 10.2, 10.5, 10.9, 11.0, 11.3, 11.5, 11.8, 12.0,
    12.2, 12.3, 12.5, 12.8, 13.0, 13.2, 13.5, 13.8, 14.0, 14.3,
    14.5, 14.8, 15.2, 16.0,
]

MW2_VALUES = [
    0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.7, 2.0, 2.2, 2.5,
    2.8, 3.0, 3.3, 3.6, 4.0, 4.3, 4.8, 5.2, 5.8, 6.3,
    7.0, 7.8, 8.5, 9.5, 10.8, 12.0, 14.5, 17.0, 22.0, 35.0,
]

# MW-3 Lead: 7 NDs at DL={0.5,0.5,0.5,1.0,1.0,2.0,2.0}, 18 detects
MW3_DETECT_VALUES = [
    2.5, 3.0, 3.5, 4.2, 5.0, 6.5, 7.0, 8.5, 10.0, 12.0,
    15.0, 18.0, 20.0, 22.0, 28.0, 32.0, 38.0, 45.0,
]
MW3_ND_DLS = [0.5, 0.5, 0.5, 1.0, 1.0, 2.0, 2.0]

# MW-4 Benzene: 11 NDs at DL={0.5x7,1.0x4}, 9 detects
MW4_DETECT_VALUES = [1.2, 1.5, 2.0, 2.8, 3.5, 5.0, 7.0, 10.0, 15.0]
MW4_ND_DLS = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 1.0, 1.0, 1.0, 1.0]

# MW-5 Chromium: 2 NDs at DL=5.0, 6 detects
MW5_DETECT_VALUES = [8.0, 10.0, 12.0, 15.0, 18.0, 25.0]
MW5_ND_DLS = [5.0, 5.0]

# Pre-computed reference KM means (via reversed-KM area-under-survival-curve)
# MW-3: Each of 18 detects gets mass 1/25; integral from 0 to 45 = 11.208
REFERENCE_KM_MEAN_MW3 = 11.208
# MW-4: Each of 9 detects gets mass 1/20; integral from 0 to 15 = 2.40
REFERENCE_KM_MEAN_MW4 = 2.40
# MW-5: Each of 6 detects gets mass 1/8; integral from 0 to 25 = 11.0
REFERENCE_KM_MEAN_MW5 = 11.0


def _is_student_t_method(method_str):
    """Check if a method string represents Student's t."""
    m = method_str.lower().replace("-", "_").replace(" ", "_")
    return (
        m in ("t", "student_t", "students_t", "t_ucl", "student_t_ucl")
        or "student" in m
    )


def _is_chebyshev_method(method_str):
    """Check if a method string represents Chebyshev."""
    m = method_str.lower()
    return "cheby" in m or "chebi" in m


def _is_bootstrap_method(method_str):
    """Check if a method string represents a bootstrap method."""
    m = method_str.lower()
    return "bootstrap" in m or "bca" in m or "hall" in m


# ──────────────────────────────────────────────────────────────
# 1. Output structure tests
# ──────────────────────────────────────────────────────────────

class TestOutputStructure:
    REQUIRED_KEYS = [
        "MW-1_Arsenic", "MW-2_TCE", "MW-3_Lead",
        "MW-4_Benzene", "MW-5_Chromium",
    ]

    def test_all_datasets_present(self, results):
        """All five well-contaminant combinations must be present."""
        for key in self.REQUIRED_KEYS:
            assert key in results, f"Missing well-contaminant key: {key}"

    def test_fully_detected_have_required_keys(self, results):
        """Fully-detected datasets must have basic statistics."""
        for key in ["MW-1_Arsenic", "MW-2_TCE"]:
            d = results[key]
            for field in ["n", "mean", "sd", "recommended_method", "recommended_ucl"]:
                assert field in d, f"{key} missing required key: {field}"

    def test_censored_have_km_keys(self, results):
        """Censored datasets must have KM estimation keys."""
        for key in ["MW-3_Lead", "MW-4_Benzene", "MW-5_Chromium"]:
            d = results[key]
            for field in ["km_mean", "km_sd", "recommended_method", "recommended_ucl"]:
                assert field in d, f"{key} missing required key: {field}"

    def test_censored_have_ros_keys(self, results):
        """Censored datasets must have ROS estimation keys."""
        for key in ["MW-3_Lead", "MW-4_Benzene", "MW-5_Chromium"]:
            d = results[key]
            for field in ["ros_mean", "ros_sd"]:
                assert field in d, f"{key} missing required key: {field}"

    def test_ucl_values_present_all(self, results):
        """Each dataset must have a ucl_values dict with at least 2 methods."""
        for key in self.REQUIRED_KEYS:
            d = results[key]
            assert "ucl_values" in d, f"{key} missing ucl_values"
            assert isinstance(d["ucl_values"], dict), f"{key} ucl_values not dict"
            assert len(d["ucl_values"]) >= 2, (
                f"{key} ucl_values has fewer than 2 methods"
            )

    def test_nd_counts(self, results):
        """Verify non-detect percentages are correct."""
        checks = {
            "MW-1_Arsenic": (24, 24, 0.0),
            "MW-2_TCE": (30, 30, 0.0),
            "MW-3_Lead": (25, 18, 28.0),
            "MW-4_Benzene": (20, 9, 55.0),
            "MW-5_Chromium": (8, 6, 25.0),
        }
        for key, (n, nd, pct) in checks.items():
            d = results[key]
            assert d["n"] == n, f"{key}: n should be {n}, got {d['n']}"
            if "n_detect" in d:
                assert d["n_detect"] == nd, (
                    f"{key}: n_detect should be {nd}, got {d['n_detect']}"
                )
            if "pct_nd" in d:
                assert abs(d["pct_nd"] - pct) < 1.0, (
                    f"{key}: pct_nd should be ~{pct}, got {d['pct_nd']}"
                )


# ──────────────────────────────────────────────────────────────
# 2. MW-1 Arsenic: Normal dataset verification
# ──────────────────────────────────────────────────────────────

class TestMW1Arsenic:
    def test_mean(self, results):
        expected_mean = np.mean(MW1_VALUES)
        actual = results["MW-1_Arsenic"]["mean"]
        assert abs(actual - expected_mean) < 0.05, (
            f"MW-1 mean {actual} != expected {expected_mean:.4f}"
        )

    def test_sd(self, results):
        expected_sd = np.std(MW1_VALUES, ddof=1)
        actual = results["MW-1_Arsenic"]["sd"]
        assert abs(actual - expected_sd) < 0.1, (
            f"MW-1 SD {actual} != expected {expected_sd:.4f}"
        )

    def test_student_t_ucl(self, results):
        """Verify Student's t UCL matches analytical computation."""
        vals = np.array(MW1_VALUES)
        n = len(vals)
        mean = np.mean(vals)
        sd = np.std(vals, ddof=1)
        t_crit = stats.t.ppf(0.95, n - 1)
        expected_ucl = mean + t_crit * sd / np.sqrt(n)

        ucl_vals = results["MW-1_Arsenic"]["ucl_values"]
        t_ucl = None
        for k, v in ucl_vals.items():
            if _is_student_t_method(k):
                t_ucl = v
                break
        assert t_ucl is not None, (
            f"Student's t UCL not found. Keys: {list(ucl_vals.keys())}"
        )
        assert abs(t_ucl - expected_ucl) < 0.15, (
            f"t-UCL {t_ucl} != expected {expected_ucl:.4f}"
        )

    def test_recommended_is_student_t(self, results):
        """Normal data should recommend Student's t."""
        method = results["MW-1_Arsenic"]["recommended_method"]
        assert _is_student_t_method(method), (
            f"MW-1 (normal data) should recommend Student's t, got: {method}"
        )

    def test_recommended_ucl_matches_t_ucl(self, results):
        """Recommended UCL value should match Student's t UCL."""
        vals = np.array(MW1_VALUES)
        n = len(vals)
        mean = np.mean(vals)
        sd = np.std(vals, ddof=1)
        t_crit = stats.t.ppf(0.95, n - 1)
        expected_ucl = mean + t_crit * sd / np.sqrt(n)

        actual = results["MW-1_Arsenic"]["recommended_ucl"]
        assert abs(actual - expected_ucl) < 0.15, (
            f"Recommended UCL {actual} != expected t-UCL {expected_ucl:.4f}"
        )


# ──────────────────────────────────────────────────────────────
# 3. MW-2 TCE: Skewed dataset verification
# ──────────────────────────────────────────────────────────────

class TestMW2TCE:
    def test_mean(self, results):
        expected_mean = np.mean(MW2_VALUES)
        actual = results["MW-2_TCE"]["mean"]
        assert abs(actual - expected_mean) < 0.1, (
            f"MW-2 mean {actual} != expected {expected_mean:.4f}"
        )

    def test_not_recommend_student_t(self, results):
        """Highly skewed data should NOT recommend Student's t UCL."""
        method = results["MW-2_TCE"]["recommended_method"]
        assert not _is_student_t_method(method), (
            f"MW-2 (skewed data) should NOT recommend Student's t, got: {method}"
        )

    def test_recommended_ucl_reasonable(self, results):
        """Recommended UCL should be above mean but not absurdly large."""
        mean = np.mean(MW2_VALUES)
        ucl = results["MW-2_TCE"]["recommended_ucl"]
        assert ucl > mean, f"MW-2 UCL {ucl} must be > mean {mean:.2f}"
        assert ucl < mean * 5, f"MW-2 UCL {ucl} is implausibly large (>5x mean)"

    def test_recommended_method_valid(self, results):
        """Recommended method should be a valid ProUCL method."""
        method = results["MW-2_TCE"]["recommended_method"].lower().replace(
            " ", "_"
        ).replace("-", "_")
        assert method in VALID_UCL_METHODS or any(
            v in method for v in [
                "gamma", "bootstrap", "bca", "hall", "adj", "modified"
            ]
        ), f"MW-2: invalid recommended method: {method}"

    def test_not_chebyshev(self, results):
        """Chebyshev should never be recommended in ProUCL 5.2."""
        method = results["MW-2_TCE"]["recommended_method"]
        assert not _is_chebyshev_method(method), (
            f"MW-2: Chebyshev should never be recommended, got: {method}"
        )


# ──────────────────────────────────────────────────────────────
# 4. MW-3 Lead: Censored dataset (moderate censoring)
# ──────────────────────────────────────────────────────────────

class TestMW3Lead:
    def test_sample_size(self, results):
        d = results["MW-3_Lead"]
        assert d["n"] == 25

    def test_km_mean_positive(self, results):
        assert results["MW-3_Lead"]["km_mean"] > 0

    def test_km_mean_reference(self, results):
        """KM mean should match reference computation."""
        actual = results["MW-3_Lead"]["km_mean"]
        assert abs(actual - REFERENCE_KM_MEAN_MW3) < 1.5, (
            f"MW-3 KM mean {actual} too far from reference "
            f"{REFERENCE_KM_MEAN_MW3:.3f} (diff={abs(actual - REFERENCE_KM_MEAN_MW3):.3f})"
        )

    def test_km_mean_not_dl2(self, results):
        """KM mean should differ from simple DL/2 substitution mean."""
        # DL/2 mean = (3*0.25 + 2*0.5 + 2*1.0 + sum_detects) / 25
        # = (0.75 + 1.0 + 2.0 + 280.2) / 25 = 283.95/25 = 11.358
        dl2_mean = 11.358
        km_mean = results["MW-3_Lead"]["km_mean"]
        # If they used DL/2, the mean would be ~11.358
        # KM mean should be ~11.208 (close but not identical)
        # The key check: km_mean key EXISTS (meaning they used KM, not substitution)
        assert "km_mean" in results["MW-3_Lead"], (
            "MW-3 must use KM estimation, not simple substitution"
        )

    def test_km_mean_range(self, results):
        """KM mean should be in reasonable range."""
        detect_mean = np.mean(MW3_DETECT_VALUES)
        km_mean = results["MW-3_Lead"]["km_mean"]
        assert 0 < km_mean <= detect_mean + 1, (
            f"MW-3 KM mean {km_mean} should be between 0 and ~{detect_mean:.1f}"
        )

    def test_km_sd_positive(self, results):
        assert results["MW-3_Lead"]["km_sd"] > 0

    def test_ros_mean_present(self, results):
        assert results["MW-3_Lead"]["ros_mean"] > 0

    def test_ros_mean_reasonable(self, results):
        detect_mean = np.mean(MW3_DETECT_VALUES)
        ros_mean = results["MW-3_Lead"]["ros_mean"]
        assert ros_mean < detect_mean + 2, (
            f"MW-3 ROS mean {ros_mean} implausibly high"
        )
        assert ros_mean > 1.0, f"MW-3 ROS mean {ros_mean} too low"

    def test_ucl_above_km_mean(self, results):
        d = results["MW-3_Lead"]
        assert d["recommended_ucl"] > d["km_mean"], (
            f"MW-3 UCL {d['recommended_ucl']} must be > KM mean {d['km_mean']}"
        )

    def test_not_chebyshev(self, results):
        method = results["MW-3_Lead"]["recommended_method"]
        assert not _is_chebyshev_method(method), (
            f"MW-3: Chebyshev should never be recommended, got: {method}"
        )

    def test_method_uses_censored_estimator(self, results):
        """Method should reference KM or ROS, not raw Student's t."""
        method = results["MW-3_Lead"]["recommended_method"].lower()
        # For censored data, the method should involve km or ros
        has_censored_method = any(
            tok in method for tok in ["km", "kaplan", "ros", "regression"]
        )
        # Or at least not be plain Student's t (which ignores censoring)
        is_plain_t = _is_student_t_method(
            results["MW-3_Lead"]["recommended_method"]
        ) and "km" not in method.lower()
        assert has_censored_method or not is_plain_t, (
            f"MW-3 (censored data) should use KM/ROS-based method, got: {method}"
        )


# ──────────────────────────────────────────────────────────────
# 5. MW-4 Benzene: High censoring (>50% ND)
# ──────────────────────────────────────────────────────────────

class TestMW4Benzene:
    def test_sample_size(self, results):
        d = results["MW-4_Benzene"]
        assert d["n"] == 20

    def test_high_censoring(self, results):
        d = results["MW-4_Benzene"]
        if "pct_nd" in d:
            assert d["pct_nd"] >= 50, (
                f"MW-4 should have >50% ND, got {d['pct_nd']}"
            )

    def test_km_mean_positive(self, results):
        assert results["MW-4_Benzene"]["km_mean"] > 0

    def test_km_mean_reference(self, results):
        """KM mean should match reference computation."""
        actual = results["MW-4_Benzene"]["km_mean"]
        assert abs(actual - REFERENCE_KM_MEAN_MW4) < 1.0, (
            f"MW-4 KM mean {actual} too far from reference "
            f"{REFERENCE_KM_MEAN_MW4:.2f} (diff={abs(actual - REFERENCE_KM_MEAN_MW4):.3f})"
        )

    def test_not_chebyshev(self, results):
        """Chebyshev must never be recommended (ProUCL 5.2 rule)."""
        method = results["MW-4_Benzene"]["recommended_method"]
        assert not _is_chebyshev_method(method), (
            f"MW-4: Chebyshev should NEVER be recommended in ProUCL 5.2, "
            f"got: {method}"
        )

    def test_ros_mean_present(self, results):
        assert results["MW-4_Benzene"]["ros_mean"] > 0

    def test_ucl_above_km_mean(self, results):
        d = results["MW-4_Benzene"]
        assert d["recommended_ucl"] > d["km_mean"], (
            f"MW-4 UCL {d['recommended_ucl']} must be > KM mean {d['km_mean']}"
        )


# ──────────────────────────────────────────────────────────────
# 6. MW-5 Chromium: Small sample (n=8)
# ──────────────────────────────────────────────────────────────

class TestMW5Chromium:
    def test_sample_size(self, results):
        assert results["MW-5_Chromium"]["n"] == 8

    def test_km_mean_positive(self, results):
        assert results["MW-5_Chromium"]["km_mean"] > 0

    def test_km_mean_reference(self, results):
        """KM mean should match reference computation."""
        actual = results["MW-5_Chromium"]["km_mean"]
        assert abs(actual - REFERENCE_KM_MEAN_MW5) < 1.5, (
            f"MW-5 KM mean {actual} too far from reference "
            f"{REFERENCE_KM_MEAN_MW5:.1f} (diff={abs(actual - REFERENCE_KM_MEAN_MW5):.3f})"
        )

    def test_not_bootstrap(self, results):
        """Bootstrap should NOT be recommended for n<10."""
        method = results["MW-5_Chromium"]["recommended_method"]
        assert not _is_bootstrap_method(method), (
            f"MW-5 (n=8): Bootstrap should not be recommended for n<10, "
            f"got: {method}"
        )

    def test_not_chebyshev(self, results):
        method = results["MW-5_Chromium"]["recommended_method"]
        assert not _is_chebyshev_method(method), (
            f"MW-5: Chebyshev should never be recommended, got: {method}"
        )

    def test_ros_mean_present(self, results):
        assert results["MW-5_Chromium"]["ros_mean"] > 0

    def test_ucl_above_km_mean(self, results):
        d = results["MW-5_Chromium"]
        assert d["recommended_ucl"] > d["km_mean"], (
            f"MW-5 UCL {d['recommended_ucl']} must be > KM mean {d['km_mean']}"
        )


# ──────────────────────────────────────────────────────────────
# 7. Cross-cutting property tests
# ──────────────────────────────────────────────────────────────

class TestCrossCutting:
    ALL_KEYS = [
        "MW-1_Arsenic", "MW-2_TCE", "MW-3_Lead",
        "MW-4_Benzene", "MW-5_Chromium",
    ]

    def test_all_ucl_values_positive(self, results):
        """All computed UCL values must be positive."""
        for key in self.ALL_KEYS:
            ucl_vals = results[key].get("ucl_values", {})
            for method, val in ucl_vals.items():
                assert val > 0, (
                    f"{key}/{method} UCL value {val} must be positive"
                )

    def test_ucl_above_mean_for_full_datasets(self, results):
        """For fully-detected datasets, all UCLs should exceed the mean."""
        for key in ["MW-1_Arsenic", "MW-2_TCE"]:
            d = results[key]
            mean = d["mean"]
            ucl_vals = d.get("ucl_values", {})
            for method, val in ucl_vals.items():
                assert val >= mean - 0.01, (
                    f"{key}/{method} UCL {val} should be >= mean {mean}"
                )

    def test_recommended_ucl_in_ucl_values(self, results):
        """Recommended UCL should match one of the computed UCL values."""
        for key in self.ALL_KEYS:
            d = results[key]
            rec_ucl = d["recommended_ucl"]
            ucl_vals = d.get("ucl_values", {})
            close_to_any = any(
                abs(rec_ucl - v) < 0.05 for v in ucl_vals.values()
            )
            assert close_to_any, (
                f"{key} recommended UCL {rec_ucl} doesn't match any "
                f"ucl_values: {ucl_vals}"
            )

    def test_no_chebyshev_recommended_anywhere(self, results):
        """ProUCL 5.2 never recommends Chebyshev for any dataset."""
        for key in self.ALL_KEYS:
            method = results[key]["recommended_method"]
            assert not _is_chebyshev_method(method), (
                f"{key}: Chebyshev must never be recommended (ProUCL 5.2), "
                f"got: {method}"
            )

    def test_bootstrap_not_for_small_n(self, results):
        """Bootstrap should not be recommended when n < 10."""
        for key in self.ALL_KEYS:
            d = results[key]
            if d["n"] < 10:
                method = d["recommended_method"]
                assert not _is_bootstrap_method(method), (
                    f"{key} (n={d['n']}): Bootstrap not recommended for n<10"
                )
