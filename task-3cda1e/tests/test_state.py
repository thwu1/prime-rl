
"""
Tests for geodetic gravity survey inversion task.
Verifies coordinate projection, normal gravity, density recovery,
GMT gridding, gradient analysis, and Laplace equation.
"""

import csv
import json
import math
import os
import subprocess

import numpy as np
import pytest

# ============================================================================
# Constants
# ============================================================================

G = 6.6743e-11

# GRS80 parameters
A_E = 6378137.0
F_E = 1.0 / 298.257222101
B_E = A_E * (1 - F_E)
GM_E = 3986005.0e8
OMEGA_E = 7292115e-11
E2 = 2 * F_E - F_E**2
E_LIN = math.sqrt(A_E**2 - B_E**2)
E_PRIME = E_LIN / B_E

TRUE_DENSITIES = [300.0, -200.0, 500.0, 150.0, -350.0]

# ============================================================================
# Reference implementations
# ============================================================================


def _compute_surface_gravity():
    ratio = B_E / E_LIN
    arctan_val = math.atan2(E_LIN, B_E)
    m_param = OMEGA_E**2 * A_E**2 * B_E / GM_E
    aux_num = E_PRIME * (3 * (1 + ratio**2) * (1 - ratio * arctan_val) - 1)
    denom_common = (1 + 3 * ratio**2) * arctan_val - 3 * ratio
    gamma_a = GM_E * (1 - m_param - m_param * aux_num / (3 * denom_common)) / (A_E * B_E)
    gamma_b = GM_E * (1 + m_param * aux_num / (1.5 * denom_common)) / A_E**2
    return gamma_a, gamma_b


_GAMMA_A, _GAMMA_B = _compute_surface_gravity()


def ref_somigliana_mGal(lat_deg):
    lat_rad = math.radians(lat_deg)
    cos2 = math.cos(lat_rad) ** 2
    sin2 = math.sin(lat_rad) ** 2
    g0 = (A_E * _GAMMA_A * cos2 + B_E * _GAMMA_B * sin2) / math.sqrt(
        A_E**2 * cos2 + B_E**2 * sin2
    )
    return g0 * 1e5


def ref_normal_gravity_mGal(lat_deg, height_m):
    return ref_somigliana_mGal(lat_deg) - 0.3086 * height_m


def _safe_atan2(y, x):
    if x == 0:
        if y > 0:
            return math.pi / 2
        elif y < 0:
            return -math.pi / 2
        else:
            return 0.0
    return math.atan(y / x)


def _safe_log(x, y, z, r):
    if r == 0:
        return 0.0
    if x < 0:
        if y == 0.0 and z == 0.0:
            return -math.log(-2 * x)
        else:
            return math.log((y**2 + z**2) / (r - x))
    return math.log(x + r)


def _kernel_pot(e, n, u, r):
    return (
        e * n * _safe_log(u, e, n, r)
        + n * u * _safe_log(e, n, u, r)
        + e * u * _safe_log(n, u, e, r)
        - 0.5 * e**2 * _safe_atan2(u * n, e * r)
        - 0.5 * n**2 * _safe_atan2(u * e, n * r)
        - 0.5 * u**2 * _safe_atan2(e * n, u * r)
    )


def _kernel_u(e, n, u, r):
    return -(
        e * _safe_log(n, u, e, r)
        + n * _safe_log(e, n, u, r)
        - u * _safe_atan2(e * n, u * r)
    )


def _kernel_ee(e, n, u, r):
    if r == 0.0:
        return float("nan")
    return -_safe_atan2(n * u, e * r)


def _kernel_nn(e, n, u, r):
    if r == 0.0:
        return float("nan")
    return -_safe_atan2(e * u, n * r)


def _kernel_uu(e, n, u, r):
    if r == 0.0:
        return float("nan")
    return -_safe_atan2(e * n, u * r)


def _evaluate_kernel(easting, northing, upward, pw, pe, ps, pn, pb, pt, kernel):
    result = 0.0
    bounds_e = [pe, pw]
    bounds_n = [pn, ps]
    bounds_u = [pt, pb]
    for i in range(2):
        se = bounds_e[i] - easting
        for j in range(2):
            sn = bounds_n[j] - northing
            for k in range(2):
                su = bounds_u[k] - upward
                r = math.sqrt(se**2 + sn**2 + su**2)
                result += (-1) ** (i + j + k) * kernel(se, sn, su, r)
    return result


