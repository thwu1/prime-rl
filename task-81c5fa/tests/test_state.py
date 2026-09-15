"""
Tests for Earth-Mars transfer trajectory design results.

Verifies output format, physical plausibility via known Earth-Mars
transfer ranges, mathematical self-consistency of derived quantities,
independent forward Kepler propagation, and cross-validation against
the JPL Horizons API.
"""

import json
import math
import os

import numpy as np
import pytest
import requests

# ---------- Reference constants ----------
MU_SUN = 1.32712440041279419e11   # km^3/s^2
MU_EARTH = 3.986004418e5          # km^3/s^2
MU_MARS = 4.282837e4              # km^3/s^2
R_EARTH = 6371.0                  # km
R_MARS = 3389.5                   # km
R_PARK_EARTH = R_EARTH + 200.0    # km
R_PARK_MARS = R_MARS + 300.0      # km
AU_KM = 149597870.7               # km

# JD bounds for the search windows (pre-computed)
#   2033-04-01 = JD 2463688.5
#   2033-09-30 = JD 2463870.5
#   2033-08-01 = JD 2463810.5
#   2034-07-31 = JD 2464174.5
DEP_JD_LO = 2463685.0
DEP_JD_HI = 2463875.0
ARR_JD_LO = 2463805.0
ARR_JD_HI = 2464180.0

RESULTS_FILE = '/app/trajectory.json'


@pytest.fixture(scope='module')
def results():
    with open(RESULTS_FILE) as f:
        return json.load(f)


@pytest.fixture(scope='module')
def opt(results):
    return results['optimal']


@pytest.fixture(scope='module')
def consts(results):
    return results['constants']


# ======================================================================
# Format & structure
# ======================================================================

class TestFormat:
    def test_file_exists(self):
        assert os.path.isfile(RESULTS_FILE), "trajectory.json not found"

    def test_valid_json(self):
        with open(RESULTS_FILE) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_has_optimal(self, results):
        assert 'optimal' in results

    def test_has_top5(self, results):
        assert 'top5' in results
        assert isinstance(results['top5'], list)
        assert len(results['top5']) >= 3

    def test_has_search_grid(self, results):
        assert 'search_grid' in results

    def test_has_constants(self, results):
        assert 'constants' in results

    def test_optimal_keys(self, opt):
        required = [
            'departure_date_jd', 'arrival_date_jd',
            'departure_date_cal', 'arrival_date_cal',
            'tof_days', 'c3_km2s2', 'vinf_dep_kms', 'vinf_arr_kms',
            'dv_dep_kms', 'dv_arr_kms', 'dv_total_kms',
            'transfer_a_km', 'transfer_e',
            'transfer_i_deg', 'transfer_raan_deg', 'transfer_argp_deg',
            'r1_km', 'v1_kms', 'r2_km', 'v2_kms',
            'v_earth_kms', 'v_mars_kms',
        ]
        for k in required:
            assert k in opt, f"Missing key: {k}"

    def test_scalar_types(self, opt):
        scalars = [
            'tof_days', 'c3_km2s2', 'vinf_dep_kms', 'vinf_arr_kms',
            'dv_dep_kms', 'dv_arr_kms', 'dv_total_kms',
            'transfer_a_km', 'transfer_e',
            'transfer_i_deg', 'transfer_raan_deg', 'transfer_argp_deg',
            'departure_date_jd', 'arrival_date_jd',
        ]
        for k in scalars:
            assert isinstance(opt[k], (int, float)), f"{k} not numeric"

    def test_vector_types(self, opt):
        vecs = ['r1_km', 'v1_kms', 'r2_km', 'v2_kms',
                'v_earth_kms', 'v_mars_kms']
        for k in vecs:
            assert isinstance(opt[k], list) and len(opt[k]) == 3, \
                f"{k} must be a 3-element list"

    def test_grid_keys(self, results):
        grid = results['search_grid']
        for k in ['dep_start_jd', 'dep_end_jd', 'arr_start_jd', 'arr_end_jd',
                   'dep_step_days', 'arr_step_days', 'n_dep', 'n_arr',
                   'n_converged']:
            assert k in grid, f"Missing grid key: {k}"

    def test_constants_keys(self, consts):
        for k in ['mu_sun_km3s2', 'mu_earth_km3s2', 'mu_mars_km3s2',
                   'r_park_earth_km', 'r_park_mars_km']:
            assert k in consts, f"Missing constant: {k}"


