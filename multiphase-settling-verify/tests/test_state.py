"""
Tests for the multiphase flow V&V pipeline report.
Verifies corrected physics results, historical run classifications,
convergence data export, and gnuplot script functionality.
"""

import json
import math
import os
import subprocess
import pytest


@pytest.fixture(scope="session")
def report():
    with open("/app/report.json") as f:
        return json.load(f)


# -----------------------------------------------------------------------
# Reference computations (independent of solution code)
# -----------------------------------------------------------------------

def _cd_ref(Re):
    """Correct Schiller-Naumann drag coefficient (exponent 0.687)."""
    if Re > 1000.0:
        return 0.44
    return (24.0 / Re) * (1.0 + 0.15 * Re ** 0.687)


def _terminal_vel():
    """Stokes terminal velocity for the configured particle."""
    return 9.81 * (2500.0 - 1000.0) * (1e-4) ** 2 / (18.0 * 0.001)


def _settling_front(eps_s0):
    """Correct settling front position at t=50s."""
    u_t = _terminal_vel()
    eps_g0 = 1.0 - eps_s0
    return 0.8 + (-u_t * eps_g0 ** (4.65 + 1)) * 50.0


def _filling_front(eps_s0):
    """Correct filling front position at t=50s."""
    u_t = _terminal_vel()
    eps_g0 = 1.0 - eps_s0
    return (u_t * eps_s0 * eps_g0 ** (4.65 + 1) / (0.63 - eps_s0)) * 50.0


def _find_front(report, eps_s0):
    """Find the front entry for a given concentration."""
    for fr in report["verification"]["settling"]["fronts"]:
        if abs(fr["eps_s0"] - eps_s0) < 1e-6:
            return fr
    pytest.fail(f"No front found for eps_s0={eps_s0}")


# -----------------------------------------------------------------------
# Drag verification tests
# -----------------------------------------------------------------------

class TestDragCoefficients:

    @pytest.mark.parametrize("Re", [0.1, 1.0, 10.0, 100.0, 1500.0])
    def test_drag_value(self, report, Re):
        actual = report["verification"]["drag"][f"Re_{Re}"]
        expected = _cd_ref(Re)
        if expected > 0:
            rel_err = abs(actual - expected) / expected
            assert rel_err < 0.005, (
                f"C_d(Re={Re}): got {actual:.6f}, want {expected:.6f}, "
                f"rel_err={rel_err:.4e}"
            )

    def test_drag_has_all_reynolds(self, report):
        drag = report["verification"]["drag"]
        for Re in [0.1, 1.0, 10.0, 100.0, 1500.0]:
            assert f"Re_{Re}" in drag, f"Missing Re_{Re}"

    def test_high_re_is_constant(self, report):
        cd = report["verification"]["drag"]["Re_1500.0"]
        assert abs(cd - 0.44) < 0.001, (
            f"C_d(Re=1500) should be 0.44, got {cd}"
        )

    def test_drag_monotonically_decreases(self, report):
        drag = report["verification"]["drag"]
        re_vals = sorted(float(k.split("_")[1]) for k in drag)
        cd_vals = [drag[f"Re_{r}"] for r in re_vals]
        for i in range(len(cd_vals) - 1):
            assert cd_vals[i] >= cd_vals[i + 1], (
                f"C_d must not increase: Re={re_vals[i]}->{cd_vals[i]}, "
                f"Re={re_vals[i+1]}->{cd_vals[i+1]}"
            )


# -----------------------------------------------------------------------
# Settling analysis tests
# -----------------------------------------------------------------------

