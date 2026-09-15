
"""
Tests for the battery state-of-health analysis pipeline.

Verifies formation loss calculations against independently computed values
from Chen2020 parameters, validates discharge comparison results for
physical consistency, checks two-stage degradation trajectory outputs,
and validates sensitivity sweep for monotonicity and cross-section consistency.
"""

import json
import math
import os

import pytest


@pytest.fixture(scope="module")
def results():
    """Load results from the solution output."""
    results_path = "/app/results.json"
    assert os.path.exists(results_path), (
        f"Results file not found at {results_path}. "
        "The analysis script must write output to /app/results.json."
    )
    with open(results_path) as f:
        data = json.load(f)
    return data


# ── Helpers for independent formation-loss verification ──────────────

# Chen2020 parameter values (hardcoded from source for independent verification)
_F = 96485.3
_Z_SEI = 2.0
_V_BAR_SEI = 9.585e-05
_L_N = 8.52e-05
_L_Y = 1.58
_L_Z = 0.065
_V_N = _L_N * _L_Y * _L_Z
_R_N = 5.86e-06
_EPS_ACT_N = 0.75
_A_N = 3.0 * _EPS_ACT_N / _R_N
_EPS_NEG = 0.25
_C_MAX_N = 33133.0
_C_INIT_N = 29866.0
_DELTA_Q = 0.135

_C_SEI = _DELTA_Q * 3600 / (_F * _Z_SEI * _V_N)
_DELTA_C_N = _C_SEI * _Z_SEI / _EPS_ACT_N
_C_INIT_DEGRADED = _C_INIT_N - _DELTA_C_N
_L_SEI = _C_SEI * _V_BAR_SEI / _A_N
_EPS_DEGRADED = _EPS_NEG - _L_SEI * _A_N
_INITIAL_STO = _C_INIT_N / _C_MAX_N
_DEGRADED_STO = _C_INIT_DEGRADED / _C_MAX_N
_SEI_NM = _L_SEI * 1e9


# ── Formation Loss Tests ─────────────────────────────────────────────

class TestFormationStructure:
    """Verify the formation section exists and has the right keys."""

    def test_formation_key_exists(self, results):
        assert "formation" in results

    def test_all_formation_keys_present(self, results):
        f = results["formation"]
        required = [
            "capacity_loss_ah",
            "initial_stoichiometry",
            "degraded_stoichiometry",
            "sei_thickness_nm",
            "degraded_porosity",
        ]
        for key in required:
            assert key in f, f"Missing key: formation.{key}"

    def test_all_formation_values_are_numeric(self, results):
        f = results["formation"]
        for key, val in f.items():
            assert isinstance(val, (int, float)), (
                f"formation.{key} should be numeric, got {type(val)}"
            )
            assert not math.isnan(val), f"formation.{key} is NaN"
            assert not math.isinf(val), f"formation.{key} is infinite"


class TestFormationValues:
    """Verify the formation calculations match independently computed values."""

    def test_capacity_loss_reported(self, results):
        assert abs(results["formation"]["capacity_loss_ah"] - 0.135) < 0.001

    def test_initial_stoichiometry(self, results):
        val = results["formation"]["initial_stoichiometry"]
        assert abs(val - _INITIAL_STO) < 0.005, (
            f"initial_stoichiometry={val}, expected~{_INITIAL_STO:.4f}"
        )

    def test_degraded_stoichiometry(self, results):
        val = results["formation"]["degraded_stoichiometry"]
        assert abs(val - _DEGRADED_STO) < 0.005, (
            f"degraded_stoichiometry={val}, expected~{_DEGRADED_STO:.4f}"
        )

    def test_stoichiometry_decreased(self, results):
        f = results["formation"]
        assert f["degraded_stoichiometry"] < f["initial_stoichiometry"]

    def test_stoichiometry_decrease_magnitude(self, results):
        f = results["formation"]
        drop = f["initial_stoichiometry"] - f["degraded_stoichiometry"]
        expected_drop = _INITIAL_STO - _DEGRADED_STO
        assert abs(drop - expected_drop) < 0.005, (
            f"Stoichiometry drop={drop:.4f}, expected~{expected_drop:.4f}"
        )

    def test_sei_thickness_range(self, results):
        val = results["formation"]["sei_thickness_nm"]
        assert 50 < val < 100, f"SEI thickness={val} nm, expected 50-100 nm"

    def test_sei_thickness_accuracy(self, results):
        val = results["formation"]["sei_thickness_nm"]
        assert abs(val - _SEI_NM) < 5.0, (
            f"SEI thickness={val:.1f} nm, expected~{_SEI_NM:.1f} nm"
        )

    def test_degraded_porosity_range(self, results):
        val = results["formation"]["degraded_porosity"]
        assert 0.15 < val < 0.25, (
            f"Degraded porosity={val}, expected between 0.15 and 0.25"
        )

    def test_degraded_porosity_accuracy(self, results):
        val = results["formation"]["degraded_porosity"]
        assert abs(val - _EPS_DEGRADED) < 0.005, (
            f"Degraded porosity={val:.4f}, expected~{_EPS_DEGRADED:.4f}"
        )

    def test_porosity_decreased(self, results):
        val = results["formation"]["degraded_porosity"]
        assert val < _EPS_NEG, (
            f"Degraded porosity={val} should be less than pristine={_EPS_NEG}"
        )