# ======================================================================
# Constant validation
# ======================================================================

class TestConstants:
    def test_mu_sun(self, consts):
        rel = abs(consts['mu_sun_km3s2'] - MU_SUN) / MU_SUN
        assert rel < 1e-6, f"mu_sun off by {rel}"

    def test_mu_earth(self, consts):
        rel = abs(consts['mu_earth_km3s2'] - MU_EARTH) / MU_EARTH
        assert rel < 1e-4, f"mu_earth off by {rel}"

    def test_mu_mars(self, consts):
        rel = abs(consts['mu_mars_km3s2'] - MU_MARS) / MU_MARS
        assert rel < 1e-4, f"mu_mars off by {rel}"

    def test_r_park_earth(self, consts):
        assert abs(consts['r_park_earth_km'] - R_PARK_EARTH) < 1.0

    def test_r_park_mars(self, consts):
        assert abs(consts['r_park_mars_km'] - R_PARK_MARS) < 1.0


# ======================================================================
# Physical plausibility
# ======================================================================

class TestPlausibility:
    def test_departure_in_window(self, opt):
        jd = opt['departure_date_jd']
        assert DEP_JD_LO < jd < DEP_JD_HI, \
            f"Departure JD {jd} outside window"

    def test_arrival_in_window(self, opt):
        jd = opt['arrival_date_jd']
        assert ARR_JD_LO < jd < ARR_JD_HI, \
            f"Arrival JD {jd} outside window"

    def test_tof_range(self, opt):
        tof = opt['tof_days']
        assert 120 < tof < 400, f"TOF {tof} days outside [120, 400]"

    def test_c3_range(self, opt):
        c3 = opt['c3_km2s2']
        assert 5.0 < c3 < 30.0, f"C3 = {c3} km^2/s^2 outside [5, 30]"

    def test_vinf_dep_range(self, opt):
        v = opt['vinf_dep_kms']
        assert 2.0 < v < 6.0, f"vinf_dep = {v} km/s outside [2, 6]"

    def test_vinf_arr_range(self, opt):
        v = opt['vinf_arr_kms']
        assert 1.0 < v < 8.0, f"vinf_arr = {v} km/s outside [1, 8]"

    def test_dv_total_range(self, opt):
        dv = opt['dv_total_kms']
        assert 4.0 < dv < 10.0, f"Total dv = {dv} km/s outside [4, 10]"

    def test_dv_below_hohmann_ceiling(self, opt):
        """Optimal total dv should be competitive (< 8 km/s LEO to LMO)."""
        assert opt['dv_total_kms'] < 8.0

    def test_transfer_sma_range(self, opt):
        a_au = opt['transfer_a_km'] / AU_KM
        assert 1.0 < a_au < 2.0, f"Transfer SMA = {a_au} AU outside [1, 2]"

    def test_transfer_ecc_range(self, opt):
        e = opt['transfer_e']
        assert 0.0 < e < 0.5, f"Transfer ecc = {e} outside (0, 0.5)"

    def test_transfer_inc_small(self, opt):
        assert abs(opt['transfer_i_deg']) < 5.0, \
            f"Inc = {opt['transfer_i_deg']}° too large"

    def test_r1_near_earth(self, opt):
        r1_au = np.linalg.norm(opt['r1_km']) / AU_KM
        assert 0.95 < r1_au < 1.05, f"|r1| = {r1_au} AU"

    def test_r2_near_mars(self, opt):
        r2_au = np.linalg.norm(opt['r2_km']) / AU_KM
        assert 1.35 < r2_au < 1.70, f"|r2| = {r2_au} AU"


# ======================================================================
# Mathematical consistency
# ======================================================================

