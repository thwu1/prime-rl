"""
Verify cell electrode balancing analysis results.
"""

import json
import os
import pytest
import numpy as np


@pytest.fixture
def results():
    assert os.path.exists("/app/results.json"), "results.json not found at /app/results.json"
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture
def config():
    with open("/app/cell_config.json") as f:
        return json.load(f)


def _valid_analyses(results):
    return [a for a in results["analyses"] if "error" not in a]


def _safe_scalar(val):
    """Convert a potentially multi-dimensional array value to a Python float."""
    a = np.asarray(val, dtype=float)
    if a.ndim == 0:
        return float(a)
    if a.size == 1:
        return float(a.flat[0])
    return float(np.mean(a))


# ── Structure ──────────────────────────────────────────────────────────


class TestResultStructure:
    def test_base_parameters_present(self, results):
        bp = results["base_parameters"]
        for key in [
            "negative_electrode_thickness_m",
            "positive_electrode_thickness_m",
            "nominal_cell_capacity_Ah",
        ]:
            assert key in bp, f"Missing base parameter: {key}"
            assert isinstance(bp[key], (int, float)), f"{key} is not numeric"
            assert bp[key] > 0, f"{key} must be positive"

    def test_analyses_count(self, results, config):
        mults = config["negative_electrode_thickness_multipliers"]
        valid = _valid_analyses(results)
        assert len(valid) >= len(mults) - 1, (
            f"Expected at least {len(mults) - 1} valid analyses, got {len(valid)}"
        )

    def test_analysis_required_fields(self, results):
        required = {
            "thickness_multiplier": (int, float),
            "discharge_capacity_Ah": (int, float),
            "discharge_energy_Wh": (int, float),
            "average_voltage_V": (int, float),
            "neg_stoich_at_soc100": (int, float),
            "neg_stoich_at_soc0": (int, float),
            "pos_stoich_at_soc100": (int, float),
            "pos_stoich_at_soc0": (int, float),
            "plating_risk": bool,
            "limiting_electrode": str,
        }
        for a in _valid_analyses(results):
            for field, ftype in required.items():
                assert field in a, (
                    f"Missing field '{field}' at multiplier={a.get('thickness_multiplier')}"
                )
                assert isinstance(a[field], ftype), (
                    f"Wrong type for '{field}': expected {ftype.__name__}, "
                    f"got {type(a[field]).__name__}"
                )

    def test_optimal_fields_present(self, results):
        assert "optimal_multiplier" in results
        assert "max_safe_discharge_capacity_Ah" in results


# ── Physical bounds ────────────────────────────────────────────────────


class TestPhysicalBounds:
    def test_capacity_range(self, results):
        for a in _valid_analyses(results):
            assert 0.5 < a["discharge_capacity_Ah"] < 10.0, (
                f"Capacity {a['discharge_capacity_Ah']:.3f} Ah out of plausible range "
                f"at multiplier={a['thickness_multiplier']}"
            )

    def test_energy_range(self, results):
        for a in _valid_analyses(results):
            assert 0.5 < a["discharge_energy_Wh"] < 50.0, (
                f"Energy {a['discharge_energy_Wh']:.3f} Wh out of range"
            )

    def test_voltage_range(self, results, config):
        v_lo, v_hi = config["voltage_limits_V"]
        for a in _valid_analyses(results):
            assert v_lo - 0.1 <= a["average_voltage_V"] <= v_hi + 0.1, (
                f"Average voltage {a['average_voltage_V']:.3f} V outside [{v_lo}, {v_hi}]"
            )

    def test_stoichiometry_in_unit_interval(self, results):
        sto_keys = [
            "neg_stoich_at_soc100",
            "neg_stoich_at_soc0",
            "pos_stoich_at_soc100",
            "pos_stoich_at_soc0",
        ]
        for a in _valid_analyses(results):
            for key in sto_keys:
                assert -0.01 <= a[key] <= 1.01, (
                    f"{key}={a[key]:.4f} outside [0,1] at mult={a['thickness_multiplier']}"
                )

    def test_stoichiometry_discharge_direction(self, results):
        """Neg stoichiometry decreases during discharge; pos increases."""
        for a in _valid_analyses(results):
            assert a["neg_stoich_at_soc100"] > a["neg_stoich_at_soc0"], (
                f"Neg stoich should decrease during discharge: "
                f"soc100={a['neg_stoich_at_soc100']:.4f} <= "
                f"soc0={a['neg_stoich_at_soc0']:.4f}"
            )
            assert a["pos_stoich_at_soc100"] < a["pos_stoich_at_soc0"], (
                f"Pos stoich should increase during discharge: "
                f"soc100={a['pos_stoich_at_soc100']:.4f} >= "
                f"soc0={a['pos_stoich_at_soc0']:.4f}"
            )

    def test_limiting_electrode_values(self, results):
        for a in _valid_analyses(results):
            assert a["limiting_electrode"] in ("positive", "negative"), (
                f"limiting_electrode must be 'positive' or 'negative', "
                f"got '{a['limiting_electrode']}'"
            )