# ── Discharge Comparison Tests ────────────────────────────────────────

class TestDischargeStructure:
    """Verify the discharge section has the right structure."""

    def test_discharge_key_exists(self, results):
        assert "discharge" in results

    def test_all_discharge_keys_present(self, results):
        d = results["discharge"]
        required = [
            "pristine_capacity_ah",
            "degraded_capacity_ah",
            "capacity_difference_ah",
            "pristine_energy_wh",
            "degraded_energy_wh",
        ]
        for key in required:
            assert key in d, f"Missing key: discharge.{key}"

    def test_all_discharge_values_numeric(self, results):
        d = results["discharge"]
        for key, val in d.items():
            assert isinstance(val, (int, float)), (
                f"discharge.{key} should be numeric, got {type(val)}"
            )
            assert not math.isnan(val), f"discharge.{key} is NaN"


class TestDischargePhysics:
    """Verify discharge results satisfy physical constraints."""

    def test_pristine_capacity_range(self, results):
        cap = results["discharge"]["pristine_capacity_ah"]
        assert 4.5 < cap < 5.5, f"Pristine capacity={cap}, expected 4.5-5.5 Ah"

    def test_degraded_capacity_range(self, results):
        cap = results["discharge"]["degraded_capacity_ah"]
        assert 4.0 < cap < 5.3, f"Degraded capacity={cap}, expected 4.0-5.3 Ah"

    def test_pristine_greater_than_degraded(self, results):
        d = results["discharge"]
        assert d["pristine_capacity_ah"] > d["degraded_capacity_ah"], (
            "Pristine capacity must exceed degraded capacity"
        )

    def test_capacity_difference_positive(self, results):
        diff = results["discharge"]["capacity_difference_ah"]
        assert diff > 0, f"Capacity difference={diff}, must be positive"

    def test_capacity_difference_range(self, results):
        diff = results["discharge"]["capacity_difference_ah"]
        assert 0.05 < diff < 0.30, (
            f"Capacity difference={diff}, expected 0.05-0.30 Ah (from 0.135 Ah loss)"
        )

    def test_capacity_difference_consistency(self, results):
        d = results["discharge"]
        expected = d["pristine_capacity_ah"] - d["degraded_capacity_ah"]
        assert abs(d["capacity_difference_ah"] - expected) < 0.01, (
            f"capacity_difference_ah={d['capacity_difference_ah']}, "
            f"but pristine-degraded={expected}"
        )

    def test_pristine_energy_range(self, results):
        e = results["discharge"]["pristine_energy_wh"]
        assert 14 < e < 22, f"Pristine energy={e} Wh, expected 14-22 Wh"

    def test_degraded_energy_range(self, results):
        e = results["discharge"]["degraded_energy_wh"]
        assert 13 < e < 21, f"Degraded energy={e} Wh, expected 13-21 Wh"

    def test_pristine_energy_greater(self, results):
        d = results["discharge"]
        assert d["pristine_energy_wh"] > d["degraded_energy_wh"], (
            "Pristine energy must exceed degraded energy"
        )

    def test_energy_capacity_ratio(self, results):
        d = results["discharge"]
        avg_v = d["pristine_energy_wh"] / d["pristine_capacity_ah"]
        assert 3.0 < avg_v < 4.0, (
            f"Avg discharge voltage={avg_v} V, expected 3.0-4.0 V"
        )


# ── Degradation Trajectory Tests ─────────────────────────────────────