class TestConsistency:
    def test_c3_equals_vinf_squared(self, opt):
        c3 = opt['c3_km2s2']
        vinf = opt['vinf_dep_kms']
        assert abs(c3 - vinf ** 2) < 0.01, \
            f"C3 {c3} != vinf_dep^2 {vinf ** 2}"

    def test_vinf_dep_from_vectors(self, opt):
        v1 = np.array(opt['v1_kms'])
        ve = np.array(opt['v_earth_kms'])
        computed = np.linalg.norm(v1 - ve)
        assert abs(computed - opt['vinf_dep_kms']) < 0.01, \
            f"|v1-ve| = {computed}, reported vinf_dep = {opt['vinf_dep_kms']}"

    def test_vinf_arr_from_vectors(self, opt):
        v2 = np.array(opt['v2_kms'])
        vm = np.array(opt['v_mars_kms'])
        computed = np.linalg.norm(v2 - vm)
        assert abs(computed - opt['vinf_arr_kms']) < 0.01, \
            f"|v2-vm| = {computed}, reported vinf_arr = {opt['vinf_arr_kms']}"

    def test_dv_total_is_sum(self, opt):
        assert abs(opt['dv_total_kms'] -
                    (opt['dv_dep_kms'] + opt['dv_arr_kms'])) < 1e-6

    def test_departure_dv_formula(self, opt, consts):
        vinf = opt['vinf_dep_kms']
        mu = consts['mu_earth_km3s2']
        rp = consts['r_park_earth_km']
        expected = math.sqrt(vinf ** 2 + 2 * mu / rp) - math.sqrt(mu / rp)
        assert abs(opt['dv_dep_kms'] - expected) < 0.002, \
            f"dv_dep: {opt['dv_dep_kms']} vs formula {expected}"

    def test_arrival_dv_formula(self, opt, consts):
        vinf = opt['vinf_arr_kms']
        mu = consts['mu_mars_km3s2']
        rp = consts['r_park_mars_km']
        expected = math.sqrt(vinf ** 2 + 2 * mu / rp) - math.sqrt(mu / rp)
        assert abs(opt['dv_arr_kms'] - expected) < 0.002, \
            f"dv_arr: {opt['dv_arr_kms']} vs formula {expected}"

    def test_visviva_departure(self, opt, consts):
        r = np.linalg.norm(opt['r1_km'])
        v = np.linalg.norm(opt['v1_kms'])
        a = opt['transfer_a_km']
        mu = consts['mu_sun_km3s2']
        v_vv = math.sqrt(mu * (2.0 / r - 1.0 / a))
        assert abs(v - v_vv) / v < 1e-4, \
            f"Vis-viva dep: v={v}, visviva={v_vv}"

    def test_visviva_arrival(self, opt, consts):
        r = np.linalg.norm(opt['r2_km'])
        v = np.linalg.norm(opt['v2_kms'])
        a = opt['transfer_a_km']
        mu = consts['mu_sun_km3s2']
        v_vv = math.sqrt(mu * (2.0 / r - 1.0 / a))
        assert abs(v - v_vv) / v < 1e-4, \
            f"Vis-viva arr: v={v}, visviva={v_vv}"

    def test_angular_momentum_conservation(self, opt):
        r1 = np.array(opt['r1_km'])
        v1 = np.array(opt['v1_kms'])
        r2 = np.array(opt['r2_km'])
        v2 = np.array(opt['v2_kms'])
        h1 = np.cross(r1, v1)
        h2 = np.cross(r2, v2)
        rel = np.linalg.norm(h1 - h2) / np.linalg.norm(h1)
        assert rel < 1e-4, f"Angular momentum rel err = {rel}"

    def test_tof_matches_jd(self, opt):
        diff = opt['arrival_date_jd'] - opt['departure_date_jd']
        assert abs(opt['tof_days'] - diff) < 0.01, \
            f"TOF {opt['tof_days']} != JD diff {diff}"

    def test_energy_consistency(self, opt, consts):
        r = np.linalg.norm(opt['r1_km'])
        v = np.linalg.norm(opt['v1_kms'])
        a = opt['transfer_a_km']
        mu = consts['mu_sun_km3s2']
        eps_a = -mu / (2 * a)
        eps_rv = v ** 2 / 2 - mu / r
        rel = abs(eps_a - eps_rv) / abs(eps_a)
        assert rel < 1e-4, f"Energy: -mu/2a = {eps_a}, v^2/2 - mu/r = {eps_rv}"