# ── Physical consistency ──────────────────────────────────────────────


class TestPhysicalConsistency:
    def test_neg_stoich_soc100_decreases_with_thickness(self, results):
        """Thicker negative electrode -> lower stoichiometry at full charge."""
        analyses = sorted(_valid_analyses(results), key=lambda x: x["thickness_multiplier"])
        if len(analyses) < 2:
            pytest.skip("Not enough valid analyses for monotonicity check")
        for i in range(len(analyses) - 1):
            assert analyses[i]["neg_stoich_at_soc100"] >= (
                analyses[i + 1]["neg_stoich_at_soc100"] - 0.02
            ), (
                f"neg_stoich_at_soc100 should decrease with multiplier: "
                f"mult={analyses[i]['thickness_multiplier']} has "
                f"{analyses[i]['neg_stoich_at_soc100']:.4f}, "
                f"mult={analyses[i+1]['thickness_multiplier']} has "
                f"{analyses[i+1]['neg_stoich_at_soc100']:.4f}"
            )

    def test_plating_risk_monotonic(self, results):
        """Once plating risk is False at some multiplier, it stays False for all higher."""
        analyses = sorted(_valid_analyses(results), key=lambda x: x["thickness_multiplier"])
        found_safe = False
        for a in analyses:
            if not a["plating_risk"]:
                found_safe = True
            elif found_safe:
                pytest.fail(
                    f"Plating risk reappeared at mult={a['thickness_multiplier']} "
                    f"after being safe at a lower multiplier"
                )

    def test_plating_risk_matches_stoichiometry(self, results, config):
        """Plating risk must be consistent with stoichiometry vs threshold."""
        margin = config["plating_stoichiometry_safety_margin"]
        threshold = 1.0 - margin
        for a in _valid_analyses(results):
            if a["plating_risk"]:
                assert a["neg_stoich_at_soc100"] > threshold - 0.02, (
                    f"Plating risk flagged but stoich "
                    f"{a['neg_stoich_at_soc100']:.4f} well below "
                    f"threshold {threshold:.2f}"
                )
            else:
                assert a["neg_stoich_at_soc100"] <= threshold + 0.02, (
                    f"No plating risk but stoich "
                    f"{a['neg_stoich_at_soc100']:.4f} above "
                    f"threshold {threshold:.2f}"
                )

    def test_limiting_electrode_consistent_with_stoichiometry(self, results):
        """Limiting electrode should match which stoich is nearer its extreme."""
        for a in _valid_analyses(results):
            neg_margin = a["neg_stoich_at_soc0"]  # distance from 0
            pos_margin = 1.0 - a["pos_stoich_at_soc0"]  # distance from 1
            if neg_margin < pos_margin - 0.05:
                assert a["limiting_electrode"] == "negative", (
                    f"Neg stoich {a['neg_stoich_at_soc0']:.4f} closer to 0 than "
                    f"pos stoich {a['pos_stoich_at_soc0']:.4f} to 1, "
                    f"but marked '{a['limiting_electrode']}'"
                )
            elif pos_margin < neg_margin - 0.05:
                assert a["limiting_electrode"] == "positive", (
                    f"Pos stoich {a['pos_stoich_at_soc0']:.4f} closer to 1 than "
                    f"neg stoich {a['neg_stoich_at_soc0']:.4f} to 0, "
                    f"but marked '{a['limiting_electrode']}'"
                )
            # If margins are within 0.05 of each other, either answer is acceptable

    def test_energy_capacity_voltage_selfconsistent(self, results):
        """Energy should approximately equal capacity * average_voltage."""
        for a in _valid_analyses(results):
            expected = a["discharge_capacity_Ah"] * a["average_voltage_V"]
            if expected > 0:
                rel_err = abs(a["discharge_energy_Wh"] - expected) / expected
                assert rel_err < 0.15, (
                    f"Energy-voltage inconsistency at mult={a['thickness_multiplier']}: "
                    f"energy={a['discharge_energy_Wh']:.3f} Wh, "
                    f"cap*V={expected:.3f} Wh, "
                    f"relative error={rel_err:.1%}"
                )


# ── Optimal selection ─────────────────────────────────────────────────


