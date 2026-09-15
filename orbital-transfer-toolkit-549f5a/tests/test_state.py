
import subprocess
import json
import os
import sqlite3
import sys

import numpy as np
import pytest

sys.path.insert(0, "/app")
from astro import (
    rv2coe,
    coe2rv,
    propagate_cowell,
    lambert_solve,
    hohmann_transfer,
    j2_perturbation,
    parse_oem,
)

MU_EARTH = 398600.4418  # km^3/s^2
J2_EARTH = 0.00108263
R_EARTH = 6378.137  # km


class TestRV2COE:
    """Tests for state-vector to classical orbital elements conversion."""

    def test_curtis_example_43(self):
        """Verify against Curtis 'Orbital Mechanics' Example 4.3."""
        r = np.array([-6045.0, -3490.0, 2500.0])
        v = np.array([-3.457, 6.618, 2.533])
        p, ecc, inc, raan, argp, nu = rv2coe(MU_EARTH, r, v)

        assert abs(p - 8530.47) < 0.5, f"p={p}"
        assert abs(ecc - 0.17121) < 1e-3, f"ecc={ecc}"
        assert abs(np.degrees(inc) - 153.249) < 0.05, f"inc={np.degrees(inc)}"
        assert abs(np.degrees(raan) - 255.279) < 0.05, f"raan={np.degrees(raan)}"
        assert abs(np.degrees(argp) - 20.068) < 0.2, f"argp={np.degrees(argp)}"
        assert abs(np.degrees(nu) - 28.446) < 0.2, f"nu={np.degrees(nu)}"

    def test_roundtrip(self):
        """rv -> coe -> rv must round-trip to high precision."""
        r = np.array([-6045.0, -3490.0, 2500.0])
        v = np.array([-3.457, 6.618, 2.533])
        p, ecc, inc, raan, argp, nu = rv2coe(MU_EARTH, r, v)
        r2, v2 = coe2rv(MU_EARTH, p, ecc, inc, raan, argp, nu)
        np.testing.assert_allclose(r, r2, atol=1e-6, err_msg="Position roundtrip")
        np.testing.assert_allclose(v, v2, atol=1e-8, err_msg="Velocity roundtrip")

    def test_second_orbit(self):
        """Another orbit for element extraction correctness."""
        r = np.array([859.07256, -4137.20368, 5295.56871])
        v = np.array([7.37289205, 2.08223573, 0.43999979])
        p, ecc, inc, raan, argp, nu = rv2coe(MU_EARTH, r, v)
        r2, v2 = coe2rv(MU_EARTH, p, ecc, inc, raan, argp, nu)
        np.testing.assert_allclose(r, r2, atol=1e-6)
        np.testing.assert_allclose(v, v2, atol=1e-8)


class TestCOE2RV:
    """Tests for classical orbital elements to state vector."""

    def test_circular_orbit(self):
        """Circular orbit at 7000 km radius."""
        a = 7000.0
        p = a
        r, v = coe2rv(MU_EARTH, p, 0.0, 0.0, 0.0, 0.0, 0.0)
        assert abs(np.linalg.norm(r) - a) < 1e-10, "Radius mismatch"
        expected_v = np.sqrt(MU_EARTH / a)
        assert abs(np.linalg.norm(v) - expected_v) < 1e-10, "Velocity mismatch"

    def test_eccentric_orbit(self):
        """Eccentric orbit element recovery."""
        p = 10000.0
        ecc = 0.3
        inc = np.radians(45.0)
        raan = np.radians(60.0)
        argp = np.radians(120.0)
        nu = np.radians(30.0)
        r, v = coe2rv(MU_EARTH, p, ecc, inc, raan, argp, nu)
        p2, ecc2, inc2, raan2, argp2, nu2 = rv2coe(MU_EARTH, r, v)
        assert abs(p2 - p) < 1e-6, f"p: {p2} vs {p}"
        assert abs(ecc2 - ecc) < 1e-8, f"ecc: {ecc2} vs {ecc}"
        assert abs(inc2 - inc) < 1e-8, f"inc: {inc2} vs {inc}"


