
import subprocess
import csv
import os
import pytest


def run_gie(filepath):
    """Run gie on a test file and return (success, combined_output)."""
    result = subprocess.run(
        ["gie", filepath],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.returncode == 0, result.stdout + "\n" + result.stderr


def compute_chain_point(lon, lat):
    """Compute DHDN -> LAEA Europe transformation using known-correct parameters.

    Uses the correct Helmert 7-parameter (position vector convention) for
    DHDN->WGS84, then the correct LAEA Europe (EPSG:3035) projection.
    """
    input_str = f"{lon} {lat}\n"
    result = subprocess.run(
        [
            "cs2cs",
            "+proj=longlat",
            "+ellps=bessel",
            "+towgs84=598.1,73.7,418.2,0.202,0.045,-2.455,6.7",
            "+to",
            "+proj=laea",
            "+lat_0=52",
            "+lon_0=10",
            "+x_0=4321000",
            "+y_0=3210000",
            "+ellps=GRS80",
            "+units=m",
        ],
        input=input_str,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"cs2cs failed: {result.stderr}"
    parts = result.stdout.strip().split()
    return float(parts[0]), float(parts[1])


# ---------------------------------------------------------------------------
# Scenario A: Oblique Stereographic (Netherlands / RD New)
# ---------------------------------------------------------------------------
class TestScenarioA:
    def test_fixed_file_exists(self):
        assert os.path.exists("/app/results/scenario_a_fixed.gie"), \
            "Missing /app/results/scenario_a_fixed.gie"

    def test_gie_passes(self):
        ok, output = run_gie("/app/results/scenario_a_fixed.gie")
        assert ok, f"Scenario A gie tests failed:\n{output}"


# ---------------------------------------------------------------------------
# Scenario B: Albers Equal Area (Australia)
# ---------------------------------------------------------------------------
class TestScenarioB:
    def test_fixed_file_exists(self):
        assert os.path.exists("/app/results/scenario_b_fixed.gie"), \
            "Missing /app/results/scenario_b_fixed.gie"

    def test_gie_passes(self):
        ok, output = run_gie("/app/results/scenario_b_fixed.gie")
        assert ok, f"Scenario B gie tests failed:\n{output}"


# ---------------------------------------------------------------------------
# Scenario C: LAEA Europe
# ---------------------------------------------------------------------------
class TestScenarioC:
    def test_fixed_file_exists(self):
        assert os.path.exists("/app/results/scenario_c_fixed.gie"), \
            "Missing /app/results/scenario_c_fixed.gie"

    def test_gie_passes(self):
        ok, output = run_gie("/app/results/scenario_c_fixed.gie")
        assert ok, f"Scenario C gie tests failed:\n{output}"


# ---------------------------------------------------------------------------
# Scenario D: Helmert 7-parameter (DHDN)
# ---------------------------------------------------------------------------
class TestScenarioD:
    def test_fixed_file_exists(self):
        assert os.path.exists("/app/results/scenario_d_fixed.gie"), \
            "Missing /app/results/scenario_d_fixed.gie"

    def test_gie_passes(self):
        ok, output = run_gie("/app/results/scenario_d_fixed.gie")
        assert ok, f"Scenario D gie tests failed:\n{output}"


# ---------------------------------------------------------------------------
# Chain: DHDN geographic -> LAEA Europe projected
# ---------------------------------------------------------------------------
class TestChainResults:
    CHAIN_INPUTS = [
        (7.483333333333, 53.500000000000),
        (10.333333333333, 48.833333333333),
        (13.466666666667, 52.483333333333),
        (8.000000000000, 50.083333333333),
        (10.550000000000, 47.750000000000),
    ]

    def test_file_exists(self):
        assert os.path.exists("/app/results/chain_results.csv"), \
            "Missing /app/results/chain_results.csv"

    def test_has_required_columns(self):
        with open("/app/results/chain_results.csv") as f:
            reader = csv.DictReader(f)
            row = next(reader)
        for col in ("lon_dhdn", "lat_dhdn", "easting_laea", "northing_laea"):
            assert col in row, f"Missing column '{col}' in chain_results.csv"

    def test_correct_row_count(self):
        with open("/app/results/chain_results.csv") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 5, f"Expected 5 rows, got {len(rows)}"

    def test_chain_accuracy(self):
        """Compare each chain result against an independent cs2cs computation."""
        with open("/app/results/chain_results.csv") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == len(self.CHAIN_INPUTS), "Row count mismatch"

        tolerance_m = 1.0  # 1 metre

        for i, (lon, lat) in enumerate(self.CHAIN_INPUTS):
            exp_e, exp_n = compute_chain_point(lon, lat)
            act_e = float(rows[i]["easting_laea"])
            act_n = float(rows[i]["northing_laea"])

            assert abs(exp_e - act_e) < tolerance_m, (
                f"Point {i} easting: got {act_e}, expected {exp_e} "
                f"(diff={abs(exp_e - act_e):.4f} m)"
            )
            assert abs(exp_n - act_n) < tolerance_m, (
                f"Point {i} northing: got {act_n}, expected {exp_n} "
                f"(diff={abs(exp_n - act_n):.4f} m)"
            )
