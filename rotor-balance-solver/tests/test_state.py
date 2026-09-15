
import json
import math
import os
import sqlite3
import subprocess
import tempfile

import pytest

SOLVER = "/app/balance_solver.py"


def run_solver(config, suffix=".json"):
    """Write config to a temp file, run the solver, return parsed JSON output."""
    if suffix == ".json":
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config, f)
            f.flush()
            tmp = f.name
    elif suffix == ".toml":
        # config is a string of TOML content
        with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
            f.write(config)
            f.flush()
            tmp = f.name
    else:
        raise ValueError(f"Unknown suffix: {suffix}")
    try:
        result = subprocess.run(
            ["python3", SOLVER, "solve", tmp],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"Solver exited with code {result.returncode}.\n"
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )
        return json.loads(result.stdout)
    finally:
        os.unlink(tmp)


def angle_close(a, b, tol=1.0):
    """Check if two angles (degrees) are within tol, handling 0/360 wrap."""
    diff = abs(a - b) % 360
    return min(diff, 360 - diff) <= tol


# ---------------------------------------------------------------------------
# Library build tests
# ---------------------------------------------------------------------------

class TestLibraryBuild:
    """Verify the C shared library exists and is loadable."""

    def test_shared_library_exists(self):
        assert os.path.isfile("/app/libbalance.so"), (
            "libbalance.so not found at /app/libbalance.so"
        )

    def test_library_loadable(self):
        import ctypes
        lib = ctypes.CDLL("/app/libbalance.so")
        assert lib is not None

    def test_library_exports_rotating(self):
        import ctypes
        lib = ctypes.CDLL("/app/libbalance.so")
        assert hasattr(lib, "rotating_balance"), (
            "libbalance.so does not export rotating_balance"
        )

    def test_library_exports_reciprocating(self):
        import ctypes
        lib = ctypes.CDLL("/app/libbalance.so")
        assert hasattr(lib, "reciprocating_balance"), (
            "libbalance.so does not export reciprocating_balance"
        )

    def test_library_exports_flywheel(self):
        import ctypes
        lib = ctypes.CDLL("/app/libbalance.so")
        assert hasattr(lib, "flywheel_analysis"), (
            "libbalance.so does not export flywheel_analysis"
        )


# ---------------------------------------------------------------------------
# Rotating balance tests
# ---------------------------------------------------------------------------

class TestRotating4Plane:
    """4 planes: 2 known masses, 2 correction planes."""

    CONFIG = {
        "type": "rotating",
        "planes": [
            {"name": "P1", "axial_position": 0.0, "radius": 0.05,
             "mass": None, "angle_deg": None, "is_correction": True},
            {"name": "P2", "axial_position": 0.1, "radius": 0.08,
             "mass": 3.0, "angle_deg": 0.0, "is_correction": False},
            {"name": "P3", "axial_position": 0.2, "radius": 0.06,
             "mass": 4.0, "angle_deg": 90.0, "is_correction": False},
            {"name": "P4", "axial_position": 0.3, "radius": 0.05,
             "mass": None, "angle_deg": None, "is_correction": True},
        ],
    }

    def test_correction_masses(self):
        out = run_solver(self.CONFIG)
        corr = {c["name"]: c for c in out["corrections"]}
        assert abs(corr["P1"]["mass_kg"] - 3.578) < 0.05
        assert abs(corr["P4"]["mass_kg"] - 3.578) < 0.05

    def test_correction_angles(self):
        out = run_solver(self.CONFIG)
        corr = {c["name"]: c for c in out["corrections"]}
        assert angle_close(corr["P1"]["angle_deg"], 206.57, tol=1.0)
        assert angle_close(corr["P4"]["angle_deg"], 243.43, tol=1.0)

    def test_residuals(self):
        out = run_solver(self.CONFIG)
        assert out["residual_mr"] < 1e-6
        assert out["residual_mrx"] < 1e-6