class TestLambert:
    """Tests for Lambert problem solver."""

    def test_curtis_example_52(self):
        """Curtis Example 5.2: 3D transfer."""
        r1 = np.array([5000.0, 10000.0, 2100.0])
        r2 = np.array([-14600.0, 2500.0, 7000.0])
        tof = 3600.0
        sols = lambert_solve(MU_EARTH, r1, r2, tof, M=0, prograde=True)
        assert len(sols) == 1, f"Expected 1 solution, got {len(sols)}"
        v1, v2 = sols[0]
        np.testing.assert_allclose(
            v1, [-5.9925, 1.9254, 3.2456], atol=0.02, err_msg="v1"
        )
        np.testing.assert_allclose(
            v2, [-3.3125, -4.1966, -0.3853], atol=0.02, err_msg="v2"
        )

    def test_single_rev_planar(self):
        """Planar single-revolution case from poliastro notebook."""
        r1 = np.array([15945.34, 0.0, 0.0])
        r2 = np.array([12214.83399, 10249.46731, 0.0])
        tof = 76.0 * 60.0
        sols = lambert_solve(MU_EARTH, r1, r2, tof, M=0, prograde=True)
        assert len(sols) == 1
        v1, v2 = sols[0]
        np.testing.assert_allclose(
            v1, [2.058925, 2.915956, 0.0], atol=0.02, err_msg="v1 planar"
        )
        np.testing.assert_allclose(
            v2, [-3.451569, 0.910301, 0.0], atol=0.02, err_msg="v2 planar"
        )

    def test_multi_revolution_m0(self):
        """Multi-revolution test case, M=0 baseline."""
        r1 = np.array([22592.145603, -1599.915239, -19783.950506])
        r2 = np.array([1922.067697, 4054.157051, -8925.727465])
        tof = 36000.0
        sols = lambert_solve(MU_EARTH, r1, r2, tof, M=0, prograde=True)
        assert len(sols) == 1
        v1, v2 = sols[0]
        np.testing.assert_allclose(
            v1, [2.000652697, 0.387688615, -2.666947760], atol=0.01
        )
        np.testing.assert_allclose(
            v2, [-3.79246619, -1.77707641, 6.85681439], atol=0.01
        )

    def test_multi_revolution_m1(self):
        """Multi-revolution test case, M=1 must produce two distinct solutions."""
        r1 = np.array([22592.145603, -1599.915239, -19783.950506])
        r2 = np.array([1922.067697, 4054.157051, -8925.727465])
        tof = 36000.0
        sols = lambert_solve(MU_EARTH, r1, r2, tof, M=1, prograde=True)
        assert len(sols) == 2, f"Expected 2 M=1 solutions, got {len(sols)}"
        v1_a, v2_a = sols[0]
        v1_b, v2_b = sols[1]
        assert np.linalg.norm(v2_a - v2_b) > 0.1, "M=1 solutions not distinct"
        expected_v2_low = np.array([-4.18334626, -1.13262727, 6.13307091])
        expected_v2_high = np.array([-5.53841370, 0.01822220, 5.49641054])
        diffs = []
        for ev in [expected_v2_low, expected_v2_high]:
            d = min(np.linalg.norm(v2_a - ev), np.linalg.norm(v2_b - ev))
            diffs.append(d)
        assert all(d < 0.05 for d in diffs), f"M=1 solutions don't match expected: diffs={diffs}"