def ref_gravity_u(ex, ny, uz, pw, pe, ps, pn, pb, pt, density):
    return G * density * _evaluate_kernel(ex, ny, uz, pw, pe, ps, pn, pb, pt, _kernel_u)


def ref_gravity_pot(ex, ny, uz, pw, pe, ps, pn, pb, pt, density):
    return G * density * _evaluate_kernel(ex, ny, uz, pw, pe, ps, pn, pb, pt, _kernel_pot)


def ref_gravity_ee(ex, ny, uz, pw, pe, ps, pn, pb, pt, density):
    return G * density * _evaluate_kernel(ex, ny, uz, pw, pe, ps, pn, pb, pt, _kernel_ee)


def ref_gravity_nn(ex, ny, uz, pw, pe, ps, pn, pb, pt, density):
    return G * density * _evaluate_kernel(ex, ny, uz, pw, pe, ps, pn, pb, pt, _kernel_nn)


def ref_gravity_uu(ex, ny, uz, pw, pe, ps, pn, pb, pt, density):
    return G * density * _evaluate_kernel(ex, ny, uz, pw, pe, ps, pn, pb, pt, _kernel_uu)


# ============================================================================
# Load data fixtures
# ============================================================================


@pytest.fixture(scope="module")
def survey_data():
    rows = []
    with open("/app/survey.csv") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "id": int(row["station_id"]),
                "lon": float(row["longitude"]),
                "lat": float(row["latitude"]),
                "height": float(row["height"]),
                "obs_gravity": float(row["observed_gravity"]),
            })
    return rows


@pytest.fixture(scope="module")
def prisms():
    with open("/app/prisms.json") as f:
        data = json.load(f)
    return [(p["west"], p["east"], p["south"], p["north"], p["bottom"], p["top"]) for p in data]


@pytest.fixture(scope="module")
def proj_string():
    with open("/app/proj_string.txt") as f:
        return f.read().strip()