class TestRotating5Plane:
    """5 planes: 3 known masses, 2 correction planes."""

    CONFIG = {
        "type": "rotating",
        "planes": [
            {"name": "A", "axial_position": 0.0, "radius": 0.04,
             "mass": None, "angle_deg": None, "is_correction": True},
            {"name": "B", "axial_position": 0.1, "radius": 0.05,
             "mass": 2.0, "angle_deg": 0.0, "is_correction": False},
            {"name": "C", "axial_position": 0.25, "radius": 0.06,
             "mass": 3.0, "angle_deg": 120.0, "is_correction": False},
            {"name": "D", "axial_position": 0.4, "radius": 0.07,
             "mass": 1.5, "angle_deg": 210.0, "is_correction": False},
            {"name": "E", "axial_position": 0.5, "radius": 0.04,
             "mass": None, "angle_deg": None, "is_correction": True},
        ],
    }

    def test_correction_masses(self):
        out = run_solver(self.CONFIG)
        corr = {c["name"]: c for c in out["corrections"]}
        assert abs(corr["A"]["mass_kg"] - 1.738) < 0.05
        assert abs(corr["E"]["mass_kg"] - 2.604) < 0.05

    def test_correction_angles(self):
        out = run_solver(self.CONFIG)
        corr = {c["name"]: c for c in out["corrections"]}
        assert angle_close(corr["A"]["angle_deg"], 256.0, tol=1.0)
        assert angle_close(corr["E"]["angle_deg"], 339.81, tol=1.0)

    def test_residuals(self):
        out = run_solver(self.CONFIG)
        assert out["residual_mr"] < 1e-6
        assert out["residual_mrx"] < 1e-6


class TestRotatingAlreadyBalanced:
    """System already in perfect balance; corrections should be ~0."""

    CONFIG = {
        "type": "rotating",
        "planes": [
            {"name": "D1", "axial_position": -0.1, "radius": 0.1,
             "mass": None, "angle_deg": None, "is_correction": True},
            {"name": "P1", "axial_position": 0.0, "radius": 0.1,
             "mass": 1.0, "angle_deg": 0.0, "is_correction": False},
            {"name": "P3", "axial_position": 0.1, "radius": 0.1,
             "mass": 2.0, "angle_deg": 180.0, "is_correction": False},
            {"name": "P2", "axial_position": 0.2, "radius": 0.1,
             "mass": 1.0, "angle_deg": 0.0, "is_correction": False},
            {"name": "D2", "axial_position": 0.3, "radius": 0.1,
             "mass": None, "angle_deg": None, "is_correction": True},
        ],
    }

    def test_zero_corrections(self):
        out = run_solver(self.CONFIG)
        for c in out["corrections"]:
            assert c["mass_kg"] < 1e-6, (
                f"Correction {c['name']} should be ~0, got {c['mass_kg']}"
            )

    def test_residuals(self):
        out = run_solver(self.CONFIG)
        assert out["residual_mr"] < 1e-6
        assert out["residual_mrx"] < 1e-6


# ---------------------------------------------------------------------------
# Reciprocating balance tests
# ---------------------------------------------------------------------------

class TestRecip3Cyl120:
    """3-cylinder inline, 120 deg apart. Forces balanced, moments not."""

    CONFIG = {
        "type": "reciprocating",
        "cylinders": [
            {"name": "A", "mass_kg": 0.4, "crank_radius_m": 0.04,
             "con_rod_length_m": 0.12, "crank_angle_deg": 0,
             "axial_position_m": 0.05},
            {"name": "B", "mass_kg": 0.4, "crank_radius_m": 0.04,
             "con_rod_length_m": 0.12, "crank_angle_deg": 120,
             "axial_position_m": 0.10},
            {"name": "C", "mass_kg": 0.4, "crank_radius_m": 0.04,
             "con_rod_length_m": 0.12, "crank_angle_deg": 240,
             "axial_position_m": 0.15},
        ],
        "speed_rad_s": 30.0,
        "reference_plane_m": 0.0,
    }

    def test_primary_force_balanced(self):
        out = run_solver(self.CONFIG)
        assert out["primary_force"]["balanced"] is True
        assert out["primary_force"]["resultant_mr"] < 1e-6

    def test_secondary_force_balanced(self):
        out = run_solver(self.CONFIG)
        assert out["secondary_force"]["balanced"] is True
        assert out["secondary_force"]["resultant_mr_n"] < 1e-6

    def test_primary_moment_unbalanced(self):
        out = run_solver(self.CONFIG)
        pf = out["primary_moment"]
        assert pf["balanced"] is False
        assert abs(pf["resultant_mrx"] - 0.001386) < 0.0001
        assert abs(pf["peak_Nm"] - 1.2474) < 0.05

    def test_secondary_moment_unbalanced(self):
        out = run_solver(self.CONFIG)
        sf = out["secondary_moment"]
        assert sf["balanced"] is False
        assert abs(sf["resultant_mrx_n"] - 0.000462) < 0.00005
        assert abs(sf["peak_Nm"] - 0.4158) < 0.02


