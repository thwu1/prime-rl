
import subprocess
import csv
import json
import os
import math
import pytest


@pytest.fixture(scope="module")
def simulation_output():
    """Run the R simulation once and return parsed CSV rows."""
    result = subprocess.run(
        ["Rscript", "/app/run_simulation.R"],
        capture_output=True, text=True, timeout=180
    )
    assert result.returncode == 0, (
        f"Simulation failed with exit code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    assert os.path.exists("/app/results.csv"), "results.csv not created"

    with open("/app/results.csv") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    return rows


@pytest.fixture(scope="module")
def model_params():
    """Run parameter validation R script and return parsed JSON."""
    result = subprocess.run(
        ["Rscript", "/tests/validate_params.R"],
        capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, (
        f"Parameter validation R script failed.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return json.loads(result.stdout.strip())


# ============================================================
# Output format and structure tests
# ============================================================

class TestOutputFormat:
    def test_results_file_exists(self, simulation_output):
        assert os.path.exists("/app/results.csv")

    def test_csv_columns(self, simulation_output):
        with open("/app/results.csv") as f:
            reader = csv.DictReader(f)
            cols = set(reader.fieldnames)
        expected = {"scenario_id", "time_min", "plasma_conc", "effect_conc", "infusion_rate"}
        assert cols == expected, f"Expected columns {expected}, got {cols}"

    def test_total_row_count(self, simulation_output):
        assert len(simulation_output) == 384, (
            f"Expected 384 rows (96 per scenario x 4), got {len(simulation_output)}"
        )

    def test_scenario_row_counts(self, simulation_output):
        for sid in ["1", "2", "3", "4"]:
            rows = [r for r in simulation_output if r["scenario_id"] == sid]
            assert len(rows) == 96, (
                f"Scenario {sid}: expected 96 rows, got {len(rows)}"
            )

    def test_non_negative_concentrations(self, simulation_output):
        for i, row in enumerate(simulation_output):
            cp = float(row["plasma_conc"])
            ce = float(row["effect_conc"])
            ir = float(row["infusion_rate"])
            assert cp >= -1e-10, f"Row {i}: negative plasma_conc={cp}"
            assert ce >= -1e-10, f"Row {i}: negative effect_conc={ce}"
            assert ir >= -1e-10, f"Row {i}: negative infusion_rate={ir}"

    def test_no_nan_or_inf(self, simulation_output):
        for i, row in enumerate(simulation_output):
            for col in ["plasma_conc", "effect_conc", "infusion_rate"]:
                val = float(row[col])
                assert math.isfinite(val), f"Row {i}: {col}={val} is not finite"


# ============================================================
# Model parameter validation tests
# ============================================================

class TestModelParameters:
    def test_james_lbm_male(self, model_params):
        """James LBM for 170cm, 70kg male should be ~55.30"""
        val = model_params["lbm_male_170_70"]
        assert abs(val - 55.30) < 0.5, (
            f"James LBM male (170cm, 70kg): got {val:.3f}, expected ~55.30"
        )

    def test_james_lbm_female(self, model_params):
        """James LBM for 155cm, 55kg female should be ~40.22 (not ~45.72)"""
        val = model_params["lbm_female_155_55"]
        assert abs(val - 40.22) < 0.5, (
            f"James LBM female (155cm, 55kg): got {val:.3f}, expected ~40.22. "
            f"Check the female coefficient in the James formula."
        )

    def test_schnider_v1_constant(self, model_params):
        """Schnider V1 is always 4.27 L"""
        assert abs(model_params["schnider_v1"] - 4.27) < 0.01

    def test_schnider_v2(self, model_params):
        """Schnider V2 for age=40: 18.9 - 0.391*(40-53) = 23.983"""
        val = model_params["schnider_v2"]
        assert abs(val - 23.983) < 0.01, (
            f"Schnider V2 for age=40: got {val:.4f}, expected 23.983"
        )

    def test_schnider_k21_uses_v2(self, model_params):
        """Schnider k21 = Cl2/V2. For age=40: ~0.0668 (NOT Cl2/V1 ~0.375)"""
        val = model_params["schnider_k21"]
        assert val < 0.12, (
            f"Schnider k21: got {val:.4f}, expected ~0.067. "
            f"k21 should use V2 as denominator, not V1."
        )
        assert abs(val - 0.0668) < 0.005, (
            f"Schnider k21: got {val:.4f}, expected ~0.0668"
        )

    def test_marsh_v1(self, model_params):
        """Marsh V1 for 70kg = 0.228 * 70 = 15.96"""
        assert abs(model_params["marsh_v1"] - 15.96) < 0.01

    def test_marsh_k10(self, model_params):
        """Marsh k10 is constant at 0.119"""
        assert abs(model_params["marsh_k10"] - 0.119) < 0.001

    def test_eleveld_female_clearance_higher(self, model_params):
        """Eleveld female clearance should be higher than male at reference point.
        Female uses theta15=2.10, male uses theta4=1.79."""
        k10_f = model_params["eleveld_female_k10"]
        k10_m = model_params["eleveld_male_k10"]
        assert k10_f > k10_m * 1.10, (
            f"Eleveld female k10={k10_f:.4f} should be >10% higher than "
            f"male k10={k10_m:.4f}. Check sex-dependent clearance."
        )

    def test_eleveld_female_k10_value(self, model_params):
        """At reference (35, 70, 170, female): k10 = theta15/V1 = 2.10/6.28 ≈ 0.3344"""
        val = model_params["eleveld_female_k10"]
        assert val > 0.30, (
            f"Eleveld female k10={val:.4f}, expected >0.30. "
            f"Female clearance should use a different theta than male."
        )

    def test_minto_ke0(self, model_params):
        """Minto ke0 for age=50: 0.595 - 0.007*(50-40) = 0.525"""
        val = model_params["minto_ke0"]
        assert abs(val - 0.525) < 0.01, (
            f"Minto ke0 for age=50: got {val:.4f}, expected 0.525. "
            f"Check the covariate reference age in the ke0 formula."
        )

    def test_minto_v1(self, model_params):
        """Minto V1 for (50, 65, 165, f) with correct LBM"""
        val = model_params["minto_v1"]
        assert val > 3.5 and val < 5.5, (
            f"Minto V1={val:.3f} outside expected range [3.5, 5.5]"
        )


# ============================================================
# TCI convergence tests
# ============================================================

def _get_scenario_rows(simulation_output, scenario_id):
    """Extract rows for a given scenario, sorted by time."""
    rows = [r for r in simulation_output if r["scenario_id"] == str(scenario_id)]
    rows.sort(key=lambda r: float(r["time_min"]))
    return rows


def _check_convergence(rows, t_start, t_end, target, tolerance=0.05):
    """Check that Ce is within tolerance of target for all rows in [t_start, t_end]."""
    checked = []
    for r in rows:
        t = float(r["time_min"])
        if t_start <= t <= t_end:
            ce = float(r["effect_conc"])
            checked.append((t, ce))

    assert len(checked) > 0, (
        f"No data points found in [{t_start}, {t_end}]"
    )

    violations = []
    for t, ce in checked:
        pct_err = abs(ce - target) / target
        if pct_err > tolerance:
            violations.append((t, ce, pct_err))

    assert len(violations) == 0, (
        f"Ce not within {tolerance*100}% of target {target} at "
        f"{len(violations)}/{len(checked)} time points. "
        f"Worst: t={violations[0][0]:.2f} Ce={violations[0][1]:.4f} "
        f"err={violations[0][2]*100:.1f}%"
    )


class TestConvergence:
    def test_scenario1_segment1(self, simulation_output):
        """Schnider: Ce should converge to 4.0 by t=5-7.9"""
        rows = _get_scenario_rows(simulation_output, 1)
        _check_convergence(rows, 5.0, 7.9, target=4.0)

    def test_scenario1_segment2(self, simulation_output):
        """Schnider: Ce should converge to 3.0 by t=13-16"""
        rows = _get_scenario_rows(simulation_output, 1)
        _check_convergence(rows, 13.0, 16.0, target=3.0)

    def test_scenario2_early(self, simulation_output):
        """Eleveld female: Ce should converge to 3.5 by t=5-7.9"""
        rows = _get_scenario_rows(simulation_output, 2)
        _check_convergence(rows, 5.0, 7.9, target=3.5)

    def test_scenario2_late(self, simulation_output):
        """Eleveld female: Ce should stay at 3.5 through t=13-16"""
        rows = _get_scenario_rows(simulation_output, 2)
        _check_convergence(rows, 13.0, 16.0, target=3.5)

    def test_scenario3_segment1(self, simulation_output):
        """Eleveld male+opiates: Ce should converge to 3.0 by t=5-7.9"""
        rows = _get_scenario_rows(simulation_output, 3)
        _check_convergence(rows, 5.0, 7.9, target=3.0)

    def test_scenario3_segment2(self, simulation_output):
        """Eleveld male+opiates: Ce should converge to 4.5 by t=13-16"""
        rows = _get_scenario_rows(simulation_output, 3)
        _check_convergence(rows, 13.0, 16.0, target=4.5)

    def test_scenario4_segment1(self, simulation_output):
        """Minto female: Ce should converge to 5.0 by t=5-7.9"""
        rows = _get_scenario_rows(simulation_output, 4)
        _check_convergence(rows, 5.0, 7.9, target=5.0)

    def test_scenario4_segment2(self, simulation_output):
        """Minto female: Ce should converge to 3.0 by t=13-16"""
        rows = _get_scenario_rows(simulation_output, 4)
        _check_convergence(rows, 13.0, 16.0, target=3.0)


# ============================================================
# TCI behavior tests
# ============================================================

class TestTCIBehavior:
    def test_initial_concentrations_near_zero(self, simulation_output):
        """At t near 0, concentrations should start from zero."""
        for sid in [1, 2, 3, 4]:
            rows = _get_scenario_rows(simulation_output, sid)
            first = rows[0]
            ce = float(first["effect_conc"])
            assert ce < 1.0, (
                f"Scenario {sid}: first Ce={ce:.3f} too high (should start near 0)"
            )

    def test_infusion_rate_positive_during_induction(self, simulation_output):
        """During the first few steps, infusion rate should be positive."""
        for sid in [1, 2, 3, 4]:
            rows = _get_scenario_rows(simulation_output, sid)
            early_rates = [float(r["infusion_rate"]) for r in rows[:6]]
            total_early = sum(early_rates)
            assert total_early > 0, (
                f"Scenario {sid}: no infusion during first minute"
            )

    def test_plasma_overshoots_for_effect_targeting(self, simulation_output):
        """Effect-site targeting should produce plasma overshoot above target."""
        for sid in [1, 2, 3, 4]:
            rows = _get_scenario_rows(simulation_output, sid)
            # Get the first target
            targets = {1: 4.0, 2: 3.5, 3: 3.0, 4: 5.0}
            target = targets[sid]
            # Check that Cp exceeds target at some early point
            early_cp = [float(r["plasma_conc"]) for r in rows[:18]]
            max_cp = max(early_cp)
            assert max_cp > target * 1.05, (
                f"Scenario {sid}: max early Cp={max_cp:.3f} does not overshoot "
                f"target {target}. Effect-site targeting should overshoot plasma."
            )