class TestCowell:
    """Tests for Cowell orbit propagation."""

    def test_keplerian_iss(self):
        """ISS-like orbit: 2.5 periods of pure Keplerian propagation."""
        r0 = np.array([859.07256, -4137.20368, 5295.56871])
        v0 = np.array([7.37289205, 2.08223573, 0.43999979])
        tof = 13892.42425291
        rf, vf = propagate_cowell(MU_EARTH, r0, v0, tof, rtol=1e-12)
        expected_rf = np.array([-835.92108, 4151.60693, -5303.60428])
        np.testing.assert_allclose(rf, expected_rf, atol=0.05, err_msg="ISS position after 2.5T")
        v0_mag = np.linalg.norm(v0)
        vf_mag = np.linalg.norm(vf)
        E0 = v0_mag**2 / 2 - MU_EARTH / np.linalg.norm(r0)
        Ef = vf_mag**2 / 2 - MU_EARTH / np.linalg.norm(rf)
        assert abs(Ef - E0) / abs(E0) < 1e-8, f"Energy not conserved: E0={E0}, Ef={Ef}"
        h0 = np.linalg.norm(np.cross(r0, v0))
        hf = np.linalg.norm(np.cross(rf, vf))
        assert abs(hf - h0) / h0 < 1e-8, f"Angular momentum not conserved: h0={h0}, hf={hf}"

    def test_j2_raan_precession(self):
        """J2 perturbation causes RAAN to precess for inclined LEO orbit."""
        r0 = np.array([-2384.46, 5729.01, 3050.46])
        v0 = np.array([-7.36138, -2.98997, 1.64354])
        tof = 172800.0

        def j2_pert(t, state, mu):
            return j2_perturbation(t, state, mu, J2_EARTH, R_EARTH)

        p0, ecc0, inc0, raan0, argp0, nu0 = rv2coe(MU_EARTH, r0, v0)

        rf, vf = propagate_cowell(
            MU_EARTH, r0, v0, tof, perturbation=j2_pert, rtol=1e-10
        )

        pf, eccf, incf, raanf, argpf, nuf = rv2coe(MU_EARTH, rf, vf)

        raan_change = raanf - raan0
        if raan_change > np.pi:
            raan_change -= 2 * np.pi
        elif raan_change < -np.pi:
            raan_change += 2 * np.pi
        assert raan_change < 0, f"RAAN should decrease for prograde; got {raan_change} rad"
        assert abs(raan_change) > 0.02, f"RAAN drift too small: {raan_change} rad"
        assert abs(raan_change) < 0.5, f"RAAN drift implausibly large: {raan_change} rad"

        a0 = p0 / (1 - ecc0**2)
        af = pf / (1 - eccf**2)
        assert abs(af - a0) / a0 < 0.005, f"SMA not conserved: a0={a0}, af={af}"

    def test_edelbaum_tangent_thrust(self):
        """Edelbaum validation: constant tangent thrust on circular orbit."""
        a0 = R_EARTH + 500.0
        v0_mag = np.sqrt(MU_EARTH / a0)
        r0 = np.array([a0, 0.0, 0.0])
        v0 = np.array([0.0, v0_mag, 0.0])

        period = 2 * np.pi * np.sqrt(a0**3 / MU_EARTH)
        tof = 20 * period

        accel_mag = 1e-7

        def tangent_accel(t, state, mu):
            vel = state[3:]
            speed = np.linalg.norm(vel)
            if speed < 1e-15:
                return np.zeros(3)
            return accel_mag * vel / speed

        rf, vf = propagate_cowell(
            MU_EARTH, r0, v0, tof, perturbation=tangent_accel, rtol=1e-10
        )

        vf_mag = np.linalg.norm(vf)
        rf_mag = np.linalg.norm(rf)
        energy_f = vf_mag**2 / 2 - MU_EARTH / rf_mag
        af = -MU_EARTH / (2 * energy_f)

        da_a0 = (af - a0) / a0
        dv_v0 = abs(vf_mag - v0_mag) / v0_mag

        assert da_a0 > 0, f"SMA should increase; da/a0={da_a0}"
        assert abs(da_a0 - 2 * dv_v0) / da_a0 < 0.05, (
            f"Edelbaum mismatch: da/a0={da_a0:.6e}, 2*dv/v0={2*dv_v0:.6e}"
        )


class TestHohmann:
    """Tests for Hohmann transfer calculator."""

    def test_leo_to_geo(self):
        """Hohmann from 800 km LEO to GEO."""
        r_i = R_EARTH + 800.0
        r_f = 42164.0
        dv1, dv2, tof = hohmann_transfer(MU_EARTH, r_i, r_f)

        v_i = np.sqrt(MU_EARTH / r_i)
        v_f = np.sqrt(MU_EARTH / r_f)
        a_t = (r_i + r_f) / 2
        v_t_dep = np.sqrt(MU_EARTH * (2 / r_i - 1 / a_t))
        v_t_arr = np.sqrt(MU_EARTH * (2 / r_f - 1 / a_t))

        expected_dv1 = abs(v_t_dep - v_i)
        expected_dv2 = abs(v_f - v_t_arr)
        expected_tof = np.pi * np.sqrt(a_t**3 / MU_EARTH)

        assert abs(dv1 - expected_dv1) < 0.001, f"dv1: {dv1} vs {expected_dv1}"
        assert abs(dv2 - expected_dv2) < 0.001, f"dv2: {dv2} vs {expected_dv2}"
        assert abs(tof - expected_tof) < 1.0, f"tof: {tof} vs {expected_tof}"
        assert 3.0 < dv1 + dv2 < 5.0, f"Total dv out of range: {dv1+dv2}"

    def test_small_transfer(self):
        """Hohmann between close circular orbits."""
        r_i = 7000.0
        r_f = 7200.0
        dv1, dv2, tof = hohmann_transfer(MU_EARTH, r_i, r_f)
        assert dv1 > 0 and dv2 > 0
        assert tof > 0
        assert dv1 + dv2 < 0.5