class TestRecip4CylStandard:
    """4-cylinder inline, standard 0-180-180-0. Primary balanced, secondary not."""

    CONFIG = {
        "type": "reciprocating",
        "cylinders": [
            {"name": "1", "mass_kg": 0.4, "crank_radius_m": 0.04,
             "con_rod_length_m": 0.12, "crank_angle_deg": 0,
             "axial_position_m": 0.05},
            {"name": "2", "mass_kg": 0.4, "crank_radius_m": 0.04,
             "con_rod_length_m": 0.12, "crank_angle_deg": 180,
             "axial_position_m": 0.10},
            {"name": "3", "mass_kg": 0.4, "crank_radius_m": 0.04,
             "con_rod_length_m": 0.12, "crank_angle_deg": 180,
             "axial_position_m": 0.15},
            {"name": "4", "mass_kg": 0.4, "crank_radius_m": 0.04,
             "con_rod_length_m": 0.12, "crank_angle_deg": 0,
             "axial_position_m": 0.20},
        ],
        "speed_rad_s": 30.0,
        "reference_plane_m": 0.0,
    }

    def test_primary_balanced(self):
        out = run_solver(self.CONFIG)
        assert out["primary_force"]["balanced"] is True
        assert out["primary_moment"]["balanced"] is True

    def test_secondary_force_unbalanced(self):
        out = run_solver(self.CONFIG)
        sf = out["secondary_force"]
        assert sf["balanced"] is False
        assert abs(sf["resultant_mr_n"] - 0.02133) < 0.001
        assert abs(sf["peak_N"] - 19.2) < 0.5

    def test_secondary_moment_unbalanced(self):
        out = run_solver(self.CONFIG)
        sm = out["secondary_moment"]
        assert sm["balanced"] is False
        assert abs(sm["resultant_mrx_n"] - 0.002667) < 0.0002
        assert abs(sm["peak_Nm"] - 2.4) < 0.1


class TestRecip2CylOpposed:
    """2-cylinder opposed (180 deg). Primary force balanced; rest not."""

    CONFIG = {
        "type": "reciprocating",
        "cylinders": [
            {"name": "A", "mass_kg": 0.5, "crank_radius_m": 0.05,
             "con_rod_length_m": 0.15, "crank_angle_deg": 0,
             "axial_position_m": 0.0},
            {"name": "B", "mass_kg": 0.5, "crank_radius_m": 0.05,
             "con_rod_length_m": 0.15, "crank_angle_deg": 180,
             "axial_position_m": 0.2},
        ],
        "speed_rad_s": 50.0,
        "reference_plane_m": 0.0,
    }

    def test_primary_force_balanced(self):
        out = run_solver(self.CONFIG)
        assert out["primary_force"]["balanced"] is True

    def test_secondary_force_unbalanced(self):
        out = run_solver(self.CONFIG)
        sf = out["secondary_force"]
        assert sf["balanced"] is False
        assert abs(sf["resultant_mr_n"] - 0.016667) < 0.001
        assert abs(sf["peak_N"] - 41.667) < 1.0

    def test_primary_moment_unbalanced(self):
        out = run_solver(self.CONFIG)
        pm = out["primary_moment"]
        assert pm["balanced"] is False
        assert abs(pm["resultant_mrx"] - 0.005) < 0.0005
        assert abs(pm["peak_Nm"] - 12.5) < 0.5

    def test_secondary_moment_unbalanced(self):
        out = run_solver(self.CONFIG)
        sm = out["secondary_moment"]
        assert sm["balanced"] is False
        assert abs(sm["resultant_mrx_n"] - 0.001667) < 0.0002
        assert abs(sm["peak_Nm"] - 4.167) < 0.2