class TestTrajectoryStructure:
    """Verify the degradation_trajectory section has the right structure."""

    def test_trajectory_key_exists(self, results):
        assert "degradation_trajectory" in results

    def test_all_trajectory_keys_present(self, results):
        dt = results["degradation_trajectory"]
        required = [
            "stage1_rpt_ah",
            "stage2_rpt_ah",
            "stage1_retention_pct",
            "stage2_retention_pct",
            "stage1_sei_nm",
            "stage2_sei_nm",
            "capacity_fade_per_stage_pct",
        ]
        for key in required:
            assert key in dt, f"Missing key: degradation_trajectory.{key}"

    def test_all_trajectory_values_numeric(self, results):
        dt = results["degradation_trajectory"]
        for key, val in dt.items():
            assert isinstance(val, (int, float)), (
                f"degradation_trajectory.{key} should be numeric, got {type(val)}"
            )
            assert not math.isnan(val), f"degradation_trajectory.{key} is NaN"
            assert not math.isinf(val), f"degradation_trajectory.{key} is infinite"


class TestTrajectoryPhysics:
    """Verify degradation trajectory results satisfy physical constraints."""

    def test_stage1_rpt_range(self, results):
        cap = results["degradation_trajectory"]["stage1_rpt_ah"]
        assert 3.0 < cap < 5.5, f"Stage 1 RPT capacity={cap}, expected 3.0-5.5 Ah"

    def test_stage2_rpt_range(self, results):
        cap = results["degradation_trajectory"]["stage2_rpt_ah"]
        assert 3.0 < cap < 5.5, f"Stage 2 RPT capacity={cap}, expected 3.0-5.5 Ah"

    def test_stage1_less_than_pristine(self, results):
        stage1 = results["degradation_trajectory"]["stage1_rpt_ah"]
        pristine = results["discharge"]["pristine_capacity_ah"]
        assert stage1 < pristine, (
            f"Stage 1 RPT ({stage1}) should be less than pristine ({pristine})"
        )

    def test_stage2_leq_stage1(self, results):
        dt = results["degradation_trajectory"]
        assert dt["stage2_rpt_ah"] <= dt["stage1_rpt_ah"] * 1.01, (
            f"Stage 2 RPT ({dt['stage2_rpt_ah']}) should not exceed "
            f"Stage 1 RPT ({dt['stage1_rpt_ah']})"
        )

    def test_stage1_retention_range(self, results):
        ret = results["degradation_trajectory"]["stage1_retention_pct"]
        assert 85 < ret < 102, (
            f"Stage 1 retention={ret}%, expected 85-102%"
        )

    def test_stage2_retention_range(self, results):
        ret = results["degradation_trajectory"]["stage2_retention_pct"]
        assert 80 < ret < 102, (
            f"Stage 2 retention={ret}%, expected 80-102%"
        )

    def test_stage2_retention_leq_stage1(self, results):
        dt = results["degradation_trajectory"]
        assert dt["stage2_retention_pct"] <= dt["stage1_retention_pct"] * 1.01, (
            f"Stage 2 retention ({dt['stage2_retention_pct']:.2f}%) should not exceed "
            f"Stage 1 retention ({dt['stage1_retention_pct']:.2f}%)"
        )

    def test_retention_consistency_stage1(self, results):
        dt = results["degradation_trajectory"]
        degraded_cap = results["discharge"]["degraded_capacity_ah"]
        expected = dt["stage1_rpt_ah"] / degraded_cap * 100
        assert abs(dt["stage1_retention_pct"] - expected) < 1.5, (
            f"Stage 1 retention={dt['stage1_retention_pct']:.2f}%, "
            f"computed={expected:.1f}%"
        )

    def test_retention_consistency_stage2(self, results):
        dt = results["degradation_trajectory"]
        degraded_cap = results["discharge"]["degraded_capacity_ah"]
        expected = dt["stage2_rpt_ah"] / degraded_cap * 100
        assert abs(dt["stage2_retention_pct"] - expected) < 1.5, (
            f"Stage 2 retention={dt['stage2_retention_pct']:.2f}%, "
            f"computed={expected:.1f}%"
        )

    def test_stage2_sei_geq_stage1_sei(self, results):
        dt = results["degradation_trajectory"]
        assert dt["stage2_sei_nm"] >= dt["stage1_sei_nm"] * 0.99, (
            f"Stage 2 SEI ({dt['stage2_sei_nm']:.2f}) should be >= "
            f"Stage 1 SEI ({dt['stage1_sei_nm']:.2f})"
        )

    def test_stage1_sei_range(self, results):
        val = results["degradation_trajectory"]["stage1_sei_nm"]
        assert 50 < val < 500, (
            f"Stage 1 SEI thickness={val} nm, expected 50-500 nm"
        )

    def test_stage2_sei_range(self, results):
        val = results["degradation_trajectory"]["stage2_sei_nm"]
        assert 50 < val < 500, (
            f"Stage 2 SEI thickness={val} nm, expected 50-500 nm"
        )

    def test_sei_grew_from_formation(self, results):
        formation_sei = results["formation"]["sei_thickness_nm"]
        stage1_sei = results["degradation_trajectory"]["stage1_sei_nm"]
        assert stage1_sei >= formation_sei, (
            f"Stage 1 SEI ({stage1_sei}) should be >= "
            f"formation SEI ({formation_sei})"
        )

    def test_capacity_fade_per_stage_value(self, results):
        dt = results["degradation_trajectory"]
        expected = (dt["stage1_rpt_ah"] - dt["stage2_rpt_ah"]) / dt["stage1_rpt_ah"] * 100
        assert abs(dt["capacity_fade_per_stage_pct"] - expected) < 0.5, (
            f"capacity_fade_per_stage_pct={dt['capacity_fade_per_stage_pct']:.4f}%, "
            f"computed={expected:.4f}%"
        )

    def test_capacity_fade_non_negative(self, results):
        assert results["degradation_trajectory"]["capacity_fade_per_stage_pct"] >= -0.5, (
            "Capacity fade per stage should be non-negative"
        )