class TestOptimalSelection:
    def test_at_least_one_safe(self, results):
        """At least one configuration (high multiplier) should be safe."""
        safe = [a for a in _valid_analyses(results) if not a["plating_risk"]]
        assert len(safe) >= 1, "No safe configuration found; expect at least one"

    def test_optimal_exists_when_safe_exists(self, results):
        safe = [a for a in _valid_analyses(results) if not a["plating_risk"]]
        if len(safe) > 0:
            assert results["optimal_multiplier"] is not None, (
                "Safe configurations exist but optimal_multiplier is None"
            )

    def test_optimal_is_valid_multiplier(self, results, config):
        if results["optimal_multiplier"] is None:
            pytest.skip("No optimal multiplier")
        assert results["optimal_multiplier"] in config["negative_electrode_thickness_multipliers"]

    def test_optimal_is_safe(self, results):
        if results["optimal_multiplier"] is None:
            pytest.skip("No optimal multiplier")
        opt = next(
            a for a in _valid_analyses(results)
            if abs(a["thickness_multiplier"] - results["optimal_multiplier"]) < 1e-6
        )
        assert not opt["plating_risk"], "Optimal configuration must not have plating risk"

    def test_optimal_has_max_safe_capacity(self, results):
        if results["optimal_multiplier"] is None:
            pytest.skip("No optimal multiplier")
        safe = [a for a in _valid_analyses(results) if not a["plating_risk"]]
        max_cap = max(a["discharge_capacity_Ah"] for a in safe)
        opt = next(
            a for a in _valid_analyses(results)
            if abs(a["thickness_multiplier"] - results["optimal_multiplier"]) < 1e-6
        )
        assert abs(opt["discharge_capacity_Ah"] - max_cap) < 0.05, (
            f"Optimal capacity {opt['discharge_capacity_Ah']:.4f} != "
            f"max safe capacity {max_cap:.4f}"
        )

    def test_max_safe_capacity_matches_optimal(self, results):
        if results["optimal_multiplier"] is None:
            pytest.skip("No optimal multiplier")
        opt = next(
            a for a in _valid_analyses(results)
            if abs(a["thickness_multiplier"] - results["optimal_multiplier"]) < 1e-6
        )
        assert abs(
            results["max_safe_discharge_capacity_Ah"] - opt["discharge_capacity_Ah"]
        ) < 0.05, (
            f"max_safe_discharge_capacity_Ah "
            f"{results['max_safe_discharge_capacity_Ah']:.4f} != "
            f"optimal capacity {opt['discharge_capacity_Ah']:.4f}"
        )


# ── Independent verification ─────────────────────────────────────────


class TestReferenceSimulation:
    def test_independent_discharge_at_baseline(self, results):
        """Run independent PyBaMM simulation at multiplier=1.0 and compare."""
        import pybamm

        ref = None
        for a in _valid_analyses(results):
            if abs(a["thickness_multiplier"] - 1.0) < 0.01:
                ref = a
                break
        if ref is None:
            pytest.skip("No analysis at multiplier=1.0")

        model = pybamm.lithium_ion.SPMe(options={"thermal": "lumped"})
        param = pybamm.ParameterValues("Chen2020")
        sim = pybamm.Simulation(model, parameter_values=param)
        sol = sim.solve([0, 7200], initial_soc=1.0)

        # Robustly extract scalar capacity handling potential multi-dim arrays
        try:
            ref_cap = _safe_scalar(sol["Discharge capacity [A.h]"](t=sol.t[-1]))
        except (TypeError, AttributeError, ValueError):
            ref_cap = _safe_scalar(
                np.asarray(sol["Discharge capacity [A.h]"].entries).flat[-1]
            )

        rel_err = abs(ref["discharge_capacity_Ah"] - ref_cap) / ref_cap
        assert rel_err < 0.10, (
            f"Capacity mismatch at baseline: "
            f"agent={ref['discharge_capacity_Ah']:.4f}, "
            f"reference={ref_cap:.4f}, "
            f"relative error={rel_err:.1%}"
        )

    def test_chen2020_baseline_capacity_plausible(self, results):
        """Chen2020 (LG M50) at 1C should deliver approximately 4-6 Ah."""
        for a in _valid_analyses(results):
            if abs(a["thickness_multiplier"] - 1.0) < 0.01:
                assert 3.5 < a["discharge_capacity_Ah"] < 6.5, (
                    f"Baseline capacity {a['discharge_capacity_Ah']:.3f} Ah "
                    f"far from expected ~5 Ah for Chen2020"
                )
                return
        pytest.skip("No baseline multiplier=1.0 analysis found")

    def test_base_electrode_thicknesses_plausible(self, results):
        """Chen2020 electrode thicknesses should be in the ~50-120 um range."""
        bp = results["base_parameters"]
        for key in ["negative_electrode_thickness_m", "positive_electrode_thickness_m"]:
            val_um = bp[key] * 1e6  # convert to micrometers
            assert 30 < val_um < 200, (
                f"{key} = {val_um:.1f} um is outside plausible range [30, 200] um"
            )