class TestRecip3CylWithCorrections:
    """3-cylinder with 2 primary correction planes."""

    CONFIG = {
        "type": "reciprocating",
        "cylinders": [
            {"name": "A", "mass_kg": 0.4, "crank_radius_m": 0.04,
             "con_rod_length_m": 0.12, "crank_angle_deg": 0,
             "axial_position_m": 0.05},
            {"name": "B", "mass_kg": 0.4, "crank_radius_m": 0.04,
             "con_rod_length_m": 0.12, "crank_angle_deg": 120,
             "axial_position_m": 0.10},
            {"name": "C", "mass_kg": 0.4, "crank_radius_m": 0.04,
             "con_rod_length_m": 0.12, "crank_angle_deg": 240,
             "axial_position_m": 0.15},
        ],
        "speed_rad_s": 30.0,
        "reference_plane_m": 0.0,
        "correction_planes": [
            {"name": "X", "axial_position_m": 0.0, "crank_radius_m": 0.04},
            {"name": "Y", "axial_position_m": 0.2, "crank_radius_m": 0.04},
        ],
    }

    def test_correction_count(self):
        out = run_solver(self.CONFIG)
        assert len(out["primary_corrections"]) == 2

    def test_correction_masses(self):
        out = run_solver(self.CONFIG)
        corr = {c["name"]: c for c in out["primary_corrections"]}
        assert abs(corr["X"]["mass_kg"] - 0.1732) < 0.005
        assert abs(corr["Y"]["mass_kg"] - 0.1732) < 0.005

    def test_correction_angles(self):
        out = run_solver(self.CONFIG)
        corr = {c["name"]: c for c in out["primary_corrections"]}
        assert angle_close(corr["X"]["angle_deg"], 210.0, tol=1.0)
        assert angle_close(corr["Y"]["angle_deg"], 30.0, tol=1.0)

    def test_balance_state_unchanged(self):
        """Correction planes should not alter the balance analysis output."""
        out = run_solver(self.CONFIG)
        assert out["primary_force"]["balanced"] is True
        assert out["secondary_force"]["balanced"] is True
        assert out["primary_moment"]["balanced"] is False
        assert out["secondary_moment"]["balanced"] is False


# ---------------------------------------------------------------------------
# Flywheel analysis tests
# ---------------------------------------------------------------------------

class TestFlywheelPiecewise:
    """Piecewise-linear torque over 2pi with known trapezoidal integral."""

    CONFIG = {
        "type": "flywheel",
        "torque_angle_data": [
            [0.0, 100.0],
            [math.pi / 2, 300.0],
            [math.pi, 100.0],
            [3 * math.pi / 2, -100.0],
            [2 * math.pi, 100.0],
        ],
        "cycle_angle_rad": 2 * math.pi,
        "mean_speed_rpm": 500.0,
        "target_cof_speed": 0.02,
        "flywheel_radius_gyration_m": 0.3,
    }

    def test_mean_torque(self):
        out = run_solver(self.CONFIG)
        # total work = 200*pi, mean = 200*pi / 2*pi = 100
        assert abs(out["mean_torque_Nm"] - 100.0) < 0.5

    def test_energy_per_cycle(self):
        out = run_solver(self.CONFIG)
        # 200*pi ~ 628.318
        assert abs(out["energy_per_cycle_J"] - 628.318) < 2.0

    def test_max_energy_fluctuation(self):
        out = run_solver(self.CONFIG)
        # 100*pi ~ 314.159
        assert abs(out["max_energy_fluctuation_J"] - 314.159) < 2.0

    def test_required_inertia(self):
        out = run_solver(self.CONFIG)
        # I = 100*pi / ((500*2*pi/60)^2 * 0.02) = 18/pi ~ 5.7296
        assert abs(out["required_inertia_kgm2"] - 5.7296) < 0.05

    def test_required_mass(self):
        out = run_solver(self.CONFIG)
        # mass = 18/(pi*0.09) = 200/pi ~ 63.662
        assert abs(out["required_mass_kg"] - 63.662) < 1.0

    def test_speed_range(self):
        out = run_solver(self.CONFIG)
        assert abs(out["speed_range_rpm"]["max"] - 505.0) < 0.5
        assert abs(out["speed_range_rpm"]["min"] - 495.0) < 0.5