# ── Sensitivity Sweep Tests ─────────────────────────────────────────

class TestSensitivityStructure:
    """Verify the sensitivity section exists and has the right keys."""

    def test_sensitivity_key_exists(self, results):
        assert "sensitivity" in results

    def test_all_sensitivity_keys_present(self, results):
        s = results["sensitivity"]
        required = [
            "retention_1e-14",
            "retention_1e-13",
            "retention_1e-12",
            "sei_growth_nm_1e-14",
            "sei_growth_nm_1e-13",
            "sei_growth_nm_1e-12",
        ]
        for key in required:
            assert key in s, f"Missing key: sensitivity.{key}"

    def test_all_sensitivity_values_numeric(self, results):
        s = results["sensitivity"]
        for key, val in s.items():
            assert isinstance(val, (int, float)), (
                f"sensitivity.{key} should be numeric, got {type(val)}"
            )
            assert not math.isnan(val), f"sensitivity.{key} is NaN"
            assert not math.isinf(val), f"sensitivity.{key} is infinite"


class TestSensitivityPhysics:
    """Verify sensitivity results satisfy physical constraints."""

    def test_retention_monotonically_decreasing(self, results):
        s = results["sensitivity"]
        assert s["retention_1e-14"] >= s["retention_1e-13"], (
            f"Retention should decrease with k: "
            f"1e-14={s['retention_1e-14']:.2f}% vs 1e-13={s['retention_1e-13']:.2f}%"
        )
        assert s["retention_1e-13"] >= s["retention_1e-12"], (
            f"Retention should decrease with k: "
            f"1e-13={s['retention_1e-13']:.2f}% vs 1e-12={s['retention_1e-12']:.2f}%"
        )

    def test_sei_growth_monotonically_increasing(self, results):
        s = results["sensitivity"]
        assert s["sei_growth_nm_1e-14"] <= s["sei_growth_nm_1e-13"] + 0.1, (
            f"SEI growth should increase with k: "
            f"1e-14={s['sei_growth_nm_1e-14']:.2f} vs 1e-13={s['sei_growth_nm_1e-13']:.2f}"
        )
        assert s["sei_growth_nm_1e-13"] <= s["sei_growth_nm_1e-12"] + 0.1, (
            f"SEI growth should increase with k: "
            f"1e-13={s['sei_growth_nm_1e-13']:.2f} vs 1e-12={s['sei_growth_nm_1e-12']:.2f}"
        )

    def test_all_retentions_physically_reasonable(self, results):
        s = results["sensitivity"]
        for k_str in ["1e-14", "1e-13", "1e-12"]:
            key = f"retention_{k_str}"
            val = s[key]
            assert 50 < val <= 101, f"{key}={val}%, expected 50-101%"

    def test_low_k_nearly_no_degradation(self, results):
        ret = results["sensitivity"]["retention_1e-14"]
        assert ret > 97, (
            f"At k=1e-14, retention should be >97%, got {ret:.2f}%"
        )

    def test_low_k_bounded_sei_growth(self, results):
        growth = results["sensitivity"]["sei_growth_nm_1e-14"]
        assert growth < 120.0, (
            f"At k=1e-14, SEI growth should be <120 nm, got {growth:.2f} nm"
        )

    def test_all_sei_growth_non_negative(self, results):
        s = results["sensitivity"]
        for k_str in ["1e-14", "1e-13", "1e-12"]:
            key = f"sei_growth_nm_{k_str}"
            val = s[key]
            assert val >= -0.5, f"{key}={val:.2f} nm, should be non-negative"

    def test_high_k_significant_sei_growth(self, results):
        growth = results["sensitivity"]["sei_growth_nm_1e-12"]
        assert growth > 0.5, (
            f"At k=1e-12, SEI growth should be >0.5 nm, got {growth:.2f} nm"
        )

    def test_spread_between_extremes(self, results):
        s = results["sensitivity"]
        ret_spread = s["retention_1e-14"] - s["retention_1e-12"]
        assert ret_spread > 0.1, (
            f"Retention spread between k=1e-14 and k=1e-12 should be >0.1%, "
            f"got {ret_spread:.4f}%"
        )


