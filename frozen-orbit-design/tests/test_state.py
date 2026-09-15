
"""
Tests for frozen sun-synchronous repeat ground track orbit design pipeline.
Verifies database interaction, jq validation, physics constraints, and self-consistency.
No pre-computed answers are embedded — all checks are physics-based or schema-based.
"""

import json
import math
import os
import sqlite3
import subprocess
import pytest

# Expected constants from JGM3 gravity model (the active profile's model)
EXPECTED_MODEL = "JGM3"
MU = 398600.4418
R_E = 6378.137
J2 = 0.00108262668
J3 = -2.53265649e-6
OMEGA_E = 7.2921159e-5

# Expected mission profile parameters (active, highest priority)
Q = 185
P = 13
TARGET_RAAN_RATE_DEG_DAY = 0.9856473
TARGET_RAAN_RATE_RAD_S = math.radians(TARGET_RAAN_RATE_DEG_DAY) / 86400.0
ALT_MIN = 780.0
ALT_MAX = 820.0


@pytest.fixture
def results():
    assert os.path.exists("/app/results.json"), "Results file /app/results.json not found"
    with open("/app/results.json") as f:
        data = json.load(f)
    return data


@pytest.fixture
def query_results():
    assert os.path.exists("/app/query_results.json"), \
        "Query results file /app/query_results.json not found"
    with open("/app/query_results.json") as f:
        data = json.load(f)
    return data


class TestDatabaseQuery:
    """Verify the agent queried the correct gravity model and mission profile."""

    def test_correct_gravity_model(self, query_results):
        assert query_results["gravity_model"] == EXPECTED_MODEL, \
            f"Expected gravity model {EXPECTED_MODEL}, got {query_results['gravity_model']}"

    def test_correct_j2(self, query_results):
        assert abs(query_results["J2"] - J2) < 1e-10, \
            f"J2 mismatch: expected {J2}, got {query_results['J2']}"

    def test_correct_j3(self, query_results):
        assert abs(query_results["J3"] - J3) < 1e-12, \
            f"J3 mismatch: expected {J3}, got {query_results['J3']}"

    def test_correct_repeat_cycle(self, query_results):
        assert query_results["repeat_revolutions"] == Q, \
            f"Expected Q={Q}, got {query_results['repeat_revolutions']}"
        assert query_results["repeat_days"] == P, \
            f"Expected P={P}, got {query_results['repeat_days']}"

    def test_correct_raan_rate(self, query_results):
        assert abs(query_results["target_raan_rate_deg_day"] - TARGET_RAAN_RATE_DEG_DAY) < 1e-6

    def test_correct_mu(self, query_results):
        assert abs(query_results["mu_km3_s2"] - MU) < 0.01

    def test_correct_radius(self, query_results):
        assert abs(query_results["equatorial_radius_km"] - R_E) < 0.01

    def test_correct_rotation_rate(self, query_results):
        assert abs(query_results["rotation_rate_rad_s"] - OMEGA_E) < 1e-10


class TestDatabaseWrite:
    """Verify the agent wrote computed results back to the database."""

    def test_computed_orbits_table_exists(self):
        conn = sqlite3.connect("/app/orbit_data.db")
        c = conn.cursor()
        c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='computed_orbits'"
        )
        row = c.fetchone()
        conn.close()
        assert row is not None, "Table 'computed_orbits' not found in database"

    def test_computed_orbits_has_data(self):
        conn = sqlite3.connect("/app/orbit_data.db")
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM computed_orbits WHERE profile_id = 1")
        count = c.fetchone()[0]
        conn.close()
        assert count >= 1, "No rows found in computed_orbits for profile_id=1"

    def test_computed_orbits_has_required_columns(self):
        conn = sqlite3.connect("/app/orbit_data.db")
        c = conn.cursor()
        c.execute("PRAGMA table_info(computed_orbits)")
        columns = {row[1] for row in c.fetchall()}
        conn.close()
        required = {
            "profile_id", "semi_major_axis_km", "eccentricity",
            "inclination_deg", "nodal_period_s", "computed_at"
        }
        missing = required - columns
        assert not missing, f"Missing columns in computed_orbits: {missing}"

    def test_computed_orbit_matches_results(self, results):
        conn = sqlite3.connect("/app/orbit_data.db")
        c = conn.cursor()
        c.execute("""
            SELECT semi_major_axis_km, eccentricity, inclination_deg, nodal_period_s
            FROM computed_orbits
            WHERE profile_id = 1
            ORDER BY computed_at DESC
            LIMIT 1
        """)
        row = c.fetchone()
        conn.close()
        assert row is not None, "No computed orbit found for profile_id=1"
        assert abs(row[0] - results["semi_major_axis_km"]) < 0.01, \
            "semi_major_axis_km mismatch between DB and JSON"
        assert abs(row[1] - results["eccentricity"]) < 1e-6, \
            "eccentricity mismatch between DB and JSON"
        assert abs(row[2] - results["inclination_deg"]) < 0.01, \
            "inclination_deg mismatch between DB and JSON"
        assert abs(row[3] - results["nodal_period_s"]) < 0.1, \
            "nodal_period_s mismatch between DB and JSON"