class TestFlywheelSinusoidal:
    """Dense sinusoidal torque data (361 points) for accuracy test."""

    @staticmethod
    def _make_config():
        data = []
        for i in range(361):
            theta = math.radians(i)
            torque = 200.0 + 150.0 * math.sin(theta)
            data.append([theta, torque])
        return {
            "type": "flywheel",
            "torque_angle_data": data,
            "cycle_angle_rad": 2 * math.pi,
            "mean_speed_rpm": 600.0,
            "target_cof_speed": 0.01,
            "flywheel_radius_gyration_m": 0.4,
        }

    def test_mean_torque(self):
        out = run_solver(self._make_config())
        assert abs(out["mean_torque_Nm"] - 200.0) < 0.5

    def test_energy_per_cycle(self):
        out = run_solver(self._make_config())
        # 200 * 2*pi ~ 1256.64
        assert abs(out["energy_per_cycle_J"] - 1256.64) < 5.0

    def test_max_fluctuation(self):
        out = run_solver(self._make_config())
        # Analytical: 300.0; with 361 points trapezoidal very close
        assert abs(out["max_energy_fluctuation_J"] - 300.0) < 2.0

    def test_required_inertia(self):
        out = run_solver(self._make_config())
        # I = 300 / ((20*pi)^2 * 0.01) = 300/(4*pi^2) = 75/pi^2 ~ 7.599
        assert abs(out["required_inertia_kgm2"] - 7.599) < 0.1

    def test_required_mass(self):
        out = run_solver(self._make_config())
        # mass = 75/(pi^2 * 0.16) ~ 47.49
        assert abs(out["required_mass_kg"] - 47.49) < 1.0

    def test_speed_range(self):
        out = run_solver(self._make_config())
        assert abs(out["speed_range_rpm"]["max"] - 603.0) < 0.5
        assert abs(out["speed_range_rpm"]["min"] - 597.0) < 0.5


class TestFlywheelEnergyOnly:
    """Flywheel analysis without target_cof_speed - energy analysis only."""

    CONFIG = {
        "type": "flywheel",
        "torque_angle_data": [
            [0.0, 100.0],
            [math.pi / 2, 300.0],
            [math.pi, 100.0],
            [3 * math.pi / 2, -100.0],
            [2 * math.pi, 100.0],
        ],
        "cycle_angle_rad": 2 * math.pi,
        "mean_speed_rpm": 500.0,
    }

    def test_mean_torque(self):
        out = run_solver(self.CONFIG)
        assert abs(out["mean_torque_Nm"] - 100.0) < 0.5

    def test_energy_per_cycle(self):
        out = run_solver(self.CONFIG)
        assert abs(out["energy_per_cycle_J"] - 628.318) < 2.0

    def test_max_energy_fluctuation(self):
        out = run_solver(self.CONFIG)
        assert abs(out["max_energy_fluctuation_J"] - 314.159) < 2.0

    def test_no_inertia_field(self):
        out = run_solver(self.CONFIG)
        assert "required_inertia_kgm2" not in out

    def test_no_mass_field(self):
        out = run_solver(self.CONFIG)
        assert "required_mass_kg" not in out

    def test_no_speed_range_field(self):
        out = run_solver(self.CONFIG)
        assert "speed_range_rpm" not in out


# ---------------------------------------------------------------------------
# TOML input format tests
# ---------------------------------------------------------------------------

class TestTomlRotating:
    """Test rotating balance analysis with TOML input format."""

    TOML_CONTENT = """\
type = "rotating"

[[planes]]
name = "P1"
axial_position = 0.0
radius = 0.05
is_correction = true

[[planes]]
name = "P2"
axial_position = 0.1
radius = 0.08
mass = 3.0
angle_deg = 0.0
is_correction = false

[[planes]]
name = "P3"
axial_position = 0.2
radius = 0.06
mass = 4.0
angle_deg = 90.0
is_correction = false

[[planes]]
name = "P4"
axial_position = 0.3
radius = 0.05
is_correction = true
"""

    def test_toml_correction_masses(self):
        out = run_solver(self.TOML_CONTENT, suffix=".toml")
        corr = {c["name"]: c for c in out["corrections"]}
        assert abs(corr["P1"]["mass_kg"] - 3.578) < 0.05
        assert abs(corr["P4"]["mass_kg"] - 3.578) < 0.05

    def test_toml_correction_angles(self):
        out = run_solver(self.TOML_CONTENT, suffix=".toml")
        corr = {c["name"]: c for c in out["corrections"]}
        assert angle_close(corr["P1"]["angle_deg"], 206.57, tol=1.0)
        assert angle_close(corr["P4"]["angle_deg"], 243.43, tol=1.0)

    def test_toml_residuals(self):
        out = run_solver(self.TOML_CONTENT, suffix=".toml")
        assert out["residual_mr"] < 1e-6
        assert out["residual_mrx"] < 1e-6