class TestJ2Perturbation:
    """Tests for J2 perturbation acceleration."""

    def test_equatorial_symmetry(self):
        """At equator (z=0), J2 accel is purely radial for radially-aligned r."""
        state = np.array([7000.0, 0.0, 0.0, 0.0, 7.5, 0.0])
        a = j2_perturbation(0, state, MU_EARTH, J2_EARTH, R_EARTH)
        assert abs(a[1]) < 1e-15, f"a_y should be 0 at equator, got {a[1]}"
        assert abs(a[2]) < 1e-15, f"a_z should be 0 at equator, got {a[2]}"
        assert abs(a[0]) > 1e-8, f"a_x should be nonzero at equator"
        assert a[0] < 0, "J2 at equator should push radially inward for x-aligned"

    def test_polar_acceleration(self):
        """At pole (r along z), J2 accel is purely along z."""
        state = np.array([0.0, 0.0, 7000.0, 0.0, 7.5, 0.0])
        a = j2_perturbation(0, state, MU_EARTH, J2_EARTH, R_EARTH)
        assert abs(a[0]) < 1e-15, f"a_x should be 0 at pole, got {a[0]}"
        assert abs(a[1]) < 1e-15, f"a_y should be 0 at pole, got {a[1]}"
        assert abs(a[2]) > 1e-8, f"a_z should be nonzero at pole"

    def test_magnitude_order(self):
        """J2 acceleration should be ~1e-5 km/s^2 at 7000 km."""
        state = np.array([7000.0, 0.0, 0.0, 0.0, 7.5, 0.0])
        a = j2_perturbation(0, state, MU_EARTH, J2_EARTH, R_EARTH)
        mag = np.linalg.norm(a)
        assert 1e-6 < mag < 1e-3, f"J2 magnitude out of expected range: {mag}"


class TestParseOEM:
    """Tests for CCSDS OEM ephemeris file parsing."""

    def test_parse_target_ephemeris(self):
        """Parse the mission target ephemeris OEM file."""
        entries = parse_oem("/app/mission_data/target_ephemeris.oem")
        assert len(entries) == 7, f"Expected 7 ephemeris entries, got {len(entries)}"

        # First entry is at epoch 0
        e0 = entries[0]
        assert abs(e0["epoch_s"]) < 1e-6, f"First epoch_s should be 0, got {e0['epoch_s']}"
        assert abs(e0["x"] - 42164.0) < 0.01, f"x mismatch: {e0['x']}"
        assert abs(e0["y"]) < 0.01, f"y should be ~0: {e0['y']}"
        assert abs(e0["z"]) < 0.01, f"z should be ~0: {e0['z']}"
        assert abs(e0["vx"]) < 0.001, f"vx should be ~0: {e0['vx']}"
        assert abs(e0["vy"] - 3.0747) < 0.001, f"vy mismatch: {e0['vy']}"
        assert abs(e0["vz"]) < 0.001, f"vz should be ~0: {e0['vz']}"

    def test_oem_epoch_offsets(self):
        """Verify epoch_s values are correctly computed as offsets from first entry."""
        entries = parse_oem("/app/mission_data/target_ephemeris.oem")
        # Entries are at 0h, 2h, 4h, 6h, 8h, 10h, 12h
        expected_offsets = [0, 7200, 14400, 21600, 28800, 36000, 43200]
        for i, (entry, expected) in enumerate(zip(entries, expected_offsets)):
            assert abs(entry["epoch_s"] - expected) < 1.0, (
                f"Entry {i}: epoch_s={entry['epoch_s']}, expected={expected}"
            )

    def test_oem_all_entries_have_keys(self):
        """All parsed entries must have the required keys."""
        entries = parse_oem("/app/mission_data/target_ephemeris.oem")
        required = {"epoch_s", "x", "y", "z", "vx", "vy", "vz"}
        for i, entry in enumerate(entries):
            assert required.issubset(entry.keys()), (
                f"Entry {i} missing keys: {required - set(entry.keys())}"
            )

    def test_oem_later_entries_have_nonzero_y(self):
        """Later entries should have nonzero y (orbit is circular, object moves)."""
        entries = parse_oem("/app/mission_data/target_ephemeris.oem")
        assert abs(entries[1]["y"]) > 1000, (
            f"Second entry y should be large, got {entries[1]['y']}"
        )