class TestSettlingAnalysis:

    def test_terminal_velocity(self, report):
        actual = report["verification"]["settling"]["terminal_velocity"]
        expected = _terminal_vel()
        assert abs(actual - expected) / expected < 0.001

    def test_reynolds_number(self, report):
        u_t = _terminal_vel()
        expected_re = 1000.0 * u_t * 1e-4 / 0.001
        actual_re = report["verification"]["settling"]["reynolds_number"]
        assert abs(actual_re - expected_re) / expected_re < 0.001

    def test_stokes_regime(self, report):
        Re = report["verification"]["settling"]["reynolds_number"]
        assert 0 < Re < 1.0, f"Particle Re={Re} not in Stokes regime"

    @pytest.mark.parametrize("eps_s0", [0.05, 0.10, 0.20])
    def test_settling_front_position(self, report, eps_s0):
        expected = _settling_front(eps_s0)
        front = _find_front(report, eps_s0)
        assert abs(front["settling_front"] - expected) < 0.005, (
            f"Settling front eps_s={eps_s0}: got {front['settling_front']:.6f}, "
            f"want {expected:.6f}"
        )

    @pytest.mark.parametrize("eps_s0", [0.05, 0.10, 0.20])
    def test_filling_front_position(self, report, eps_s0):
        expected = _filling_front(eps_s0)
        front = _find_front(report, eps_s0)
        assert abs(front["filling_front"] - expected) < 0.003, (
            f"Filling front eps_s={eps_s0}: got {front['filling_front']:.6f}, "
            f"want {expected:.6f}"
        )

    @pytest.mark.parametrize("eps_s0", [0.05, 0.10, 0.20])
    def test_hindered_velocity(self, report, eps_s0):
        u_t = _terminal_vel()
        eps_g0 = 1.0 - eps_s0
        expected = u_t * eps_g0 ** 4.65
        front = _find_front(report, eps_s0)
        assert abs(front["hindered_velocity"] - expected) / expected < 0.005

    def test_three_concentrations(self, report):
        assert len(report["verification"]["settling"]["fronts"]) == 3

    def test_settling_above_filling(self, report):
        for fr in report["verification"]["settling"]["fronts"]:
            assert fr["settling_front"] > fr["filling_front"], (
                f"Settling front must be above filling at eps_s={fr['eps_s0']}"
            )

    def test_hindered_decreasing(self, report):
        fronts = sorted(
            report["verification"]["settling"]["fronts"],
            key=lambda f: f["eps_s0"],
        )
        for i in range(len(fronts) - 1):
            assert fronts[i]["hindered_velocity"] > fronts[i + 1]["hindered_velocity"]


# -----------------------------------------------------------------------
# MMS convergence tests
# -----------------------------------------------------------------------

class TestMMSConvergence:

    def test_orders_near_two(self, report):
        orders = report["verification"]["mms"]["observed_orders"]
        assert len(orders) >= 3
        for key, p in orders.items():
            assert 1.8 <= p <= 2.2, (
                f"MMS order {key} = {p:.4f}, expected in [1.8, 2.2]"
            )

    def test_l2_norms_decrease(self, report):
        norms = report["verification"]["mms"]["l2_norms"]
        sizes = sorted(int(k) for k in norms.keys())
        for i in range(len(sizes) - 1):
            assert norms[str(sizes[i])] > norms[str(sizes[i + 1])], (
                f"L2 norm should decrease: N={sizes[i]} vs N={sizes[i+1]}"
            )

    def test_finest_grid_accuracy(self, report):
        norms = report["verification"]["mms"]["l2_norms"]
        finest = str(max(int(k) for k in norms.keys()))
        assert norms[finest] < 1.0, (
            f"Finest grid L2={norms[finest]}, expected < 1.0"
        )

    def test_sufficient_grid_levels(self, report):
        assert len(report["verification"]["mms"]["l2_norms"]) >= 4


# -----------------------------------------------------------------------
# Historical audit tests
# -----------------------------------------------------------------------

# Ground truth for historical runs:
#   correct: 1, 4, 7
#   drag defect: 2, 6, 10
#   settling defect: 3, 8, 11
#   mms defect: 5, 9, 12

class TestHistoricalAudit:

    def test_all_runs_classified(self, report):
        audit = report["audit"]
        for run_id in range(1, 13):
            assert str(run_id) in audit, f"Missing audit for run_id={run_id}"

    @pytest.mark.parametrize("run_id", ["1", "4", "7"])
    def test_correct_runs_identified(self, report, run_id):
        entry = report["audit"][run_id]
        assert entry["status"] == "correct", (
            f"Run {run_id} should be correct, got {entry['status']}"
        )
        dt = entry.get("defect_type")
        assert dt is None or str(dt).lower() in ("none", "null", ""), (
            f"Run {run_id} defect_type should be null/none, got '{dt}'"
        )

    @pytest.mark.parametrize("run_id", ["2", "6", "10"])
    def test_drag_defects_identified(self, report, run_id):
        entry = report["audit"][run_id]
        assert entry["status"] == "defective", (
            f"Run {run_id} should be defective, got {entry['status']}"
        )
        assert entry.get("defect_type") is not None
        dt = entry["defect_type"].lower()
        assert "drag" in dt, (
            f"Run {run_id} defect should mention 'drag', got '{dt}'"
        )

    @pytest.mark.parametrize("run_id", ["3", "8", "11"])
    def test_settling_defects_identified(self, report, run_id):
        entry = report["audit"][run_id]
        assert entry["status"] == "defective", (
            f"Run {run_id} should be defective, got {entry['status']}"
        )
        assert entry.get("defect_type") is not None
        dt = entry["defect_type"].lower()
        assert any(kw in dt for kw in ["settl", "shock", "front", "wave"]), (
            f"Run {run_id} defect should reference settling/shock/front, got '{dt}'"
        )

    @pytest.mark.parametrize("run_id", ["5", "9", "12"])
    def test_mms_defects_identified(self, report, run_id):
        entry = report["audit"][run_id]
        assert entry["status"] == "defective", (
            f"Run {run_id} should be defective, got {entry['status']}"
        )
        assert entry.get("defect_type") is not None
        dt = entry["defect_type"].lower()
        assert any(kw in dt for kw in
                   ["mms", "source", "sign", "manufactur", "convergence"]), (
            f"Run {run_id} defect should reference MMS/source/sign, got '{dt}'"
        )