class TestTomlReciprocating:
    """Test reciprocating analysis with TOML input including correction planes."""

    TOML_CONTENT = """\
type = "reciprocating"
speed_rad_s = 30.0
reference_plane_m = 0.0

[[cylinders]]
name = "A"
mass_kg = 0.4
crank_radius_m = 0.04
con_rod_length_m = 0.12
crank_angle_deg = 0
axial_position_m = 0.05

[[cylinders]]
name = "B"
mass_kg = 0.4
crank_radius_m = 0.04
con_rod_length_m = 0.12
crank_angle_deg = 120
axial_position_m = 0.10

[[cylinders]]
name = "C"
mass_kg = 0.4
crank_radius_m = 0.04
con_rod_length_m = 0.12
crank_angle_deg = 240
axial_position_m = 0.15

[[correction_planes]]
name = "X"
axial_position_m = 0.0
crank_radius_m = 0.04

[[correction_planes]]
name = "Y"
axial_position_m = 0.2
crank_radius_m = 0.04
"""

    def test_toml_primary_force_balanced(self):
        out = run_solver(self.TOML_CONTENT, suffix=".toml")
        assert out["primary_force"]["balanced"] is True

    def test_toml_correction_masses(self):
        out = run_solver(self.TOML_CONTENT, suffix=".toml")
        corr = {c["name"]: c for c in out["primary_corrections"]}
        assert abs(corr["X"]["mass_kg"] - 0.1732) < 0.005
        assert abs(corr["Y"]["mass_kg"] - 0.1732) < 0.005

    def test_toml_correction_angles(self):
        out = run_solver(self.TOML_CONTENT, suffix=".toml")
        corr = {c["name"]: c for c in out["primary_corrections"]}
        assert angle_close(corr["X"]["angle_deg"], 210.0, tol=1.0)
        assert angle_close(corr["Y"]["angle_deg"], 30.0, tol=1.0)


class TestTomlFlywheel:
    """Test flywheel analysis with TOML input."""

    TOML_CONTENT = """\
type = "flywheel"
cycle_angle_rad = 6.283185307179586
mean_speed_rpm = 500.0
target_cof_speed = 0.02
flywheel_radius_gyration_m = 0.3

torque_angle_data = [
  [0.0, 100.0],
  [1.5707963267948966, 300.0],
  [3.141592653589793, 100.0],
  [4.71238898038469, -100.0],
  [6.283185307179586, 100.0]
]
"""

    def test_toml_mean_torque(self):
        out = run_solver(self.TOML_CONTENT, suffix=".toml")
        assert abs(out["mean_torque_Nm"] - 100.0) < 0.5

    def test_toml_required_inertia(self):
        out = run_solver(self.TOML_CONTENT, suffix=".toml")
        assert abs(out["required_inertia_kgm2"] - 5.7296) < 0.05

    def test_toml_speed_range(self):
        out = run_solver(self.TOML_CONTENT, suffix=".toml")
        assert abs(out["speed_range_rpm"]["max"] - 505.0) < 0.5
        assert abs(out["speed_range_rpm"]["min"] - 495.0) < 0.5


# ---------------------------------------------------------------------------
# Batch mode and query mode tests
# ---------------------------------------------------------------------------

_BATCH_ROT_CONFIG = {
    "type": "rotating",
    "planes": [
        {"name": "C1", "axial_position": 0.0, "radius": 0.1,
         "mass": None, "angle_deg": None, "is_correction": True},
        {"name": "M1", "axial_position": 0.1, "radius": 0.1,
         "mass": 1.0, "angle_deg": 0.0, "is_correction": False},
        {"name": "M2", "axial_position": 0.2, "radius": 0.1,
         "mass": 1.0, "angle_deg": 180.0, "is_correction": False},
        {"name": "C2", "axial_position": 0.3, "radius": 0.1,
         "mass": None, "angle_deg": None, "is_correction": True},
    ],
}

_BATCH_FW_CONFIG = {
    "type": "flywheel",
    "torque_angle_data": [
        [0.0, 100.0], [3.141592653589793, 100.0], [6.283185307179586, 100.0]
    ],
    "cycle_angle_rad": 6.283185307179586,
    "mean_speed_rpm": 500.0,
}

_BATCH_FW_TOML = """\
type = "flywheel"
cycle_angle_rad = 6.283185307179586
mean_speed_rpm = 400.0
torque_angle_data = [[0.0, 200.0], [3.141592653589793, 200.0], [6.283185307179586, 200.0]]
"""


