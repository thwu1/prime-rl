#!/usr/bin/env python3
"""

Verification tests for corrected Lambert transfer orbit solution
and mission trade-study evaluation.
"""

import json
import math
import os
import re
import time
import urllib.request

import numpy as np
import pytest

MU_SUN = 1.32712440018e11  # km^3/s^2

# Julian Day boundaries for date windows (midnight TDB)
DEP_JD_MIN = 2461284.5  # 2026-Sep-01
DEP_JD_MAX = 2461374.5  # 2026-Nov-30
ARR_JD_MIN = 2461465.5  # 2027-Mar-01
ARR_JD_MAX = 2461648.5  # 2027-Aug-31


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def stumpff_c(z):
    if z > 1e-6:
        return (1.0 - np.cos(np.sqrt(z))) / z
    elif z < -1e-6:
        return (np.cosh(np.sqrt(-z)) - 1.0) / (-z)
    else:
        return 0.5 - z / 24.0 + z ** 2 / 720.0


def stumpff_s(z):
    if z > 1e-6:
        sz = np.sqrt(z)
        return (sz - np.sin(sz)) / (sz ** 3)
    elif z < -1e-6:
        sz = np.sqrt(-z)
        return (np.sinh(sz) - sz) / (sz ** 3)
    else:
        return 1.0 / 6.0 - z / 120.0 + z ** 2 / 5040.0


def kepler_propagate(r0_vec, v0_vec, dt, mu):
    """
    Propagate an orbital state using the universal variable formulation.
    """
    r0_vec = np.asarray(r0_vec, dtype=np.float64)
    v0_vec = np.asarray(v0_vec, dtype=np.float64)

    r0 = np.linalg.norm(r0_vec)
    v0 = np.linalg.norm(v0_vec)
    vr0 = np.dot(r0_vec, v0_vec) / r0

    alpha = 2.0 / r0 - v0 ** 2 / mu
    sqrt_mu = np.sqrt(mu)

    if alpha > 1e-12:
        chi = sqrt_mu * dt * alpha
    elif alpha < -1e-12:
        a = 1.0 / alpha
        chi = (np.sign(dt) * np.sqrt(-a)
               * np.log((-2.0 * mu * alpha * dt)
                        / (np.dot(r0_vec, v0_vec)
                           + np.sign(dt) * np.sqrt(-mu * a)
                           * (1.0 - r0 * alpha))))
    else:
        chi = sqrt_mu * dt / r0

    for _ in range(300):
        z = alpha * chi ** 2
        C = stumpff_c(z)
        S = stumpff_s(z)

        f_chi = (chi ** 3 * S
                 + (r0 * vr0 / sqrt_mu) * chi ** 2 * C
                 + r0 * chi * (1.0 - z * S)
                 - sqrt_mu * dt)

        r = (chi ** 2 * C
             + (r0 * vr0 / sqrt_mu) * chi * (1.0 - z * S)
             + r0 * (1.0 - z * C))

        if abs(f_chi) < 1e-10:
            break
        if abs(r) < 1e-30:
            break

        chi = chi - f_chi / r

    z = alpha * chi ** 2
    C = stumpff_c(z)
    S = stumpff_s(z)

    r = (chi ** 2 * C
         + (r0 * vr0 / sqrt_mu) * chi * (1.0 - z * S)
         + r0 * (1.0 - z * C))

    f = 1.0 - chi ** 2 / r0 * C
    g = dt - chi ** 3 / sqrt_mu * S
    fdot = sqrt_mu / (r * r0) * chi * (z * S - 1.0)
    gdot = 1.0 - chi ** 2 / r * C

    r1_vec = f * r0_vec + g * v0_vec
    v1_vec = fdot * r0_vec + gdot * v0_vec

    return r1_vec, v1_vec