class TestJqValidation:
    """Verify the output passes the provided jq validation filter."""

    def test_jq_filter_passes(self):
        result = subprocess.run(
            ["jq", "-e", "-f", "/app/validate_output.jq", "/app/results.json"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, \
            f"jq validation failed with stderr: {result.stderr}"


class TestFieldsPresent:
    """All required output fields must exist in the results."""

    REQUIRED_FIELDS = [
        "semi_major_axis_km", "eccentricity", "inclination_deg",
        "argument_of_perigee_deg", "nodal_period_s", "ground_track_spacing_km",
        "max_altitude_variation_m", "altitude_at_equator_ascending_km",
        "sun_synchronous_raan_rate_deg_day",
    ]

    def test_all_fields_present(self, results):
        for field in self.REQUIRED_FIELDS:
            assert field in results, f"Missing required field: {field}"
            assert isinstance(results[field], (int, float)), \
                f"Field {field} must be numeric, got {type(results[field])}"


class TestAltitudeBounds:
    """Both periapsis and apoapsis must lie within the specified altitude band."""

    def test_periapsis_above_minimum(self, results):
        a = results["semi_major_axis_km"]
        e = results["eccentricity"]
        h_peri = a * (1.0 - e) - R_E
        assert h_peri >= ALT_MIN - 1.0, \
            f"Periapsis altitude {h_peri:.3f} km below {ALT_MIN} km"

    def test_apoapsis_below_maximum(self, results):
        a = results["semi_major_axis_km"]
        e = results["eccentricity"]
        h_apo = a * (1.0 + e) - R_E
        assert h_apo <= ALT_MAX + 1.0, \
            f"Apoapsis altitude {h_apo:.3f} km above {ALT_MAX} km"


class TestSunSynchronous:
    """The J2 secular RAAN precession rate must match the sun-synchronous target."""

    def test_raan_rate_matches_target(self, results):
        a = results["semi_major_axis_km"]
        e = results["eccentricity"]
        i = math.radians(results["inclination_deg"])
        n = math.sqrt(MU / a ** 3)
        omega_dot_raan = (
            -1.5 * n * J2 * (R_E / a) ** 2 * math.cos(i) / (1.0 - e ** 2) ** 2
        )
        rate_deg_day = math.degrees(omega_dot_raan) * 86400.0
        assert abs(rate_deg_day - TARGET_RAAN_RATE_DEG_DAY) < 0.005, \
            f"RAAN rate {rate_deg_day:.6f} deg/day, expected {TARGET_RAAN_RATE_DEG_DAY}"

    def test_inclination_is_retrograde(self, results):
        i = results["inclination_deg"]
        assert 90.0 < i < 110.0, \
            f"Inclination {i:.4f} deg not in expected retrograde range"


class TestRepeatGroundTrack:
    """The nodal period must satisfy the Q-rev / P-day commensurability condition."""

    def test_commensurability(self, results):
        a = results["semi_major_axis_km"]
        e = results["eccentricity"]
        i = math.radians(results["inclination_deg"])
        n = math.sqrt(MU / a ** 3)
        omega_dot = (
            1.5 * n * J2 * (R_E / a) ** 2
            * (2.0 - 2.5 * math.sin(i) ** 2) / (1.0 - e ** 2) ** 2
        )
        M_dot = n * (
            1.0 + 1.5 * J2 * (R_E / a) ** 2
            * (1.0 - 1.5 * math.sin(i) ** 2) / (1.0 - e ** 2) ** 1.5
        )
        T_nodal = 2.0 * math.pi / (omega_dot + M_dot)
        omega_dot_raan = (
            -1.5 * n * J2 * (R_E / a) ** 2
            * math.cos(i) / (1.0 - e ** 2) ** 2
        )
        lhs = Q * T_nodal * (OMEGA_E - omega_dot_raan)
        rhs = 2.0 * math.pi * P
        rel_err = abs(lhs - rhs) / rhs
        assert rel_err < 1e-4, \
            f"Repeat ground track condition violated: relative error = {rel_err:.2e}"


class TestFrozenOrbit:
    """Eccentricity must match the J2+J3 frozen-orbit equilibrium value."""

    def test_frozen_eccentricity(self, results):
        a = results["semi_major_axis_km"]
        e = results["eccentricity"]
        i = math.radians(results["inclination_deg"])
        e_frozen = -J3 * R_E * math.sin(i) / (2.0 * J2 * a)
        tol = max(abs(e_frozen) * 0.02, 1e-5)
        assert abs(e - e_frozen) < tol, \
            f"Eccentricity {e:.8f} does not match frozen value {e_frozen:.8f}"

    def test_argument_of_perigee(self, results):
        omega = results["argument_of_perigee_deg"]
        assert abs(omega - 90.0) < 0.1, \
            f"Argument of perigee {omega} deg, expected 90.0 deg"

    def test_eccentricity_positive(self, results):
        e = results["eccentricity"]
        assert e > 0, f"Eccentricity must be positive, got {e}"


class TestSelfConsistency:
    """Reported derived quantities must be consistent with primary orbital elements."""

    def test_nodal_period_consistent(self, results):
        a = results["semi_major_axis_km"]
        e = results["eccentricity"]
        i = math.radians(results["inclination_deg"])
        T_reported = results["nodal_period_s"]
        n = math.sqrt(MU / a ** 3)
        omega_dot = (
            1.5 * n * J2 * (R_E / a) ** 2
            * (2.0 - 2.5 * math.sin(i) ** 2) / (1.0 - e ** 2) ** 2
        )
        M_dot = n * (
            1.0 + 1.5 * J2 * (R_E / a) ** 2
            * (1.0 - 1.5 * math.sin(i) ** 2) / (1.0 - e ** 2) ** 1.5
        )
        T_computed = 2.0 * math.pi / (omega_dot + M_dot)
        rel_err = abs(T_reported - T_computed) / T_computed
        assert rel_err < 1e-4, \
            f"Nodal period {T_reported:.4f}s inconsistent with computed {T_computed:.4f}s"

    def test_ground_track_spacing(self, results):
        spacing = results["ground_track_spacing_km"]
        expected = 2.0 * math.pi * R_E / Q
        assert abs(spacing - expected) < 0.5, \
            f"Ground track spacing {spacing:.2f} km, expected {expected:.2f} km"

    def test_altitude_variation(self, results):
        a = results["semi_major_axis_km"]
        e = results["eccentricity"]
        alt_var = results["max_altitude_variation_m"]
        expected = 2.0 * a * e * 1000.0
        assert abs(alt_var - expected) < max(expected * 0.02, 1.0), \
            f"Altitude variation {alt_var:.2f} m, expected {expected:.2f} m"

    def test_ascending_node_altitude(self, results):
        a = results["semi_major_axis_km"]
        e = results["eccentricity"]
        omega = math.radians(results["argument_of_perigee_deg"])
        h_asc = results["altitude_at_equator_ascending_km"]
        nu_asc = -omega
        r_asc = a * (1.0 - e ** 2) / (1.0 + e * math.cos(nu_asc))
        h_expected = r_asc - R_E
        assert abs(h_asc - h_expected) < 0.5, \
            f"Ascending node altitude {h_asc:.4f} km, expected {h_expected:.4f} km"

    def test_raan_rate_self_consistent(self, results):
        a = results["semi_major_axis_km"]
        e = results["eccentricity"]
        i = math.radians(results["inclination_deg"])
        reported = results["sun_synchronous_raan_rate_deg_day"]
        n = math.sqrt(MU / a ** 3)
        omega_dot_raan = (
            -1.5 * n * J2 * (R_E / a) ** 2 * math.cos(i) / (1.0 - e ** 2) ** 2
        )
        computed = math.degrees(omega_dot_raan) * 86400.0
        assert abs(reported - computed) < 0.001, \
            f"Reported RAAN rate {reported} inconsistent with computed {computed}"