class TestFilteredObservations:
    """Tests for tracking observation filtering."""

    def test_filtered_obs_exists(self):
        """filtered_obs.json must exist."""
        assert os.path.exists("/app/filtered_obs.json"), "filtered_obs.json not found"

    def test_filtered_obs_count(self):
        """Must contain exactly 12 accepted observations (15 total minus 3 rejected)."""
        with open("/app/filtered_obs.json") as f:
            obs = json.load(f)
        assert isinstance(obs, list), "filtered_obs.json must be a JSON array"
        assert len(obs) == 12, f"Expected 12 clean observations, got {len(obs)}"

    def test_filtered_obs_schema(self):
        """Each observation must have the required keys with valid values."""
        with open("/app/filtered_obs.json") as f:
            obs = json.load(f)
        required_keys = {"time_s", "station_id", "range_km", "azimuth_deg", "elevation_deg"}
        for entry in obs:
            assert required_keys.issubset(entry.keys()), (
                f"Missing keys: {required_keys - set(entry.keys())}"
            )
            assert entry["range_km"] > 0, f"range_km must be positive: {entry}"
            assert 0 <= entry["elevation_deg"] <= 90, (
                f"elevation_deg out of range: {entry['elevation_deg']}"
            )

    def test_filtered_obs_outliers_excluded(self):
        """Rejected observations must not appear in filtered output."""
        with open("/app/filtered_obs.json") as f:
            obs = json.load(f)
        ranges = [e["range_km"] for e in obs]
        # These are the range values of the 3 rejected observations
        assert 9999.999 not in ranges, "Outlier range=9999.999 should be filtered"
        assert 3456.789 not in ranges, "Outlier range=3456.789 should be filtered"
        assert 12345.678 not in ranges, "Outlier range=12345.678 should be filtered"

    def test_filtered_obs_time_reference(self):
        """time_s must be relative to the stated reference epoch (midnight)."""
        with open("/app/filtered_obs.json") as f:
            obs = json.load(f)
        # First accepted observation is at 00:05:12 = 312 seconds from midnight
        assert abs(obs[0]["time_s"] - 312.0) < 1.0, (
            f"First time_s should be ~312, got {obs[0]['time_s']}"
        )
        # Last accepted observation is at 03:00:00 = 10800 seconds
        assert abs(obs[-1]["time_s"] - 10800.0) < 1.0, (
            f"Last time_s should be ~10800, got {obs[-1]['time_s']}"
        )

    def test_filtered_obs_stations(self):
        """Filtered observations should come from known stations."""
        with open("/app/filtered_obs.json") as f:
            obs = json.load(f)
        valid_stations = {"GSN01", "GSN02", "GSN03"}
        for entry in obs:
            assert entry["station_id"] in valid_stations, (
                f"Unknown station: {entry['station_id']}"
            )


