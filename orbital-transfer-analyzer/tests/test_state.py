
"""
Tests for the orbital mechanics mission planner.
Validates /app/results.json against textbook golden values from
Vallado "Fundamentals of Astrodynamics" and Curtis "Orbital Mechanics
for Engineering Students".
Also validates /app/report.csv structure.
"""

import json
import math
import os
import pytest


RESULTS_FILE = "/app/results.json"
REPORT_FILE = "/app/report.csv"


@pytest.fixture(scope="module")
def results():
    with open(RESULTS_FILE) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# rv2coe: State vectors -> Classical Orbital Elements (Curtis Example 4.3)
# ---------------------------------------------------------------------------
class TestRv2Coe:
    def test_semi_latus_rectum(self, results):
        r = results["rv2coe_1"]
        assert r["p_km"] == pytest.approx(8530.474, rel=1e-3)

    def test_eccentricity(self, results):
        r = results["rv2coe_1"]
        assert r["ecc"] == pytest.approx(0.17121, rel=5e-3)

    def test_inclination(self, results):
        r = results["rv2coe_1"]
        assert r["inc_deg"] == pytest.approx(153.249, abs=0.15)

    def test_raan(self, results):
        r = results["rv2coe_1"]
        assert r["raan_deg"] == pytest.approx(255.279, abs=0.15)

    def test_argp(self, results):
        r = results["rv2coe_1"]
        assert r["argp_deg"] == pytest.approx(20.068, abs=0.15)

    def test_true_anomaly(self, results):
        r = results["rv2coe_1"]
        assert r["nu_deg"] == pytest.approx(28.446, abs=0.15)


# ---------------------------------------------------------------------------
# coe2rv: Classical elements -> State vectors (roundtrip of rv2coe_1)
# ---------------------------------------------------------------------------
class TestCoe2Rv:
    def test_position_x(self, results):
        r = results["coe2rv_1"]
        assert r["r_km"][0] == pytest.approx(-6045.0, abs=1.0)

    def test_position_y(self, results):
        r = results["coe2rv_1"]
        assert r["r_km"][1] == pytest.approx(-3490.0, abs=1.0)

    def test_position_z(self, results):
        r = results["coe2rv_1"]
        assert r["r_km"][2] == pytest.approx(2500.0, abs=1.0)

    def test_velocity_x(self, results):
        r = results["coe2rv_1"]
        assert r["v_km_s"][0] == pytest.approx(-3.457, abs=0.01)

    def test_velocity_y(self, results):
        r = results["coe2rv_1"]
        assert r["v_km_s"][1] == pytest.approx(6.618, abs=0.01)

    def test_velocity_z(self, results):
        r = results["coe2rv_1"]
        assert r["v_km_s"][2] == pytest.approx(2.533, abs=0.01)

    def test_position_magnitude(self, results):
        """Position magnitude should match original."""
        r = results["coe2rv_1"]
        mag = math.sqrt(sum(c**2 for c in r["r_km"]))
        expected = math.sqrt(6045**2 + 3490**2 + 2500**2)
        assert mag == pytest.approx(expected, rel=1e-4)


# ---------------------------------------------------------------------------
# Lambert Problem 1: Planar transfer (Vallado Example 7.5)
# ---------------------------------------------------------------------------
class TestLambert1:
    def test_departure_velocity(self, results):
        r = results["lambert_1"]
        expected = [2.058925, 2.915956, 0.0]
        for i in range(3):
            assert r["v0_km_s"][i] == pytest.approx(expected[i], abs=0.015)

    def test_arrival_velocity(self, results):
        r = results["lambert_1"]
        expected = [-3.451569, 0.910301, 0.0]
        for i in range(3):
            assert r["v_km_s"][i] == pytest.approx(expected[i], abs=0.015)

    def test_departure_speed_reasonable(self, results):
        r = results["lambert_1"]
        speed = math.sqrt(sum(c**2 for c in r["v0_km_s"]))
        assert 2.0 < speed < 6.0


# ---------------------------------------------------------------------------
# Lambert Problem 2: 3D transfer (Curtis Example 5.2)
# ---------------------------------------------------------------------------
class TestLambert2:
    def test_departure_velocity(self, results):
        r = results["lambert_2"]
        expected = [-5.9925, 1.9254, 3.2456]
        for i in range(3):
            assert r["v0_km_s"][i] == pytest.approx(expected[i], abs=0.02)

    def test_arrival_velocity(self, results):
        r = results["lambert_2"]
        expected = [-3.3125, -4.1966, -0.38529]
        for i in range(3):
            assert r["v_km_s"][i] == pytest.approx(expected[i], abs=0.02)

    def test_arrival_speed_reasonable(self, results):
        r = results["lambert_2"]
        speed = math.sqrt(sum(c**2 for c in r["v_km_s"]))
        assert 3.0 < speed < 8.0

    def test_departure_arrival_speeds_differ(self, results):
        """Departure and arrival speeds should not be identical for asymmetric transfer."""
        r = results["lambert_2"]
        dep_speed = math.sqrt(sum(c**2 for c in r["v0_km_s"]))
        arr_speed = math.sqrt(sum(c**2 for c in r["v_km_s"]))
        assert abs(dep_speed - arr_speed) > 0.5