def lambert_solve_test(r1_vec, r2_vec, tof, mu=MU_SUN):
    """
    Lambert solver for test verification (prograde Type-I transfer).
    Uses the universal variable method with Newton-Raphson iteration.
    """
    r1_vec = np.asarray(r1_vec, dtype=np.float64)
    r2_vec = np.asarray(r2_vec, dtype=np.float64)
    r1 = np.linalg.norm(r1_vec)
    r2 = np.linalg.norm(r2_vec)

    cos_dtheta = np.clip(np.dot(r1_vec, r2_vec) / (r1 * r2), -1.0, 1.0)

    # Prograde: orbit normal Z-component must be positive in ecliptic frame
    cx = np.cross(r1_vec, r2_vec)
    if cx[2] >= 0:
        dtheta = np.arccos(cos_dtheta)
    else:
        dtheta = 2.0 * np.pi - np.arccos(cos_dtheta)

    if dtheta > np.pi:
        raise ValueError("Type-II transfer")

    sin_dtheta = np.sin(dtheta)
    if abs(sin_dtheta) < 1e-12:
        raise ValueError("Degenerate geometry")

    A = sin_dtheta * np.sqrt(r1 * r2 / (1.0 - cos_dtheta))
    if abs(A) < 1e-14:
        raise ValueError("A ~ 0")

    sqrt_mu = np.sqrt(mu)

    def tof_residual(z):
        C = stumpff_c(z)
        S = stumpff_s(z)
        if C <= 0:
            return None, None
        y = r1 + r2 + A * (z * S - 1.0) / np.sqrt(C)
        if y < 0:
            return None, y
        F = (y / C) ** 1.5 * S + A * np.sqrt(y) - sqrt_mu * tof
        return F, y

    z = 0.0
    for _ in range(300):
        F, y = tof_residual(z)
        if F is None or y is None or y < 0:
            z += 0.5
            continue
        if abs(F) < 1e-8:
            break
        h = max(abs(z) * 1e-7, 1e-7)
        Fp, _ = tof_residual(z + h)
        Fm, _ = tof_residual(z - h)
        if Fp is None or Fm is None:
            z += 0.5
            continue
        dFdz = (Fp - Fm) / (2.0 * h)
        if abs(dFdz) < 1e-30:
            z += 0.5
            continue
        z_new = z - F / dFdz
        z_new = np.clip(z_new, -4.0 * np.pi ** 2, 40.0 * np.pi ** 2)
        _, y_new = tof_residual(z_new)
        retries = 0
        while (y_new is None or y_new < 0) and retries < 20:
            z_new = (z + z_new) / 2.0
            _, y_new = tof_residual(z_new)
            retries += 1
        z = z_new
    else:
        raise ValueError("Lambert solver did not converge")

    C = stumpff_c(z)
    S = stumpff_s(z)
    y = r1 + r2 + A * (z * S - 1.0) / np.sqrt(C)

    f = 1.0 - y / r1
    g = A * np.sqrt(y / mu)
    gdot = 1.0 - y / r2

    v1 = (r2_vec - f * r1_vec) / g
    v2 = (gdot * r2_vec - r1_vec) / g

    return v1, v2