class TestAnalyzeCLI:
    """Integration test for the transfer analysis CLI pipeline."""

    def test_transfer_analysis_pipeline(self):
        """Run the full pipeline with the mission scenario."""
        results_path = "/app/results.json"
        if os.path.exists(results_path):
            os.remove(results_path)

        result = subprocess.run(
            ["python3", "/app/analyze.py", "/app/mission_data/scenario.toml"],
            capture_output=True,
            text=True,
            timeout=180,
            cwd="/app",
        )
        assert result.returncode == 0, (
            f"CLI failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert os.path.exists(results_path), "results.json not created"

        with open(results_path) as f:
            results = json.load(f)

        assert "grid" in results, "Missing 'grid' key"
        assert "optimal" in results, "Missing 'optimal' key"
        assert len(results["grid"]) > 0, "Grid is empty"

        opt = results["optimal"]
        assert "dep_s" in opt, "Missing dep_s in optimal"
        assert "tof_s" in opt, "Missing tof_s in optimal"
        assert "dv_km_s" in opt, "Missing dv_km_s in optimal"
        assert opt["dv_km_s"] > 0, f"dv must be positive, got {opt['dv_km_s']}"
        assert opt["dv_km_s"] < 15.0, f"dv implausibly large: {opt['dv_km_s']}"

        # Optimal must be the true minimum of the grid
        min_dv = min(e["dv_km_s"] for e in results["grid"])
        assert abs(opt["dv_km_s"] - min_dv) < 1e-10, (
            f"Optimal dv {opt['dv_km_s']} != grid min {min_dv}"
        )

        # All grid entries must have required keys and positive dv
        for entry in results["grid"]:
            assert "dep_s" in entry
            assert "tof_s" in entry
            assert "dv_km_s" in entry
            assert entry["dv_km_s"] > 0


class TestMakefilePipeline:
    """Tests for Makefile-based build pipeline and SQLite integration."""

    def test_makefile_exists(self):
        """Makefile must exist at /app/Makefile."""
        assert os.path.exists("/app/Makefile"), "Makefile not found at /app/Makefile"

    def test_make_all_succeeds(self):
        """make all must succeed without errors."""
        result = subprocess.run(
            ["make", "-C", "/app", "all"],
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, (
            f"make all failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_make_db_rebuilds(self):
        """Removing mission.db and running make db must recreate it."""
        if os.path.exists("/app/mission.db"):
            os.remove("/app/mission.db")
        result = subprocess.run(
            ["make", "-C", "/app", "db"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"make db failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert os.path.exists("/app/mission.db"), "mission.db not created by make db"

    def test_make_query_rebuilds(self):
        """Removing optimal_report.txt and running make query must recreate it."""
        if os.path.exists("/app/optimal_report.txt"):
            os.remove("/app/optimal_report.txt")
        result = subprocess.run(
            ["make", "-C", "/app", "query"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"make query failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert os.path.exists("/app/optimal_report.txt"), "optimal_report.txt not created"

    def test_grid_results_table_schema(self):
        """mission.db must have grid_results table with dep_s, tof_s, dv_km_s."""
        conn = sqlite3.connect("/app/mission.db")
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='grid_results'"
        )
        assert cur.fetchone() is not None, "grid_results table not found in mission.db"
        cur.execute("PRAGMA table_info(grid_results)")
        columns = {row[1] for row in cur.fetchall()}
        assert {"dep_s", "tof_s", "dv_km_s"}.issubset(columns), (
            f"Missing required columns; found: {columns}"
        )
        conn.close()

    def test_db_row_count_matches_json(self):
        """Row count in grid_results must equal results.json grid length."""
        with open("/app/results.json") as f:
            results = json.load(f)
        conn = sqlite3.connect("/app/mission.db")
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM grid_results")
        db_count = cur.fetchone()[0]
        conn.close()
        assert db_count == len(results["grid"]), (
            f"DB has {db_count} rows, JSON grid has {len(results['grid'])}"
        )

    def test_db_min_dv_matches_optimal(self):
        """SQL MIN(dv_km_s) must match results.json optimal."""
        with open("/app/results.json") as f:
            results = json.load(f)
        conn = sqlite3.connect("/app/mission.db")
        cur = conn.cursor()
        cur.execute("SELECT MIN(dv_km_s) FROM grid_results")
        db_min = cur.fetchone()[0]
        conn.close()
        assert abs(db_min - results["optimal"]["dv_km_s"]) < 1e-6, (
            f"DB min dv {db_min} != JSON optimal {results['optimal']['dv_km_s']}"
        )

    def test_optimal_report_format(self):
        """optimal_report.txt must be pipe-delimited with header and one data line."""
        with open("/app/optimal_report.txt") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        assert len(lines) >= 2, f"Expected header + data, got {len(lines)} lines"
        header = lines[0]
        assert "dep_s" in header and "tof_s" in header and "dv_km_s" in header, (
            f"Header missing required fields: {header}"
        )
        data = lines[1].split("|")
        assert len(data) >= 3, f"Data line must have 3+ pipe-separated values, got {len(data)}"
        for val in data[:3]:
            float(val.strip())  # must be numeric

    def test_optimal_report_matches_json(self):
        """Report optimal values must match results.json."""
        with open("/app/results.json") as f:
            results = json.load(f)
        with open("/app/optimal_report.txt") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        data = lines[1].split("|")
        assert abs(float(data[0].strip()) - results["optimal"]["dep_s"]) < 1e-4, (
            f"dep_s mismatch: report={data[0]}, json={results['optimal']['dep_s']}"
        )
        assert abs(float(data[1].strip()) - results["optimal"]["tof_s"]) < 1e-4, (
            f"tof_s mismatch: report={data[1]}, json={results['optimal']['tof_s']}"
        )
        assert abs(float(data[2].strip()) - results["optimal"]["dv_km_s"]) < 1e-4, (
            f"dv_km_s mismatch: report={data[2]}, json={results['optimal']['dv_km_s']}"
        )