@pytest.fixture(scope="module")
def batch_db(tmp_path_factory):
    """Create a batch database with 3 configs for batch/query tests."""
    tmp = tmp_path_factory.mktemp("batch")
    config_dir = tmp / "configs"
    config_dir.mkdir()

    with open(config_dir / "rot.json", "w") as f:
        json.dump(_BATCH_ROT_CONFIG, f)
    with open(config_dir / "fw.json", "w") as f:
        json.dump(_BATCH_FW_CONFIG, f)
    (config_dir / "fw2.toml").write_text(_BATCH_FW_TOML)

    db_path = str(tmp / "results.db")
    result = subprocess.run(
        ["python3", SOLVER, "batch", str(config_dir), db_path],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"Batch failed with code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    return db_path


class TestBatchMode:
    """Test batch processing creates correct SQLite database."""

    def test_batch_row_count(self, batch_db):
        conn = sqlite3.connect(batch_db)
        count = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        conn.close()
        assert count == 3, f"Expected 3 rows, got {count}"

    def test_batch_schema_columns(self, batch_db):
        conn = sqlite3.connect(batch_db)
        cursor = conn.execute("PRAGMA table_info(results)")
        cols = {row[1] for row in cursor.fetchall()}
        conn.close()
        for expected in ("config_name", "analysis_type", "result_json",
                         "mean_torque", "max_fluctuation", "residual_mr"):
            assert expected in cols, f"Missing column: {expected}"

    def test_batch_rotating_nulls(self, batch_db):
        """Rotating results should have residual_mr but NULL mean_torque."""
        conn = sqlite3.connect(batch_db)
        row = conn.execute(
            "SELECT mean_torque, residual_mr FROM results WHERE analysis_type='rotating'"
        ).fetchone()
        conn.close()
        assert row is not None, "No rotating row found"
        assert row[0] is None, f"mean_torque should be NULL for rotating, got {row[0]}"
        assert row[1] is not None, "residual_mr should not be NULL for rotating"

    def test_batch_flywheel_nulls(self, batch_db):
        """Flywheel results should have mean_torque but NULL residual_mr."""
        conn = sqlite3.connect(batch_db)
        row = conn.execute(
            "SELECT mean_torque, residual_mr FROM results WHERE analysis_type='flywheel' LIMIT 1"
        ).fetchone()
        conn.close()
        assert row is not None, "No flywheel row found"
        assert row[0] is not None, "mean_torque should not be NULL for flywheel"
        assert row[1] is None, f"residual_mr should be NULL for flywheel, got {row[1]}"

    def test_batch_result_json_parseable(self, batch_db):
        conn = sqlite3.connect(batch_db)
        rows = conn.execute("SELECT result_json FROM results").fetchall()
        conn.close()
        for row in rows:
            data = json.loads(row[0])
            assert isinstance(data, dict), "result_json should parse to a dict"

    def test_batch_config_names(self, batch_db):
        conn = sqlite3.connect(batch_db)
        names = sorted(
            r[0] for r in conn.execute("SELECT config_name FROM results").fetchall()
        )
        conn.close()
        assert names == ["fw.json", "fw2.toml", "rot.json"]


class TestQueryMode:
    """Test SQL query subcommand."""

    def test_query_returns_json_array(self, batch_db):
        result = subprocess.run(
            ["python3", SOLVER, "query", batch_db,
             "SELECT config_name, analysis_type FROM results ORDER BY config_name"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"Query failed: {result.stderr}"
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 3
        assert data[0]["config_name"] == "fw.json"
        assert data[0]["analysis_type"] == "flywheel"

    def test_query_aggregate(self, batch_db):
        result = subprocess.run(
            ["python3", SOLVER, "query", batch_db,
             "SELECT COUNT(*) as cnt FROM results"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"Query failed: {result.stderr}"
        data = json.loads(result.stdout)
        assert data[0]["cnt"] == 3

    def test_query_numeric_filter(self, batch_db):
        result = subprocess.run(
            ["python3", SOLVER, "query", batch_db,
             "SELECT mean_torque FROM results WHERE analysis_type='flywheel' AND mean_torque > 150"],
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, f"Query failed: {result.stderr}"
        data = json.loads(result.stdout)
        assert len(data) == 1
        assert abs(data[0]["mean_torque"] - 200.0) < 1.0