# ======================================================================
# Forward Kepler propagation — independent trajectory verification
# ======================================================================

class TestPropagation:
    """Propagate departure state by TOF and verify arrival position."""

    @staticmethod
    def _kepler_propagate(r0_vec, v0_vec, dt_sec, mu):
        """Propagate an elliptic orbit using Kepler's equation."""
        r0_vec = np.asarray(r0_vec, dtype=float)
        v0_vec = np.asarray(v0_vec, dtype=float)

        r0 = np.linalg.norm(r0_vec)
        v0 = np.linalg.norm(v0_vec)
        vr0 = np.dot(r0_vec, v0_vec) / r0

        # Semi-major axis from energy
        energy = v0 ** 2 / 2 - mu / r0
        a = -mu / (2 * energy)

        # Eccentricity vector and magnitude
        e_vec = ((v0 ** 2 - mu / r0) * r0_vec -
                 np.dot(r0_vec, v0_vec) * v0_vec) / mu
        e = np.linalg.norm(e_vec)

        # Angular momentum
        h_vec = np.cross(r0_vec, v0_vec)

        # Periapsis direction (unit eccentricity vector)
        P = e_vec / e
        W = h_vec / np.linalg.norm(h_vec)
        Q = np.cross(W, P)

        # Eccentric anomaly at departure
        cos_E0 = (1 - r0 / a) / e
        cos_E0 = np.clip(cos_E0, -1.0, 1.0)
        sin_E0 = vr0 * r0 / (e * math.sqrt(mu * a))
        E0 = math.atan2(sin_E0, cos_E0)

        # Mean anomaly at departure
        M0 = E0 - e * math.sin(E0)

        # Advance mean anomaly
        n = math.sqrt(mu / a ** 3)
        M = M0 + n * dt_sec

        # Solve Kepler's equation M = E - e sin E
        E = M
        for _ in range(200):
            dE = (M - E + e * math.sin(E)) / (1 - e * math.cos(E))
            E += dE
            if abs(dE) < 1e-14:
                break

        # Position in orbital plane
        xp = a * (math.cos(E) - e)
        yp = a * math.sqrt(1 - e ** 2) * math.sin(E)

        return xp * P + yp * Q

    def test_forward_propagation(self, opt, consts):
        """r1, v1 propagated by tof must land at r2."""
        r1 = np.array(opt['r1_km'])
        v1 = np.array(opt['v1_kms'])
        r2_expected = np.array(opt['r2_km'])
        tof_sec = opt['tof_days'] * 86400.0
        mu = consts['mu_sun_km3s2']

        r2_prop = self._kepler_propagate(r1, v1, tof_sec, mu)
        err = np.linalg.norm(r2_prop - r2_expected)
        rel = err / np.linalg.norm(r2_expected)
        assert rel < 1e-4, \
            f"Forward propagation error: {err:.1f} km ({rel * 100:.6f}%)"

    def test_orbital_elements_from_state(self, opt, consts):
        """Orbital elements computed from r1, v1 must match reported values."""
        r1 = np.array(opt['r1_km'])
        v1 = np.array(opt['v1_kms'])
        mu = consts['mu_sun_km3s2']

        r = np.linalg.norm(r1)
        v = np.linalg.norm(v1)
        h_vec = np.cross(r1, v1)
        h = np.linalg.norm(h_vec)

        # Semi-major axis
        energy = v ** 2 / 2 - mu / r
        a_comp = -mu / (2 * energy)
        assert abs(a_comp - opt['transfer_a_km']) / a_comp < 1e-4, \
            f"SMA: computed {a_comp} vs reported {opt['transfer_a_km']}"

        # Eccentricity
        e_vec = ((v ** 2 - mu / r) * r1 - np.dot(r1, v1) * v1) / mu
        e_comp = np.linalg.norm(e_vec)
        assert abs(e_comp - opt['transfer_e']) < 0.001, \
            f"Ecc: computed {e_comp} vs reported {opt['transfer_e']}"

        # Inclination
        i_comp = math.degrees(math.acos(np.clip(h_vec[2] / h, -1, 1)))
        assert abs(i_comp - opt['transfer_i_deg']) < 0.1, \
            f"Inc: computed {i_comp}° vs reported {opt['transfer_i_deg']}°"