def query_horizons_state(body_id, jd):
    """Query JPL Horizons API for heliocentric ecliptic J2000 geometric state."""
    url = (
        "https://ssd.jpl.nasa.gov/api/horizons.api"
        "?format=text"
        f"&COMMAND=%27{body_id}%27"
        "&OBJ_DATA=NO"
        "&MAKE_EPHEM=YES"
        "&EPHEM_TYPE=VECTORS"
        "&CENTER=%27500@10%27"
        "&REF_PLANE=ECLIPTIC"
        "&OUT_UNITS=KM-S"
        "&VEC_TABLE=2"
        "&VEC_LABELS=YES"
        "&CSV_FORMAT=NO"
        "&VEC_CORR=NONE"
        f"&TLIST=%27{jd}%27"
        "&TLIST_TYPE=JD"
    )

    text = None
    for attempt in range(5):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=90) as resp:
                text = resp.read().decode("utf-8")
            break
        except Exception:
            if attempt < 4:
                time.sleep(3 * (attempt + 1))
            else:
                raise

    soe = text.find("$$SOE")
    eoe = text.find("$$EOE")
    assert soe >= 0 and eoe > soe, "Horizons output missing data markers"
    data = text[soe + 5 : eoe]

    x_pat = re.compile(
        r"X\s*=\s*([+-]?\d+\.\d+[Ee][+-]?\d+)\s+"
        r"Y\s*=\s*([+-]?\d+\.\d+[Ee][+-]?\d+)\s+"
        r"Z\s*=\s*([+-]?\d+\.\d+[Ee][+-]?\d+)"
    )
    v_pat = re.compile(
        r"VX\s*=\s*([+-]?\d+\.\d+[Ee][+-]?\d+)\s+"
        r"VY\s*=\s*([+-]?\d+\.\d+[Ee][+-]?\d+)\s+"
        r"VZ\s*=\s*([+-]?\d+\.\d+[Ee][+-]?\d+)"
    )

    xm = x_pat.search(data)
    vm = v_pat.search(data)
    assert xm and vm, "Could not parse position/velocity from Horizons output"

    pos = np.array([float(xm.group(i)) for i in range(1, 4)])
    vel = np.array([float(vm.group(i)) for i in range(1, 4)])
    return pos, vel


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def results():
    with open("/app/results.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def diagnosis():
    with open("/app/diagnosis.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def evaluation():
    with open("/app/mission_evaluation.json") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def api_earth(results):
    """Earth state from Horizons API (body 399, geometric) at departure JD."""
    return query_horizons_state("399", results["departure_jd"])


@pytest.fixture(scope="session")
def api_mars(results):
    """Mars state from Horizons API (body 499, geometric) at arrival JD."""
    time.sleep(2)
    return query_horizons_state("499", results["arrival_jd"])


@pytest.fixture(scope="session")
def earth_dep_m1(results):
    """Earth state at departure JD - 1 day."""
    time.sleep(2)
    return query_horizons_state("399", results["departure_jd"] - 1.0)


@pytest.fixture(scope="session")
def earth_dep_p1(results):
    """Earth state at departure JD + 1 day."""
    time.sleep(2)
    return query_horizons_state("399", results["departure_jd"] + 1.0)


@pytest.fixture(scope="session")
def mars_arr_m1(results):
    """Mars state at arrival JD - 1 day."""
    time.sleep(2)
    return query_horizons_state("499", results["arrival_jd"] - 1.0)


@pytest.fixture(scope="session")
def mars_arr_p1(results):
    """Mars state at arrival JD + 1 day."""
    time.sleep(2)
    return query_horizons_state("499", results["arrival_jd"] + 1.0)


@pytest.fixture(scope="session")
def api_arr_opt_earth(evaluation):
    """Earth state at arrival-optimal departure JD."""
    time.sleep(2)
    return query_horizons_state("399", evaluation["arrival_optimal"]["departure_jd"])


@pytest.fixture(scope="session")
def api_arr_opt_mars(evaluation):
    """Mars state at arrival-optimal arrival JD."""
    time.sleep(2)
    return query_horizons_state("499", evaluation["arrival_optimal"]["arrival_jd"])


# ---------------------------------------------------------------------------
# Tests — result format
# ---------------------------------------------------------------------------

class TestResultsFormat:
    def test_file_exists(self):
        assert os.path.isfile("/app/results.json"), "results.json not found"

    def test_valid_json(self, results):
        assert isinstance(results, dict)

    def test_required_fields(self, results):
        required = [
            "departure_jd", "arrival_jd", "c3_km2_s2",
            "v_inf_dep_km_s", "v_inf_arr_km_s",
            "transfer_v1_km_s", "transfer_v2_km_s",
            "tof_seconds",
            "earth_pos_km", "earth_vel_km_s",
            "mars_pos_km", "mars_vel_km_s",
        ]
        for field in required:
            assert field in results, f"Missing required field: {field}"

    def test_vector_dimensions(self, results):
        vec_fields = [
            "v_inf_dep_km_s", "v_inf_arr_km_s",
            "transfer_v1_km_s", "transfer_v2_km_s",
            "earth_pos_km", "earth_vel_km_s",
            "mars_pos_km", "mars_vel_km_s",
        ]
        for field in vec_fields:
            assert len(results[field]) == 3, f"{field} must have 3 components"


# ---------------------------------------------------------------------------
# Tests — date windows
# ---------------------------------------------------------------------------

class TestDateWindows:
    def test_departure_in_window(self, results):
        jd = results["departure_jd"]
        assert DEP_JD_MIN <= jd <= DEP_JD_MAX, (
            f"Departure JD {jd} outside [{DEP_JD_MIN}, {DEP_JD_MAX}]"
        )

    def test_arrival_in_window(self, results):
        jd = results["arrival_jd"]
        assert ARR_JD_MIN <= jd <= ARR_JD_MAX, (
            f"Arrival JD {jd} outside [{ARR_JD_MIN}, {ARR_JD_MAX}]"
        )

    def test_tof_matches_jd_difference(self, results):
        tof_expected = (results["arrival_jd"] - results["departure_jd"]) * 86400.0
        np.testing.assert_allclose(
            results["tof_seconds"], tof_expected, rtol=1e-6,
            err_msg="tof_seconds inconsistent with departure/arrival JD",
        )


# ---------------------------------------------------------------------------
# Tests — physical plausibility
# ---------------------------------------------------------------------------

class TestPhysicalPlausibility:
    def test_c3_in_range(self, results):
        c3 = results["c3_km2_s2"]
        assert 7.0 < c3 < 20.0, f"C3 = {c3} km^2/s^2 outside plausible range"

    def test_tof_in_range(self, results):
        tof_days = results["tof_seconds"] / 86400.0
        assert 100.0 < tof_days < 400.0, (
            f"TOF = {tof_days:.1f} days outside plausible range"
        )

    def test_vinf_dep_magnitude(self, results):
        vmag = np.linalg.norm(results["v_inf_dep_km_s"])
        assert 2.0 < vmag < 6.0, (
            f"|v_inf_dep| = {vmag:.4f} km/s outside plausible range"
        )

    def test_vinf_arr_magnitude(self, results):
        vmag = np.linalg.norm(results["v_inf_arr_km_s"])
        assert 1.0 < vmag < 10.0, (
            f"|v_inf_arr| = {vmag:.4f} km/s outside plausible range"
        )

    def test_transfer_orbit_elliptic(self, results):
        r = np.array(results["earth_pos_km"])
        v = np.array(results["transfer_v1_km_s"])
        eps = 0.5 * np.dot(v, v) - MU_SUN / np.linalg.norm(r)
        assert eps < 0, f"Transfer orbit energy = {eps} (must be negative)"

    def test_prograde_transfer(self, results):
        """Transfer orbit must have positive Z angular momentum (prograde)."""
        r1 = np.array(results["earth_pos_km"])
        v1 = np.array(results["transfer_v1_km_s"])
        h = np.cross(r1, v1)
        assert h[2] > 0, (
            f"Transfer angular momentum Z = {h[2]:.4e} (must be positive for prograde)"
        )


# ---------------------------------------------------------------------------
# Tests — self-consistency
# ---------------------------------------------------------------------------

class TestSelfConsistency:
    def test_c3_equals_vinf_squared(self, results):
        v_inf = np.array(results["v_inf_dep_km_s"])
        c3_computed = float(np.dot(v_inf, v_inf))
        np.testing.assert_allclose(
            c3_computed, results["c3_km2_s2"], rtol=1e-6,
            err_msg="C3 != |v_inf_dep|^2",
        )

    def test_vinf_dep_equals_v1_minus_vearth(self, results):
        v1 = np.array(results["transfer_v1_km_s"])
        ve = np.array(results["earth_vel_km_s"])
        computed = v1 - ve
        reported = np.array(results["v_inf_dep_km_s"])
        np.testing.assert_allclose(
            computed, reported, atol=1e-6,
            err_msg="v_inf_dep != transfer_v1 - earth_vel",
        )

    def test_vinf_arr_equals_v2_minus_vmars(self, results):
        v2 = np.array(results["transfer_v2_km_s"])
        vm = np.array(results["mars_vel_km_s"])
        computed = v2 - vm
        reported = np.array(results["v_inf_arr_km_s"])
        np.testing.assert_allclose(
            computed, reported, atol=1e-6,
            err_msg="v_inf_arr != transfer_v2 - mars_vel",
        )

    def test_energy_conservation(self, results):
        r1 = np.array(results["earth_pos_km"])
        v1 = np.array(results["transfer_v1_km_s"])
        r2 = np.array(results["mars_pos_km"])
        v2 = np.array(results["transfer_v2_km_s"])

        eps1 = 0.5 * np.dot(v1, v1) - MU_SUN / np.linalg.norm(r1)
        eps2 = 0.5 * np.dot(v2, v2) - MU_SUN / np.linalg.norm(r2)

        np.testing.assert_allclose(
            eps1, eps2, rtol=1e-4,
            err_msg="Orbital energy not conserved along transfer orbit",
        )

    def test_angular_momentum_conservation(self, results):
        r1 = np.array(results["earth_pos_km"])
        v1 = np.array(results["transfer_v1_km_s"])
        r2 = np.array(results["mars_pos_km"])
        v2 = np.array(results["transfer_v2_km_s"])

        h1 = np.cross(r1, v1)
        h2 = np.cross(r2, v2)

        np.testing.assert_allclose(
            h1, h2, rtol=1e-4,
            err_msg="Angular momentum not conserved along transfer orbit",
        )


# ---------------------------------------------------------------------------
# Tests — API verification of planet states
# ---------------------------------------------------------------------------

class TestAPIVerification:
    def test_earth_position_matches_api(self, results, api_earth):
        pos_reported = np.array(results["earth_pos_km"])
        pos_api, _ = api_earth
        diff = np.linalg.norm(pos_reported - pos_api)
        assert diff < 10.0, (
            f"Earth position differs from Horizons body-399 geometric by {diff:.4f} km"
        )

    def test_earth_velocity_matches_api(self, results, api_earth):
        vel_reported = np.array(results["earth_vel_km_s"])
        _, vel_api = api_earth
        diff = np.linalg.norm(vel_reported - vel_api)
        assert diff < 1e-4, (
            f"Earth velocity differs from Horizons body-399 geometric by {diff:.8f} km/s"
        )

    def test_mars_position_matches_api(self, results, api_mars):
        pos_reported = np.array(results["mars_pos_km"])
        pos_api, _ = api_mars
        diff = np.linalg.norm(pos_reported - pos_api)
        assert diff < 10.0, (
            f"Mars position differs from Horizons body-499 geometric by {diff:.4f} km"
        )

    def test_mars_velocity_matches_api(self, results, api_mars):
        vel_reported = np.array(results["mars_vel_km_s"])
        _, vel_api = api_mars
        diff = np.linalg.norm(vel_reported - vel_api)
        assert diff < 1e-4, (
            f"Mars velocity differs from Horizons body-499 geometric by {diff:.8f} km/s"
        )


# ---------------------------------------------------------------------------
# Tests — Kepler propagation verification
# ---------------------------------------------------------------------------

class TestKeplerPropagation:
    def test_departure_state_reaches_arrival(self, results):
        """Propagate (earth_pos, transfer_v1) and verify arrival position."""
        r1 = np.array(results["earth_pos_km"])
        v1 = np.array(results["transfer_v1_km_s"])
        r2_expected = np.array(results["mars_pos_km"])
        tof = results["tof_seconds"]

        r2_prop, _ = kepler_propagate(r1, v1, tof, MU_SUN)

        pos_err = np.linalg.norm(r2_prop - r2_expected)
        assert pos_err < 500.0, (
            f"Kepler propagation position error: {pos_err:.1f} km (tolerance 500 km)"
        )

    def test_arrival_velocity_from_propagation(self, results):
        """Propagated velocity at arrival must match transfer_v2."""
        r1 = np.array(results["earth_pos_km"])
        v1 = np.array(results["transfer_v1_km_s"])
        v2_expected = np.array(results["transfer_v2_km_s"])
        tof = results["tof_seconds"]

        _, v2_prop = kepler_propagate(r1, v1, tof, MU_SUN)

        vel_err = np.linalg.norm(v2_prop - v2_expected)
        assert vel_err < 0.01, (
            f"Kepler propagation velocity error: {vel_err:.6f} km/s (tolerance 0.01 km/s)"
        )


# ---------------------------------------------------------------------------
# Tests — local optimality of C3
# ---------------------------------------------------------------------------

class TestLocalOptimality:
    """
    Verify the reported solution is a local C3 minimum by checking that
    shifting the departure or arrival date by +/-1 day does not yield a
    lower C3. This ensures the optimizer found a true local minimum
    rather than a coarse grid artifact.
    """

    def _compute_c3_at(self, r1, v1_earth, r2, tof):
        """Solve Lambert and compute C3 for given boundary conditions."""
        v1_t, _ = lambert_solve_test(r1, r2, tof)
        v_inf = v1_t - np.asarray(v1_earth)
        return float(np.dot(v_inf, v_inf))

    def test_c3_vs_dep_minus_1d(self, results, earth_dep_m1, api_mars):
        """C3 at departure - 1 day should not be significantly lower."""
        c3_opt = results["c3_km2_s2"]
        r1, v1 = earth_dep_m1
        r2, _ = api_mars
        tof = (results["arrival_jd"] - (results["departure_jd"] - 1.0)) * 86400.0
        try:
            c3_pert = self._compute_c3_at(r1, v1, r2, tof)
            assert c3_opt <= c3_pert + 0.15, (
                f"C3 at dep-1d ({c3_pert:.4f}) significantly < optimal "
                f"({c3_opt:.4f}) — not a local minimum in departure direction"
            )
        except ValueError:
            pass  # Lambert failure at perturbed point is acceptable

    def test_c3_vs_dep_plus_1d(self, results, earth_dep_p1, api_mars):
        """C3 at departure + 1 day should not be significantly lower."""
        c3_opt = results["c3_km2_s2"]
        r1, v1 = earth_dep_p1
        r2, _ = api_mars
        tof = (results["arrival_jd"] - (results["departure_jd"] + 1.0)) * 86400.0
        try:
            c3_pert = self._compute_c3_at(r1, v1, r2, tof)
            assert c3_opt <= c3_pert + 0.15, (
                f"C3 at dep+1d ({c3_pert:.4f}) significantly < optimal "
                f"({c3_opt:.4f}) — not a local minimum in departure direction"
            )
        except ValueError:
            pass

    def test_c3_vs_arr_minus_1d(self, results, api_earth, mars_arr_m1):
        """C3 at arrival - 1 day should not be significantly lower."""
        c3_opt = results["c3_km2_s2"]
        r1, v1 = api_earth
        r2, _ = mars_arr_m1
        tof = ((results["arrival_jd"] - 1.0) - results["departure_jd"]) * 86400.0
        try:
            c3_pert = self._compute_c3_at(r1, v1, r2, tof)
            assert c3_opt <= c3_pert + 0.15, (
                f"C3 at arr-1d ({c3_pert:.4f}) significantly < optimal "
                f"({c3_opt:.4f}) — not a local minimum in arrival direction"
            )
        except ValueError:
            pass

    def test_c3_vs_arr_plus_1d(self, results, api_earth, mars_arr_p1):
        """C3 at arrival + 1 day should not be significantly lower."""
        c3_opt = results["c3_km2_s2"]
        r1, v1 = api_earth
        r2, _ = mars_arr_p1
        tof = ((results["arrival_jd"] + 1.0) - results["departure_jd"]) * 86400.0
        try:
            c3_pert = self._compute_c3_at(r1, v1, r2, tof)
            assert c3_opt <= c3_pert + 0.15, (
                f"C3 at arr+1d ({c3_pert:.4f}) significantly < optimal "
                f"({c3_opt:.4f}) — not a local minimum in arrival direction"
            )
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Tests — diagnosis report
# ---------------------------------------------------------------------------

class TestDiagnosis:
    def test_diagnosis_file_exists(self):
        assert os.path.isfile("/app/diagnosis.json"), "diagnosis.json not found"

    def test_diagnosis_valid_json(self, diagnosis):
        assert isinstance(diagnosis, dict)

    def test_diagnosis_has_bugs_found(self, diagnosis):
        assert "bugs_found" in diagnosis, "diagnosis must have 'bugs_found' key"
        assert isinstance(diagnosis["bugs_found"], list), "bugs_found must be a list"

    def test_diagnosis_minimum_bug_count(self, diagnosis):
        assert len(diagnosis["bugs_found"]) >= 3, (
            f"Expected at least 3 bugs, found {len(diagnosis['bugs_found'])}"
        )

    def test_diagnosis_bug_fields(self, diagnosis):
        required_fields = ["location", "description", "impact", "fix"]
        for i, bug in enumerate(diagnosis["bugs_found"]):
            for field in required_fields:
                assert field in bug, (
                    f"Bug #{i+1} missing required field: {field}"
                )
            for field in required_fields:
                assert isinstance(bug[field], str) and len(bug[field]) > 5, (
                    f"Bug #{i+1} field '{field}' must be a non-trivial string"
                )

    def test_diagnosis_num_bugs_fixed(self, diagnosis):
        assert "num_bugs_fixed" in diagnosis
        assert diagnosis["num_bugs_fixed"] >= 3, (
            f"num_bugs_fixed = {diagnosis['num_bugs_fixed']}, expected >= 3"
        )


# ---------------------------------------------------------------------------
# Tests — mission evaluation trade study
# ---------------------------------------------------------------------------

class TestMissionEvaluation:
    """
    Verify the mission trade-study evaluation: launch/arrival windows,
    arrival-optimal transfer, and comparative recommendation.
    """

    def test_evaluation_file_exists(self):
        assert os.path.isfile("/app/mission_evaluation.json"), (
            "mission_evaluation.json not found"
        )

    def test_evaluation_valid_json(self, evaluation):
        assert isinstance(evaluation, dict)

    def test_required_sections(self, evaluation):
        for section in [
            "launch_window", "arrival_window",
            "arrival_optimal", "comparison", "recommendation",
        ]:
            assert section in evaluation, f"Missing section: {section}"

    # --- Launch window ---

    def test_launch_window_fields(self, evaluation):
        lw = evaluation["launch_window"]
        for field in [
            "optimal_arrival_jd", "earliest_departure_jd",
            "latest_departure_jd", "window_width_days", "c3_threshold_km2_s2",
        ]:
            assert field in lw, f"launch_window missing field: {field}"

    def test_launch_window_contains_optimum(self, evaluation, results):
        lw = evaluation["launch_window"]
        assert lw["earliest_departure_jd"] <= results["departure_jd"], (
            "Launch window earliest must be <= optimal departure"
        )
        assert lw["latest_departure_jd"] >= results["departure_jd"], (
            "Launch window latest must be >= optimal departure"
        )

    def test_launch_window_width_consistent(self, evaluation):
        lw = evaluation["launch_window"]
        expected = lw["latest_departure_jd"] - lw["earliest_departure_jd"]
        assert abs(lw["window_width_days"] - expected) < 1.5, (
            f"window_width_days={lw['window_width_days']:.1f} inconsistent "
            f"with JD range {expected:.1f}"
        )

    def test_launch_window_width_plausible(self, evaluation):
        lw = evaluation["launch_window"]
        assert 2 <= lw["window_width_days"] <= 60, (
            f"Launch window width {lw['window_width_days']:.1f} days outside "
            f"plausible range [2, 60]"
        )

    def test_launch_window_threshold(self, evaluation, results):
        lw = evaluation["launch_window"]
        expected_threshold = results["c3_km2_s2"] + 2.0
        assert abs(lw["c3_threshold_km2_s2"] - expected_threshold) < 0.05, (
            f"C3 threshold {lw['c3_threshold_km2_s2']:.4f} != "
            f"C3_optimal + 2.0 = {expected_threshold:.4f}"
        )

    # --- Arrival window ---

    def test_arrival_window_fields(self, evaluation):
        aw = evaluation["arrival_window"]
        for field in [
            "optimal_departure_jd", "earliest_arrival_jd",
            "latest_arrival_jd", "window_width_days", "c3_threshold_km2_s2",
        ]:
            assert field in aw, f"arrival_window missing field: {field}"

    def test_arrival_window_contains_optimum(self, evaluation, results):
        aw = evaluation["arrival_window"]
        assert aw["earliest_arrival_jd"] <= results["arrival_jd"], (
            "Arrival window earliest must be <= optimal arrival"
        )
        assert aw["latest_arrival_jd"] >= results["arrival_jd"], (
            "Arrival window latest must be >= optimal arrival"
        )

    def test_arrival_window_width_consistent(self, evaluation):
        aw = evaluation["arrival_window"]
        expected = aw["latest_arrival_jd"] - aw["earliest_arrival_jd"]
        assert abs(aw["window_width_days"] - expected) < 1.5, (
            f"window_width_days={aw['window_width_days']:.1f} inconsistent "
            f"with JD range {expected:.1f}"
        )

    def test_arrival_window_width_plausible(self, evaluation):
        aw = evaluation["arrival_window"]
        # Near the Type-I/Type-II boundary (dtheta ~ pi), the arrival window
        # can be very narrow because small date shifts push the transfer angle
        # past pi. Accept width >= 0 for physical correctness.
        assert 0 <= aw["window_width_days"] <= 90, (
            f"Arrival window width {aw['window_width_days']:.1f} days outside "
            f"plausible range [0, 90]"
        )

    # --- Arrival-optimal transfer ---

    def test_arrival_optimal_fields(self, evaluation):
        ao = evaluation["arrival_optimal"]
        for field in [
            "departure_jd", "arrival_jd", "c3_km2_s2",
            "v_inf_arr_mag_km_s", "tof_days",
        ]:
            assert field in ao, f"arrival_optimal missing field: {field}"

    def test_arrival_optimal_dates_in_window(self, evaluation):
        ao = evaluation["arrival_optimal"]
        assert DEP_JD_MIN <= ao["departure_jd"] <= DEP_JD_MAX, (
            f"Arrival-optimal departure JD outside search window"
        )
        assert ARR_JD_MIN <= ao["arrival_jd"] <= ARR_JD_MAX, (
            f"Arrival-optimal arrival JD outside search window"
        )

    def test_arrival_optimal_plausible(self, evaluation):
        ao = evaluation["arrival_optimal"]
        assert 7.0 < ao["c3_km2_s2"] < 30.0, (
            f"Arrival-optimal C3={ao['c3_km2_s2']:.2f} outside plausible range"
        )
        assert 1.0 < ao["v_inf_arr_mag_km_s"] < 10.0, (
            f"Arrival-optimal v_inf_arr={ao['v_inf_arr_mag_km_s']:.2f} outside range"
        )
        assert 100 < ao["tof_days"] < 400, (
            f"Arrival-optimal TOF={ao['tof_days']:.0f} outside plausible range"
        )

    def test_arrival_optimal_not_identical_to_primary(self, evaluation, results):
        """C3-optimal and arrival-optimal must not be identical grid points."""
        ao = evaluation["arrival_optimal"]
        dep_diff = abs(ao["departure_jd"] - results["departure_jd"])
        arr_diff = abs(ao["arrival_jd"] - results["arrival_jd"])
        # For this transfer geometry the two optima can be close in date space
        # (Type-I constraint limits the search region). Require only that
        # they are at distinct grid points (>= 0.5 day apart in at least
        # one coordinate).
        assert dep_diff > 0.5 or arr_diff > 0.5, (
            f"Arrival-optimal must not be identical to C3-optimal "
            f"(departure diff: {dep_diff:.1f}d, arrival diff: {arr_diff:.1f}d)"
        )

    def test_arrival_optimal_c3_verified(self, evaluation,
                                          api_arr_opt_earth, api_arr_opt_mars):
        """Independently verify arrival-optimal C3 via API + Lambert."""
        ao = evaluation["arrival_optimal"]
        r1, v1_earth = api_arr_opt_earth
        r2, _ = api_arr_opt_mars
        tof = ao["tof_days"] * 86400.0
        v1_t, _ = lambert_solve_test(r1, r2, tof)
        v_inf_dep = v1_t - v1_earth
        c3_check = float(np.dot(v_inf_dep, v_inf_dep))
        assert abs(c3_check - ao["c3_km2_s2"]) < 0.5, (
            f"Arrival-optimal C3 verification: computed {c3_check:.4f}, "
            f"reported {ao['c3_km2_s2']:.4f}"
        )

    def test_arrival_optimal_vinf_verified(self, evaluation,
                                            api_arr_opt_earth, api_arr_opt_mars):
        """Independently verify arrival-optimal v_inf_arr via API + Lambert."""
        ao = evaluation["arrival_optimal"]
        r1, _ = api_arr_opt_earth
        r2, v2_mars = api_arr_opt_mars
        tof = ao["tof_days"] * 86400.0
        _, v2_t = lambert_solve_test(r1, r2, tof)
        v_inf_arr = v2_t - v2_mars
        vinf_mag_check = float(np.linalg.norm(v_inf_arr))
        assert abs(vinf_mag_check - ao["v_inf_arr_mag_km_s"]) < 0.05, (
            f"Arrival-optimal v_inf_arr verification: computed {vinf_mag_check:.4f}, "
            f"reported {ao['v_inf_arr_mag_km_s']:.4f}"
        )

    # --- Comparison ---

    def test_comparison_fields(self, evaluation):
        comp = evaluation["comparison"]
        for field in [
            "c3_optimal_c3", "c3_optimal_vinf_arr", "c3_optimal_tof_days",
            "arr_optimal_c3", "arr_optimal_vinf_arr", "arr_optimal_tof_days",
            "c3_penalty_for_arr_optimal", "vinf_savings_for_arr_optimal",
        ]:
            assert field in comp, f"comparison missing field: {field}"

    def test_comparison_primary_matches_results(self, evaluation, results):
        """C3-optimal values in comparison must match results.json."""
        comp = evaluation["comparison"]
        assert abs(comp["c3_optimal_c3"] - results["c3_km2_s2"]) < 0.01, (
            "comparison.c3_optimal_c3 does not match results.json"
        )

    def test_comparison_c3_optimality(self, evaluation):
        """C3-optimal must have lower or equal C3 than arrival-optimal."""
        comp = evaluation["comparison"]
        assert comp["c3_optimal_c3"] <= comp["arr_optimal_c3"] + 0.1, (
            f"C3-optimal C3 ({comp['c3_optimal_c3']:.4f}) > "
            f"arrival-optimal C3 ({comp['arr_optimal_c3']:.4f}) — "
            f"violates Pareto optimality"
        )

    def test_comparison_vinf_optimality(self, evaluation):
        """Arrival-optimal must have lower or equal v_inf_arr than C3-optimal."""
        comp = evaluation["comparison"]
        assert comp["arr_optimal_vinf_arr"] <= comp["c3_optimal_vinf_arr"] + 0.01, (
            f"Arrival-optimal v_inf_arr ({comp['arr_optimal_vinf_arr']:.4f}) > "
            f"C3-optimal v_inf_arr ({comp['c3_optimal_vinf_arr']:.4f}) — "
            f"violates Pareto optimality"
        )

    def test_comparison_penalty_consistent(self, evaluation):
        comp = evaluation["comparison"]
        expected = comp["arr_optimal_c3"] - comp["c3_optimal_c3"]
        assert abs(comp["c3_penalty_for_arr_optimal"] - expected) < 0.01, (
            f"c3_penalty inconsistent: {comp['c3_penalty_for_arr_optimal']:.4f} "
            f"!= {expected:.4f}"
        )

    def test_comparison_savings_consistent(self, evaluation):
        comp = evaluation["comparison"]
        expected = comp["c3_optimal_vinf_arr"] - comp["arr_optimal_vinf_arr"]
        assert abs(comp["vinf_savings_for_arr_optimal"] - expected) < 0.01, (
            f"vinf_savings inconsistent: {comp['vinf_savings_for_arr_optimal']:.4f} "
            f"!= {expected:.4f}"
        )

    def test_comparison_arr_optimal_matches(self, evaluation):
        """Comparison arr_optimal values must match arrival_optimal section."""
        comp = evaluation["comparison"]
        ao = evaluation["arrival_optimal"]
        assert abs(comp["arr_optimal_c3"] - ao["c3_km2_s2"]) < 0.01
        assert abs(comp["arr_optimal_vinf_arr"] - ao["v_inf_arr_mag_km_s"]) < 0.01
        assert abs(comp["arr_optimal_tof_days"] - ao["tof_days"]) < 0.5

    # --- Recommendation ---

    def test_recommendation_substantive(self, evaluation):
        """Recommendation must be a substantive analysis string."""
        rec = evaluation["recommendation"]
        assert isinstance(rec, str), "recommendation must be a string"
        assert len(rec) > 80, (
            f"recommendation too short ({len(rec)} chars) for a substantive analysis"
        )

    def test_recommendation_quantitative(self, evaluation):
        """Recommendation should contain numerical values for quantitative justification."""
        rec = evaluation["recommendation"]
        import re as re_mod
        numbers = re_mod.findall(r'\d+\.?\d*', rec)
        assert len(numbers) >= 3, (
            "recommendation should contain quantitative values (at least 3 numbers)"
        )
