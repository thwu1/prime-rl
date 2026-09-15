
"""Verification tests for the adaptive convection-diffusion solver.

Tests verify:
  - All 4 output files produced with valid convergence data
  - Residual norms below threshold
  - L2 errors below threshold (catches wrong discretization)
  - Combined iteration budget met
  - strategy.json exists with per-regime analysis
  - Strategy choices are consistent with physical regime
"""

import os
import json
import math
import pytest


def parse_output(path):
    """Parse key=value output file."""
    result = {}
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                key, value = line.split("=", 1)
                result[key.strip()] = value.strip()
    return result


# ---------- Output file existence and structure ----------

class TestOutputFiles:
    @pytest.mark.parametrize("cid", [1, 2, 3, 4])
    def test_output_exists(self, cid):
        path = f"/app/output_{cid}.txt"
        assert os.path.isfile(path), f"{path} not found"

    @pytest.mark.parametrize("cid", [1, 2, 3, 4])
    def test_output_has_required_fields(self, cid):
        data = parse_output(f"/app/output_{cid}.txt")
        for field in ("iterations", "residual_norm", "l2_error", "converged"):
            assert field in data, f"Config {cid}: missing field '{field}'"


# ---------- Convergence ----------

class TestConvergence:
    @pytest.mark.parametrize("cid", [1, 2, 3, 4])
    def test_solver_converged(self, cid):
        data = parse_output(f"/app/output_{cid}.txt")
        assert data["converged"] == "true", (
            f"Config {cid} did not converge"
        )

    @pytest.mark.parametrize("cid", [1, 2, 3, 4])
    def test_residual_norm(self, cid):
        data = parse_output(f"/app/output_{cid}.txt")
        r = float(data["residual_norm"])
        assert not math.isnan(r), f"Config {cid}: residual is NaN"
        assert not math.isinf(r), f"Config {cid}: residual is Inf"
        assert r < 1e-6, (
            f"Config {cid}: residual {r:.2e} exceeds 1e-6"
        )


# ---------- Solution accuracy (catches wrong discretization) ----------

class TestAccuracy:
    @pytest.mark.parametrize("cid", [1, 2, 3, 4])
    def test_l2_error(self, cid):
        data = parse_output(f"/app/output_{cid}.txt")
        e = float(data["l2_error"])
        assert not math.isnan(e), f"Config {cid}: L2 error is NaN"
        assert not math.isinf(e), f"Config {cid}: L2 error is Inf"
        assert e < 0.15, (
            f"Config {cid}: L2 error {e:.4f} exceeds 0.15. "
            "The discretization may be producing oscillatory solutions."
        )


# ---------- Performance budget ----------

class TestPerformance:
    def test_total_iteration_budget(self):
        total = 0
        for cid in [1, 2, 3, 4]:
            data = parse_output(f"/app/output_{cid}.txt")
            total += int(data["iterations"])
        assert total < 800, (
            f"Total iterations {total} exceeds budget of 800. "
            "Consider using more effective preconditioners."
        )


# ---------- Strategy documentation (evaluate/create requirement) ----------

class TestStrategy:
    def test_strategy_file_exists(self):
        assert os.path.isfile("/app/strategy.json"), (
            "Missing /app/strategy.json — must document per-regime analysis"
        )

    def test_strategy_valid_json(self):
        with open("/app/strategy.json") as f:
            data = json.load(f)
        assert "configurations" in data, (
            "strategy.json must have a 'configurations' key"
        )

    def test_strategy_covers_all_configs(self):
        with open("/app/strategy.json") as f:
            data = json.load(f)
        configs = data["configurations"]
        ids = {c["config_id"] for c in configs}
        assert ids == {1, 2, 3, 4}, (
            f"strategy.json covers configs {ids}, expected {{1,2,3,4}}"
        )

    def test_strategy_has_required_fields(self):
        with open("/app/strategy.json") as f:
            data = json.load(f)
        required = {
            "config_id", "grid_peclet_number", "discretization",
            "solver", "preconditioner", "rationale"
        }
        for cfg in data["configurations"]:
            missing = required - set(cfg.keys())
            assert not missing, (
                f"Config {cfg.get('config_id', '?')}: "
                f"strategy.json missing fields {missing}"
            )

    def test_convection_dominated_uses_upwind(self):
        """Configs with large Peclet number must NOT use central differences."""
        with open("/app/strategy.json") as f:
            data = json.load(f)
        for cfg in data["configurations"]:
            pe = float(cfg["grid_peclet_number"])
            disc = cfg["discretization"].lower()
            if pe > 2.0:
                assert "upwind" in disc, (
                    f"Config {cfg['config_id']}: Pe_h={pe:.1f} >> 1 "
                    f"but discretization is '{disc}'. "
                    "Convection-dominated regime requires upwind differencing."
                )

    def test_rationale_nonempty(self):
        """Each configuration must have a non-trivial rationale."""
        with open("/app/strategy.json") as f:
            data = json.load(f)
        for cfg in data["configurations"]:
            rat = cfg["rationale"].strip()
            assert len(rat) > 20, (
                f"Config {cfg['config_id']}: rationale too short "
                f"({len(rat)} chars). Provide meaningful justification."
            )