# ======================================================================
# Optimality
# ======================================================================

class TestOptimality:
    def test_optimal_is_best_of_top5(self, results):
        opt_dv = results['optimal']['dv_total_kms']
        for entry in results['top5']:
            assert opt_dv <= entry['dv_total_kms'] + 1e-6

    def test_grid_covers_departure_window(self, results):
        grid = results['search_grid']
        assert grid['dep_start_jd'] < DEP_JD_LO + 10
        assert grid['dep_end_jd'] > DEP_JD_HI - 10

    def test_grid_covers_arrival_window(self, results):
        grid = results['search_grid']
        assert grid['arr_end_jd'] > grid['dep_end_jd'] + 120

    def test_grid_resolution(self, results):
        grid = results['search_grid']
        assert grid['dep_step_days'] <= 10
        assert grid['arr_step_days'] <= 10

    def test_sufficient_convergence(self, results):
        assert results['search_grid']['n_converged'] >= 50


# ======================================================================
# API cross-validation
# ======================================================================

class TestAPIValidation:
    """Verify reported positions match actual planetary ephemeris."""

    @staticmethod
    def _query_horizons_state(body_id, jd):
        """Query Horizons for heliocentric ecliptic J2000 state at a JD."""
        url = 'https://ssd.jpl.nasa.gov/api/horizons.api'
        params = {
            'format': 'json',
            'COMMAND': f"'{body_id}'",
            'OBJ_DATA': "'NO'",
            'MAKE_EPHEM': "'YES'",
            'EPHEM_TYPE': "'VECTORS'",
            'CENTER': "'500@10'",
            'TLIST': f"'{jd}'",
            'VEC_TABLE': "'2'",
            'REF_PLANE': "'ECLIPTIC'",
            'REF_SYSTEM': "'J2000'",
            'OUT_UNITS': "'KM-S'",
            'CSV_FORMAT': "'YES'",
            'VEC_LABELS': "'NO'",
        }
        resp = requests.get(url, params=params, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        result = data['result']
        soe = result.index('$$SOE') + len('$$SOE')
        eoe = result.index('$$EOE')
        line = result[soe:eoe].strip()
        parts = [p.strip() for p in line.split(',') if p.strip()]
        pos = np.array([float(parts[2]), float(parts[3]), float(parts[4])])
        vel = np.array([float(parts[5]), float(parts[6]), float(parts[7])])
        return pos, vel

    def test_r1_matches_earth(self, opt):
        r1 = np.array(opt['r1_km'])
        r_earth, _ = self._query_horizons_state('399', opt['departure_date_jd'])
        err = np.linalg.norm(r1 - r_earth)
        assert err < 5000, f"r1 differs from Earth by {err:.0f} km"

    def test_r2_matches_mars(self, opt):
        r2 = np.array(opt['r2_km'])
        r_mars, _ = self._query_horizons_state('499', opt['arrival_date_jd'])
        err = np.linalg.norm(r2 - r_mars)
        assert err < 5000, f"r2 differs from Mars by {err:.0f} km"

    def test_v_earth_matches(self, opt):
        ve = np.array(opt['v_earth_kms'])
        _, v_api = self._query_horizons_state('399', opt['departure_date_jd'])
        err = np.linalg.norm(ve - v_api)
        assert err < 0.1, f"Earth vel differs by {err:.4f} km/s"

    def test_v_mars_matches(self, opt):
        vm = np.array(opt['v_mars_kms'])
        _, v_api = self._query_horizons_state('499', opt['arrival_date_jd'])
        err = np.linalg.norm(vm - v_api)
        assert err < 0.1, f"Mars vel differs by {err:.4f} km/s"