@pytest.fixture(scope="module")
def eval_points():
    with open("/app/eval_points.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def projected_coords():
    path = "/app/projected_coords.json"
    assert os.path.exists(path), "projected_coords.json not found"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def normal_gravity():
    path = "/app/normal_gravity.json"
    assert os.path.exists(path), "normal_gravity.json not found"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def recovered_densities():
    path = "/app/densities.json"
    assert os.path.exists(path), "densities.json not found"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def laplace_check():
    path = "/app/laplace_check.json"
    assert os.path.exists(path), "laplace_check.json not found"
    with open(path) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def gradient_max():
    path = "/app/gradient_max.json"
    assert os.path.exists(path), "gradient_max.json not found"
    with open(path) as f:
        return json.load(f)


# ============================================================================
# Reference projection via PROJ CLI
# ============================================================================


@pytest.fixture(scope="module")
def reference_projected(survey_data, proj_string):
    """Run proj on survey coordinates to get reference projected positions."""
    input_lines = "\n".join(
        f"{s['lon']:.12f} {s['lat']:.12f}" for s in survey_data
    ) + "\n"
    result = subprocess.run(
        ["proj", "-f", "%.6f"] + proj_string.split(),
        input=input_lines, capture_output=True, text=True
    )
    assert result.returncode == 0, f"proj failed: {result.stderr}"
    coords = []
    for line in result.stdout.strip().split("\n"):
        parts = line.split()
        coords.append({"easting": float(parts[0]), "northing": float(parts[1])})
    return coords


# ============================================================================
# Tests
# ============================================================================


class TestOutputFormat:
    def test_projected_coords_exists(self):
        assert os.path.exists("/app/projected_coords.json")

    def test_projected_coords_length(self, projected_coords):
        assert len(projected_coords) == 36

    def test_projected_coords_keys(self, projected_coords):
        for i, c in enumerate(projected_coords):
            assert "easting" in c, f"Missing easting in entry {i}"
            assert "northing" in c, f"Missing northing in entry {i}"

    def test_normal_gravity_exists(self):
        assert os.path.exists("/app/normal_gravity.json")

    def test_normal_gravity_length(self, normal_gravity):
        assert len(normal_gravity) == 36

    def test_densities_exists(self):
        assert os.path.exists("/app/densities.json")

    def test_densities_length(self, recovered_densities):
        assert len(recovered_densities) == 5

    def test_laplace_exists(self):
        assert os.path.exists("/app/laplace_check.json")

    def test_laplace_length(self, laplace_check):
        assert len(laplace_check) == 8

    def test_gradient_max_exists(self):
        assert os.path.exists("/app/gradient_max.json")

    def test_gradient_max_keys(self, gradient_max):
        assert "easting" in gradient_max
        assert "northing" in gradient_max
        assert "magnitude" in gradient_max

    def test_anomaly_grid_exists(self):
        assert os.path.exists("/app/anomaly_grid.nc"), "anomaly_grid.nc not found"


class TestCoordinateProjection:
    def test_easting_accuracy(self, projected_coords, reference_projected):
        for i, (agent, ref) in enumerate(zip(projected_coords, reference_projected)):
            np.testing.assert_allclose(
                agent["easting"], ref["easting"], atol=0.1,
                err_msg=f"Easting mismatch at station {i}"
            )

    def test_northing_accuracy(self, projected_coords, reference_projected):
        for i, (agent, ref) in enumerate(zip(projected_coords, reference_projected)):
            np.testing.assert_allclose(
                agent["northing"], ref["northing"], atol=0.1,
                err_msg=f"Northing mismatch at station {i}"
            )


class TestNormalGravity:
    def test_normal_gravity_accuracy(self, normal_gravity, survey_data):
        """Normal gravity must match reference Somigliana within 0.001 mGal."""
        for i, (ng, s) in enumerate(zip(normal_gravity, survey_data)):
            ref_ng = ref_normal_gravity_mGal(s["lat"], s["height"])
            np.testing.assert_allclose(
                ng, ref_ng, atol=0.001,
                err_msg=f"Normal gravity mismatch at station {i}"
            )

    def test_normal_gravity_range(self, normal_gravity):
        """Normal gravity should be in the range for mid-latitude GRS80."""
        for i, ng in enumerate(normal_gravity):
            assert 980000 < ng < 984000, (
                f"Normal gravity at station {i} is {ng} mGal, outside expected range"
            )


class TestDensityRecovery:
    def test_density_accuracy(self, recovered_densities):
        """Recovered densities must match true values within 0.1%."""
        np.testing.assert_allclose(
            recovered_densities,
            TRUE_DENSITIES,
            rtol=1e-3,
            err_msg="Recovered densities do not match true values",
        )

    def test_density_signs(self, recovered_densities):
        for i, (rec, true) in enumerate(zip(recovered_densities, TRUE_DENSITIES)):
            if true > 0:
                assert rec > 0, f"Density {i}: expected positive, got {rec}"
            else:
                assert rec < 0, f"Density {i}: expected negative, got {rec}"


class TestForwardModelConsistency:
    def test_gravity_data_fit(self, recovered_densities, prisms, projected_coords,
                               survey_data, normal_gravity):
        """Forward-modeled gravity from recovered densities must match disturbance."""
        for s_idx in range(len(survey_data)):
            ex = projected_coords[s_idx]["easting"]
            ny = projected_coords[s_idx]["northing"]
            uz = survey_data[s_idx]["height"]
            g_computed = 0.0
            for p_idx, prism in enumerate(prisms):
                g_computed += ref_gravity_u(ex, ny, uz, *prism, recovered_densities[p_idx]) * 1e5
            disturbance = survey_data[s_idx]["obs_gravity"] - normal_gravity[s_idx]
            np.testing.assert_allclose(
                g_computed, disturbance, rtol=1e-3,
                err_msg=f"Gravity mismatch at station {s_idx}",
            )


class TestForwardModelGoldenValues:
    def test_centered_prism_golden_value(self, prisms):
        """g_u at origin from prism 0 with density 1000 must match golden value."""
        prism = prisms[0]
        gu = ref_gravity_u(0.0, 0.0, 0.0, *prism, 1000.0) * 1e5
        expected = -2.927236040238308e+00
        np.testing.assert_allclose(gu, expected, rtol=1e-10)

    def test_offset_point_golden_value(self, prisms):
        """g_u at (750, 300, 100) from prism 0 with density 1000."""
        prism = prisms[0]
        gu = ref_gravity_u(750.0, 300.0, 100.0, *prism, 1000.0) * 1e5
        expected = -1.855553794350696e+00
        np.testing.assert_allclose(gu, expected, rtol=1e-10)


class TestGMTGrid:
    def test_grid_info(self):
        """Verify GMT grid has correct region and node count."""
        result = subprocess.run(
            ["gmt", "grdinfo", "-C", "/app/anomaly_grid.nc"],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"gmt grdinfo failed: {result.stderr}"
        parts = result.stdout.strip().split()
        # grdinfo -C output: name w e s n z_min z_max dx dy nx ny [registration]
        w, e, s, n = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
        assert w == pytest.approx(-3000, abs=10)
        assert e == pytest.approx(3000, abs=10)
        assert s == pytest.approx(-3000, abs=10)
        assert n == pytest.approx(3000, abs=10)
        # Should have at least 40 nodes in each direction
        nx, ny = int(parts[9]), int(parts[10])
        assert nx >= 40, f"Too few x nodes: {nx}"
        assert ny >= 40, f"Too few y nodes: {ny}"


class TestGradientMax:
    def test_gradient_location_in_bounds(self, gradient_max):
        assert -3000 <= gradient_max["easting"] <= 3000
        assert -3000 <= gradient_max["northing"] <= 3000

    def test_gradient_magnitude_positive(self, gradient_max):
        assert gradient_max["magnitude"] > 0

    def test_gradient_magnitude_plausible(self, gradient_max):
        """Gradient should be between 1e-5 and 0.01 mGal/m for buried prisms."""
        assert 1e-5 < gradient_max["magnitude"] < 0.01, (
            f"Gradient magnitude {gradient_max['magnitude']} outside plausible range"
        )


class TestLaplaceEquation:
    def test_laplace_residual_small(self, laplace_check):
        for i, val in enumerate(laplace_check):
            assert abs(val) < 1e-15, (
                f"Laplace residual at eval point {i} is {val:.2e}, expected ~0"
            )

    def test_laplace_reference(self, prisms, recovered_densities, eval_points):
        """Independently verify Laplace equation using reference implementation."""
        for pt_idx, pt in enumerate(eval_points):
            ex, ny, uz = pt[0], pt[1], pt[2]
            total_ee = 0.0
            total_nn = 0.0
            total_uu = 0.0
            for p_idx, prism in enumerate(prisms):
                density = recovered_densities[p_idx]
                total_ee += ref_gravity_ee(ex, ny, uz, *prism, density)
                total_nn += ref_gravity_nn(ex, ny, uz, *prism, density)
                total_uu += ref_gravity_uu(ex, ny, uz, *prism, density)
            residual = total_ee + total_nn + total_uu
            assert abs(residual) < 1e-20, (
                f"Reference Laplace check failed at eval point {pt_idx}: {residual:.2e}"
            )


class TestSymmetry:
    def test_potential_vertex_symmetry(self):
        """Potential must be equal at all 8 vertices equidistant from a centered prism."""
        prism_c = (-500, 500, -500, 500, -500, 500)
        density = 1000.0
        scale = 1.5
        verts_sym = []
        for sx in [-1, 1]:
            for sy in [-1, 1]:
                for sz in [-1, 1]:
                    verts_sym.append((sx * 500 * scale, sy * 500 * scale, sz * 500 * scale))
        pots_sym = []
        for vx, vy, vz in verts_sym:
            pot = ref_gravity_pot(vx, vy, vz, *prism_c, density)
            pots_sym.append(pot)
        np.testing.assert_allclose(
            pots_sym, [pots_sym[0]] * 8, rtol=1e-12,
            err_msg="Potential not symmetric at equidistant vertices",
        )


class TestFiniteDifference:
    def test_gu_matches_fd_of_potential(self, prisms):
        """g_u must match finite-difference derivative of potential."""
        prism = prisms[0]
        density = 1000.0
        test_point = (1200.0, 800.0, 500.0)
        delta = 1e-4
        V_base = ref_gravity_pot(*test_point, *prism, density)
        V_plus = ref_gravity_pot(test_point[0], test_point[1], test_point[2] + delta, *prism, density)
        fd_gu = (V_plus - V_base) / delta
        analytical_gu = ref_gravity_u(*test_point, *prism, density)
        np.testing.assert_allclose(fd_gu, analytical_gu, rtol=1e-5)