# -----------------------------------------------------------------------
# Report structure tests
# -----------------------------------------------------------------------

class TestReportStructure:

    def test_has_verification_section(self, report):
        assert "verification" in report

    def test_has_audit_section(self, report):
        assert "audit" in report

    def test_verification_has_drag(self, report):
        assert "drag" in report["verification"]

    def test_verification_has_settling(self, report):
        assert "settling" in report["verification"]
        assert "terminal_velocity" in report["verification"]["settling"]
        assert "reynolds_number" in report["verification"]["settling"]
        assert "fronts" in report["verification"]["settling"]

    def test_verification_has_mms(self, report):
        assert "mms" in report["verification"]
        assert "l2_norms" in report["verification"]["mms"]
        assert "observed_orders" in report["verification"]["mms"]

    def test_fronts_have_required_fields(self, report):
        for fr in report["verification"]["settling"]["fronts"]:
            assert "eps_s0" in fr
            assert "settling_front" in fr
            assert "filling_front" in fr
            assert "hindered_velocity" in fr


# -----------------------------------------------------------------------
# Convergence data export tests
# -----------------------------------------------------------------------

class TestConvergenceData:

    def test_convergence_tsv_exists(self):
        assert os.path.exists("/app/convergence.tsv"), \
            "convergence.tsv not found"

    def test_convergence_tsv_has_correct_rows(self, report):
        with open("/app/convergence.tsv") as f:
            lines = [l.strip() for l in f
                     if l.strip() and not l.startswith("#")]
        norms = report["verification"]["mms"]["l2_norms"]
        assert len(lines) == len(norms), \
            f"Expected {len(norms)} data lines, got {len(lines)}"

    def test_convergence_tsv_values_match_report(self, report):
        norms = report["verification"]["mms"]["l2_norms"]
        with open("/app/convergence.tsv") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                assert len(parts) == 2, \
                    f"Expected 2 tab-separated columns, got {len(parts)}"
                grid_str = parts[0].strip()
                val = float(parts[1].strip())
                assert grid_str in norms, \
                    f"Grid level {grid_str} not in report MMS norms"
                ref = norms[grid_str]
                assert abs(val - ref) / max(ref, 1e-12) < 0.001, \
                    f"TSV value {val} != report value {ref} for N={grid_str}"

    def test_convergence_tsv_sorted(self):
        with open("/app/convergence.tsv") as f:
            levels = []
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                levels.append(int(line.split("\t")[0].strip()))
        assert levels == sorted(levels), \
            "convergence.tsv rows must be sorted by grid level"


# -----------------------------------------------------------------------
# Gnuplot script and convergence plot tests
# -----------------------------------------------------------------------

class TestGnuplotPipeline:

    def test_gnuplot_script_exists(self):
        assert os.path.exists("/app/plot_convergence.gp"), \
            "plot_convergence.gp not found"

    def test_gnuplot_script_targets_png(self):
        with open("/app/plot_convergence.gp") as f:
            content = f.read()
        has_png_terminal = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("set terminal") or stripped.startswith("set term "):
                if "png" in stripped:
                    has_png_terminal = True
                    break
        assert has_png_terminal, \
            "gnuplot script must use a PNG-capable terminal (e.g. pngcairo)"

    def test_gnuplot_script_regenerates_png(self):
        """The gnuplot script must independently produce a valid PNG."""
        assert os.path.exists("/app/convergence.tsv"), \
            "convergence.tsv required for gnuplot"

        if os.path.exists("/app/convergence.png"):
            os.remove("/app/convergence.png")

        result = subprocess.run(
            ["gnuplot", "plot_convergence.gp"],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, \
            f"gnuplot failed (rc={result.returncode}): {result.stderr[:500]}"
        assert os.path.exists("/app/convergence.png"), \
            "gnuplot did not produce convergence.png"

        with open("/app/convergence.png", "rb") as f:
            magic = f.read(4)
        assert magic == b'\x89PNG', \
            "convergence.png is not a valid PNG file"

    def test_convergence_png_nontrivial(self):
        assert os.path.exists("/app/convergence.png"), \
            "convergence.png not found"
        size = os.path.getsize("/app/convergence.png")
        assert size > 1024, \
            f"convergence.png too small ({size} bytes), likely empty or corrupt"