# ---------------------------------------------------------------------------
# Hohmann Transfer (Vallado Example 6.1): LEO -> GEO
# ---------------------------------------------------------------------------
class TestHohmann:
    def test_dv_total(self, results):
        r = results["hohmann_1"]
        assert r["dv_total_km_s"] == pytest.approx(3.935224, rel=2e-3)

    def test_transfer_time(self, results):
        r = results["hohmann_1"]
        expected_t = 5.256713 * 3600.0
        assert r["t_trans_s"] == pytest.approx(expected_t, rel=2e-3)

    def test_dv_components_sum_to_total(self, results):
        r = results["hohmann_1"]
        computed_total = r["dv_a_km_s"] + r["dv_b_km_s"]
        assert computed_total == pytest.approx(r["dv_total_km_s"], rel=1e-6)

    def test_dv_components_positive(self, results):
        r = results["hohmann_1"]
        assert r["dv_a_km_s"] > 0
        assert r["dv_b_km_s"] > 0

    def test_dv_a_larger_than_dv_b(self, results):
        """For LEO->GEO, the departure burn should be larger."""
        r = results["hohmann_1"]
        assert r["dv_a_km_s"] > r["dv_b_km_s"]


# ---------------------------------------------------------------------------
# Bielliptic Transfer (Vallado Example 6.2)
# ---------------------------------------------------------------------------
class TestBielliptic:
    def test_dv_total(self, results):
        r = results["bielliptic_1"]
        assert r["dv_total_km_s"] == pytest.approx(3.904057, rel=2e-3)

    def test_transfer_time_total(self, results):
        r = results["bielliptic_1"]
        expected_t = 593.919803 * 3600.0
        total_t = r["t_trans1_s"] + r["t_trans2_s"]
        assert total_t == pytest.approx(expected_t, rel=5e-3)

    def test_dv_components_sum_to_total(self, results):
        r = results["bielliptic_1"]
        computed_total = r["dv_a_km_s"] + r["dv_b_km_s"] + r["dv_c_km_s"]
        assert computed_total == pytest.approx(r["dv_total_km_s"], rel=1e-6)

    def test_all_dv_components_nonnegative(self, results):
        r = results["bielliptic_1"]
        assert r["dv_a_km_s"] >= 0
        assert r["dv_b_km_s"] >= 0
        assert r["dv_c_km_s"] >= 0

    def test_first_burn_largest(self, results):
        """Departure burn from LEO should dominate."""
        r = results["bielliptic_1"]
        assert r["dv_a_km_s"] > r["dv_b_km_s"]
        assert r["dv_a_km_s"] > r["dv_c_km_s"]


# ---------------------------------------------------------------------------
# J2 Pericenter Correction (Vallado p.895)
# ---------------------------------------------------------------------------
class TestJ2Correction:
    def test_delta_t(self, results):
        r = results["j2_correction_1"]
        assert r["delta_t_s"] == pytest.approx(2224141.0, rel=5e-2)

    def test_delta_v(self, results):
        r = results["j2_correction_1"]
        assert r["delta_v_km_s"] == pytest.approx(0.011782, rel=5e-2)

    def test_delta_t_positive(self, results):
        r = results["j2_correction_1"]
        assert r["delta_t_s"] > 0

    def test_delta_v_positive(self, results):
        r = results["j2_correction_1"]
        assert r["delta_v_km_s"] > 0

    def test_delta_t_order_of_magnitude(self, results):
        """Time between burns should be on the order of weeks."""
        r = results["j2_correction_1"]
        assert 1e6 < r["delta_t_s"] < 1e7


# ---------------------------------------------------------------------------
# Plane Change: Inclination change at GEO
# ---------------------------------------------------------------------------
class TestPlaneChange:
    def test_dv_value(self, results):
        r = results["plane_change_1"]
        assert r["dv_km_s"] == pytest.approx(1.5134, rel=5e-3)

    def test_dv_positive(self, results):
        r = results["plane_change_1"]
        assert r["dv_km_s"] > 0

    def test_dv_less_than_orbital_velocity(self, results):
        """Plane change dv should be less than full orbital velocity."""
        r = results["plane_change_1"]
        v_geo = math.sqrt(398600.4418 / 42164.0)
        assert r["dv_km_s"] < v_geo

    def test_dv_reasonable_for_28deg(self, results):
        """For a 28.5-deg change at GEO (~3 km/s), dv should be ~1.5 km/s."""
        r = results["plane_change_1"]
        assert 1.0 < r["dv_km_s"] < 2.0