# ── Cross-section Consistency ─────────────────────────────────────────

class TestCrossSectionConsistency:
    """Verify consistency across all four analysis sections."""

    def test_degradation_chain(self, results):
        """Pristine > Degraded >= Stage 1 RPT >= Stage 2 RPT."""
        pristine = results["discharge"]["pristine_capacity_ah"]
        degraded = results["discharge"]["degraded_capacity_ah"]
        stage1 = results["degradation_trajectory"]["stage1_rpt_ah"]
        stage2 = results["degradation_trajectory"]["stage2_rpt_ah"]
        assert pristine > degraded, "Pristine must exceed degraded"
        assert stage1 < degraded * 1.02, (
            f"Stage 1 RPT ({stage1}) should not significantly exceed "
            f"degraded ({degraded})"
        )
        assert stage2 <= stage1 * 1.01, (
            f"Stage 2 RPT ({stage2}) should not exceed Stage 1 RPT ({stage1})"
        )

    def test_sei_thickness_chain(self, results):
        """SEI: formation <= stage1 <= stage2."""
        formation_sei = results["formation"]["sei_thickness_nm"]
        stage1_sei = results["degradation_trajectory"]["stage1_sei_nm"]
        stage2_sei = results["degradation_trajectory"]["stage2_sei_nm"]
        assert stage1_sei >= formation_sei * 0.99, (
            f"Stage 1 SEI ({stage1_sei}) should be >= formation ({formation_sei})"
        )
        assert stage2_sei >= stage1_sei * 0.99, (
            f"Stage 2 SEI ({stage2_sei}) should be >= Stage 1 ({stage1_sei})"
        )

    def test_sensitivity_1e13_matches_stage1_retention(self, results):
        """retention_1e-13 must be consistent with stage1_retention_pct."""
        sens_ret = results["sensitivity"]["retention_1e-13"]
        stage1_ret = results["degradation_trajectory"]["stage1_retention_pct"]
        assert abs(sens_ret - stage1_ret) < 2.0, (
            f"sensitivity.retention_1e-13={sens_ret:.2f}% should match "
            f"degradation_trajectory.stage1_retention_pct={stage1_ret:.2f}%"
        )

    def test_sensitivity_1e13_matches_stage1_sei_growth(self, results):
        """sei_growth_nm_1e-13 must be consistent with stage1 SEI growth."""
        sens_growth = results["sensitivity"]["sei_growth_nm_1e-13"]
        stage1_growth = (
            results["degradation_trajectory"]["stage1_sei_nm"]
            - results["formation"]["sei_thickness_nm"]
        )
        assert abs(sens_growth - stage1_growth) < 3.0, (
            f"sensitivity.sei_growth_nm_1e-13={sens_growth:.2f} nm should match "
            f"stage1 growth={stage1_growth:.2f} nm"
        )

    def test_overall_result_structure(self, results):
        """Top-level keys must be exactly formation, discharge,
        degradation_trajectory, sensitivity."""
        assert set(results.keys()) == {
            "formation", "discharge", "degradation_trajectory", "sensitivity"
        }