# ---------------------------------------------------------------------------
# Mission Budget: Combined LEO-to-GEO with 28.5-degree plane change
# ---------------------------------------------------------------------------
class TestMissionBudget:
    def test_arrive_optimal(self, results):
        """For LEO->GEO, plane change at arrival (lower velocity) should be optimal."""
        r = results["mission_budget_1"]
        assert r["optimal_strategy"] == "arrive"

    def test_arrive_less_than_depart(self, results):
        r = results["mission_budget_1"]
        assert r["dv_arrive_total_km_s"] < r["dv_depart_total_km_s"]

    def test_dv_optimal_matches_strategy(self, results):
        r = results["mission_budget_1"]
        if r["optimal_strategy"] == "arrive":
            assert r["dv_optimal_km_s"] == pytest.approx(
                r["dv_arrive_total_km_s"], rel=1e-6
            )
        else:
            assert r["dv_optimal_km_s"] == pytest.approx(
                r["dv_depart_total_km_s"], rel=1e-6
            )

    def test_dv_arrive_total(self, results):
        r = results["mission_budget_1"]
        assert r["dv_arrive_total_km_s"] == pytest.approx(4.294, rel=1e-2)

    def test_dv_depart_total(self, results):
        r = results["mission_budget_1"]
        assert r["dv_depart_total_km_s"] == pytest.approx(6.516, rel=1e-2)

    def test_both_totals_positive(self, results):
        r = results["mission_budget_1"]
        assert r["dv_arrive_total_km_s"] > 0
        assert r["dv_depart_total_km_s"] > 0

    def test_dv_greater_than_pure_hohmann(self, results):
        """Total dv with plane change should exceed pure Hohmann."""
        r = results["mission_budget_1"]
        hohmann = results["hohmann_1"]
        assert r["dv_arrive_total_km_s"] > hohmann["dv_total_km_s"]

    def test_depart_option_contains_hohmann_arrival_component(self, results):
        """When plane change is at departure, the arrival burn should match
        the pure Hohmann arrival burn magnitude (approximately)."""
        r = results["mission_budget_1"]
        hohmann = results["hohmann_1"]
        assert r["dv_depart_total_km_s"] > hohmann["dv_total_km_s"]

    def test_optimal_less_than_sum_of_separate(self, results):
        """Combined burn should be cheaper than doing Hohmann + separate plane change."""
        r = results["mission_budget_1"]
        hohmann = results["hohmann_1"]
        plane = results["plane_change_1"]
        separate_total = hohmann["dv_total_km_s"] + plane["dv_km_s"]
        assert r["dv_arrive_total_km_s"] < separate_total


# ---------------------------------------------------------------------------
# Report CSV validation
# ---------------------------------------------------------------------------
class TestReport:
    def test_report_exists(self):
        assert os.path.isfile(REPORT_FILE), "report.csv does not exist"

    def test_report_has_header(self):
        with open(REPORT_FILE) as f:
            header = f.readline().strip()
        assert "mission_id" in header, f"Header missing 'mission_id': {header}"
        assert "field" in header, f"Header missing 'field': {header}"
        assert "expected" in header, f"Header missing 'expected': {header}"
        assert "tol_rel" in header, f"Header missing 'tol_rel': {header}"
        assert "tol_abs" in header, f"Header missing 'tol_abs': {header}"

    def test_report_row_count(self):
        """golden_values has 33 rows; report should have header + 33 data rows."""
        with open(REPORT_FILE) as f:
            lines = [line.strip() for line in f if line.strip()]
        assert len(lines) >= 34, f"Expected >= 34 lines (header + 33 data), got {len(lines)}"

    def test_report_contains_all_missions(self):
        """Report should contain rows for all mission IDs."""
        with open(REPORT_FILE) as f:
            content = f.read()
        expected_ids = [
            "rv2coe_1", "coe2rv_1", "lambert_1", "lambert_2",
            "hohmann_1", "bielliptic_1", "j2_correction_1",
            "plane_change_1", "mission_budget_1",
        ]
        for mid in expected_ids:
            assert mid in content, f"Report missing mission {mid}"


# ---------------------------------------------------------------------------
# Cross-scenario consistency checks
# ---------------------------------------------------------------------------
class TestCrossScenarioConsistency:
    def test_all_missions_present(self, results):
        expected_ids = [
            "rv2coe_1", "coe2rv_1", "lambert_1", "lambert_2",
            "hohmann_1", "bielliptic_1", "j2_correction_1",
            "plane_change_1", "mission_budget_1",
        ]
        for mid in expected_ids:
            assert mid in results, f"Missing mission {mid} in results"

    def test_bielliptic_cheaper_than_hohmann_for_high_ratio(self, results):
        """For r_f/r_i ~ 58, bielliptic should be cheaper than Hohmann to same orbit."""
        b = results["bielliptic_1"]
        k = 398600.4418
        r_i, r_f = 6569.48071, 382688.1366
        a_t = (r_i + r_f) / 2.0
        dv_h = (abs(math.sqrt(2*k/r_i - k/a_t) - math.sqrt(k/r_i))
                + abs(math.sqrt(k/r_f) - math.sqrt(2*k/r_f - k/a_t)))
        assert b["dv_total_km_s"] < dv_h
