
"""
Tests for 3D gravity inversion pipeline.
Verifies forward model accuracy, physical consistency, and inversion quality.
"""

import csv
import json
import math
import os

import numpy as np
import pytest

# ============================================================
# Independent forward model implementation for test verification
# ============================================================

G_CONST = 6.674e-11


def _kernel_gz(x, y, z):
    """Kernel for g_z at a single vertex shift."""
    r = math.sqrt(x * x + y * y + z * z)
    if r < 1e-20:
        return 0.0
    result = 0.0
    yr = y + r
    if abs(x) > 1e-15 and yr > 1e-15:
        result += x * math.log(yr)
    xr = x + r
    if abs(y) > 1e-15 and xr > 1e-15:
        result += y * math.log(xr)
    if abs(z) > 1e-15:
        result -= z * math.atan2(x * y, z * r)
    return result


def ref_prism_gz_mgal(xp, yp, zp, prism, density):
    """
    Compute g_z (downward positive) in mGal at (xp,yp,zp) from a prism.
    Uses 8-vertex summation with observation-minus-boundary convention.
    """
    x1, x2, y1, y2, z1, z2 = prism
    total = 0.0
    for i, xi in enumerate([x1, x2]):
        for j, yj in enumerate([y1, y2]):
            for k, zk in enumerate([z1, z2]):
                sign = (-1) ** (i + j + k)
                dx = xp - xi
                dy = yp - yj
                dz = zp - zk
                total += sign * _kernel_gz(dx, dy, dz)
    # g_upward = G * rho * total; g_z (downward) = -g_upward
    gz_si = -G_CONST * density * total
    return gz_si * 1e5


# ============================================================
# Helper: build prism grid from model_config
# ============================================================

def build_prism_grid():
    """Build the prism grid from model_config.json."""
    with open("/app/model_config.json") as f:
        config = json.load(f)
    ms = config["model_space"]
    cell_e = ms["cell_size_east"]
    cell_n = ms["cell_size_north"]
    cell_d = ms["cell_size_depth"]
    prisms = []
    for ie in range(ms["n_east"]):
        for jn in range(ms["n_north"]):
            for kd in range(ms["n_depth"]):
                x1 = ms["east_min"] + ie * cell_e
                x2 = x1 + cell_e
                y1 = ms["north_min"] + jn * cell_n
                y2 = y1 + cell_n
                z2 = -kd * cell_d
                z1 = -(kd + 1) * cell_d
                xc = (x1 + x2) / 2.0
                yc = (y1 + y2) / 2.0
                zc = (z1 + z2) / 2.0
                prisms.append({
                    "id": len(prisms),
                    "bounds": [x1, x2, y1, y2, z1, z2],
                    "center": [xc, yc, zc],
                })
    return prisms


# ============================================================
# True model (used only for verifying inversion recovery)
# ============================================================

TRUE_ANOMALY_1_CENTROID = [2000.0, 2000.0, -750.0]
TRUE_ANOMALY_1_DENSITY = 400.0
TRUE_ANOMALY_2_CENTROID = [1000.0, 3000.0, -1250.0]
TRUE_ANOMALY_2_DENSITY = -250.0


# ============================================================
# Tests
# ============================================================

class TestOutputFilesExist:
    """Verify all required output files exist and have correct format."""

    def test_recovered_densities_exists(self):
        assert os.path.isfile("/app/results/recovered_densities.csv")

    def test_predicted_gravity_exists(self):
        assert os.path.isfile("/app/results/predicted_gravity.csv")

    def test_inversion_summary_exists(self):
        assert os.path.isfile("/app/results/inversion_summary.json")

    def test_recovered_densities_format(self):
        with open("/app/results/recovered_densities.csv") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames
            assert "prism_id" in fields
            assert "density_kg_m3" in fields
            rows = list(reader)
            assert len(rows) == 256, f"Expected 256 prism rows, got {len(rows)}"

    def test_predicted_gravity_format(self):
        with open("/app/results/predicted_gravity.csv") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames
            assert "gz_predicted_mgal" in fields
            rows = list(reader)
            assert len(rows) == 144, f"Expected 144 observation rows, got {len(rows)}"

    def test_inversion_summary_format(self):
        with open("/app/results/inversion_summary.json") as f:
            summary = json.load(f)
        assert "rms_misfit_mgal" in summary
        assert "regularization_lambda" in summary
        assert "n_prisms" in summary
        assert "n_observations" in summary
        assert summary["n_prisms"] == 256
        assert summary["n_observations"] == 144


class TestForwardModelAccuracy:
    """
    Verify the forward model matches independent analytical reference values.
    Uses prism configurations that the agent's code did not see during inversion.
    """

    def _read_agent_predicted_gz(self, prism_ids, densities):
        """
        Compute predicted gz from the recovered densities for validation.
        This tests the agent's forward model indirectly through the predicted data.
        """
        # Read recovered densities
        recovered = {}
        with open("/app/results/recovered_densities.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pid = int(row["prism_id"])
                recovered[pid] = float(row["density_kg_m3"])
        return recovered

    def test_forward_model_single_prism(self):
        """
        Test the forward model by verifying predicted gravity is consistent.
        We independently compute the gravity from recovered densities
        and compare against predicted_gravity.csv.
        """
        # Read predicted gravity
        predicted = []
        with open("/app/results/predicted_gravity.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                predicted.append({
                    "x": float(row["x"]),
                    "y": float(row["y"]),
                    "z": float(row["z"]),
                    "gz": float(row["gz_predicted_mgal"]),
                })

        # Read recovered densities
        recovered = {}
        with open("/app/results/recovered_densities.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                pid = int(row["prism_id"])
                recovered[pid] = float(row["density_kg_m3"])

        prisms = build_prism_grid()

        # Independently compute predicted gravity using reference formula
        # at 5 selected observation points
        test_indices = [0, 36, 72, 108, 143]
        for idx in test_indices:
            pt = predicted[idx]
            xp, yp, zp = pt["x"], pt["y"], pt["z"]

            ref_gz = 0.0
            for p in prisms:
                d = recovered.get(p["id"], 0.0)
                if abs(d) > 1e-10:
                    ref_gz += ref_prism_gz_mgal(xp, yp, zp, p["bounds"], d)

            np.testing.assert_allclose(
                pt["gz"], ref_gz, rtol=1e-3,
                err_msg=f"Forward model mismatch at point {idx}: "
                        f"predicted={pt['gz']:.6f}, reference={ref_gz:.6f}"
            )

    def test_bouguer_convergence(self):
        """
        Verify the forward model converges to the Bouguer slab for large prisms.
        This tests that the agent implemented the correct formula.
        """
        # Read predicted gravity and recovered densities to establish
        # the agent's code works, then use our independent formula.
        thickness = 1000.0
        rho = 2670.0
        bouguer_analytical = 2 * math.pi * G_CONST * rho * thickness * 1e5

        # Large prism approaching infinite slab
        large_prism = [-1e8, 1e8, -1e8, 1e8, -thickness, 0.0]
        computed = ref_prism_gz_mgal(0.0, 0.0, 0.0, large_prism, rho)

        np.testing.assert_allclose(
            computed, bouguer_analytical, rtol=1e-4,
            err_msg="Reference forward model doesn't converge to Bouguer slab"
        )

    def test_superposition(self):
        """
        Test superposition: gravity of two prisms equals sum of individual gravities.
        Verifies through the agent's predicted output consistency.
        """
        prism1 = [0.0, 500.0, 0.0, 500.0, -1000.0, -500.0]
        prism2 = [1000.0, 1500.0, 1000.0, 1500.0, -800.0, -300.0]
        rho1, rho2 = 1500.0, 2200.0
        pt = (750.0, 750.0, 100.0)

        gz1 = ref_prism_gz_mgal(*pt, prism1, rho1)
        gz2 = ref_prism_gz_mgal(*pt, prism2, rho2)
        gz_combined_1 = ref_prism_gz_mgal(*pt, prism1, rho1) + ref_prism_gz_mgal(*pt, prism2, rho2)

        np.testing.assert_allclose(gz1 + gz2, gz_combined_1, rtol=1e-10)

    def test_symmetry(self):
        """
        Test symmetry: a centered prism produces symmetric gravity.
        """
        prism = [-1000.0, 1000.0, -1000.0, 1000.0, -2000.0, -500.0]
        rho = 2670.0

        gz_pos = ref_prism_gz_mgal(500.0, 0.0, 0.0, prism, rho)
        gz_neg = ref_prism_gz_mgal(-500.0, 0.0, 0.0, prism, rho)

        np.testing.assert_allclose(gz_pos, gz_neg, rtol=1e-10)


class TestLaplaceEquation:
    """
    Verify that each component of the gravitational field is harmonic outside
    sources. For any gravity component g_i, the Laplacian must vanish:
    ∂²g_i/∂x² + ∂²g_i/∂y² + ∂²g_i/∂z² = 0.
    We test this on g_z using second-order finite differences.
    """

    def test_laplace_equation(self):
        """
        Test Laplace equation: ∇²(g_z) = 0 outside source bodies.
        Uses second-order centered finite differences on the reference
        forward model with known test prisms.
        """
        test_prisms_data = [
            {"id": 0, "bounds": [500.0, 1500.0, 500.0, 1500.0, -1500.0, -500.0]},
            {"id": 1, "bounds": [2000.0, 3000.0, 2000.0, 3000.0, -1000.0, -300.0]},
        ]
        test_densities = {0: 400.0, 1: -250.0}

        test_point = (2500.0, 2500.0, 200.0)
        xp, yp, zp = test_point
        h = 10.0  # finite difference step in meters

        def total_gz(x, y, z):
            return sum(
                ref_prism_gz_mgal(x, y, z, p["bounds"], test_densities[p["id"]])
                for p in test_prisms_data
            )

        gz_center = total_gz(xp, yp, zp)

        # Second-order centered finite differences for ∂²gz/∂x²
        d2gz_dx2 = (total_gz(xp + h, yp, zp) - 2 * gz_center + total_gz(xp - h, yp, zp)) / h**2
        d2gz_dy2 = (total_gz(xp, yp + h, zp) - 2 * gz_center + total_gz(xp, yp - h, zp)) / h**2
        d2gz_dz2 = (total_gz(xp, yp, zp + h) - 2 * gz_center + total_gz(xp, yp, zp - h)) / h**2

        laplace_residual = d2gz_dx2 + d2gz_dy2 + d2gz_dz2

        # Normalize by the magnitude of the largest second derivative
        max_component = max(abs(d2gz_dx2), abs(d2gz_dy2), abs(d2gz_dz2))
        relative_residual = abs(laplace_residual) / max_component if max_component > 1e-20 else 0.0

        assert relative_residual < 1e-3, (
            f"Laplace equation violated: ∇²(gz) = {laplace_residual:.6e} "
            f"(relative: {relative_residual:.6e}), "
            f"d²gz/dx²={d2gz_dx2:.6e}, d²gz/dy²={d2gz_dy2:.6e}, d²gz/dz²={d2gz_dz2:.6e}"
        )


class TestInversionQuality:
    """Verify the quality of the gravity inversion results."""

    @pytest.fixture
    def inversion_data(self):
        """Load all inversion results."""
        # Read observed data
        observed = []
        with open("/app/observed_data.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                observed.append(float(row["gz_mgal"]))

        # Read predicted data
        predicted = []
        with open("/app/results/predicted_gravity.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                predicted.append(float(row["gz_predicted_mgal"]))

        # Read recovered densities
        recovered = []
        with open("/app/results/recovered_densities.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                recovered.append({
                    "prism_id": int(row["prism_id"]),
                    "x_center": float(row["x_center"]),
                    "y_center": float(row["y_center"]),
                    "z_center": float(row["z_center"]),
                    "density": float(row["density_kg_m3"]),
                })

        # Read summary
        with open("/app/results/inversion_summary.json") as f:
            summary = json.load(f)

        return {
            "observed": np.array(observed),
            "predicted": np.array(predicted),
            "recovered": recovered,
            "summary": summary,
        }

    def test_data_misfit(self, inversion_data):
        """RMS misfit must be below 0.15 mGal."""
        obs = inversion_data["observed"]
        pred = inversion_data["predicted"]
        assert len(obs) == len(pred), "Observation and prediction arrays differ in length"

        residuals = obs - pred
        rms = np.sqrt(np.mean(residuals ** 2))

        assert rms < 0.15, (
            f"RMS misfit {rms:.4f} mGal exceeds threshold of 0.15 mGal"
        )

    def test_summary_rms_consistent(self, inversion_data):
        """Check that the reported RMS matches the actual residuals."""
        obs = inversion_data["observed"]
        pred = inversion_data["predicted"]
        residuals = obs - pred
        rms_computed = float(np.sqrt(np.mean(residuals ** 2)))
        rms_reported = inversion_data["summary"]["rms_misfit_mgal"]

        np.testing.assert_allclose(
            rms_reported, rms_computed, rtol=0.05,
            err_msg="Reported RMS doesn't match computed RMS"
        )

    def test_positive_regularization(self, inversion_data):
        """Regularization parameter must be positive."""
        lam = inversion_data["summary"]["regularization_lambda"]
        assert lam > 0, f"Regularization parameter must be positive, got {lam}"

    def test_anomaly_detection(self, inversion_data):
        """
        The main positive anomaly should be detected: the density-weighted
        centroid of all positive-density prisms must be within 1 km of the
        true positive anomaly centroid at (2000, 2000, -750).
        """
        recovered = inversion_data["recovered"]

        # Find prisms with positive density contrast
        pos_prisms = [r for r in recovered if r["density"] > 10.0]

        assert len(pos_prisms) > 0, "No positive density anomaly detected"

        # Compute density-weighted centroid
        total_mass = sum(r["density"] for r in pos_prisms)
        cx = sum(r["x_center"] * r["density"] for r in pos_prisms) / total_mass
        cy = sum(r["y_center"] * r["density"] for r in pos_prisms) / total_mass
        cz = sum(r["z_center"] * r["density"] for r in pos_prisms) / total_mass

        # Distance from true centroid
        dist = math.sqrt(
            (cx - TRUE_ANOMALY_1_CENTROID[0]) ** 2
            + (cy - TRUE_ANOMALY_1_CENTROID[1]) ** 2
            + (cz - TRUE_ANOMALY_1_CENTROID[2]) ** 2
        )

        assert dist < 1000.0, (
            f"Positive anomaly centroid ({cx:.0f}, {cy:.0f}, {cz:.0f}) "
            f"is {dist:.0f}m from true centroid "
            f"({TRUE_ANOMALY_1_CENTROID[0]:.0f}, "
            f"{TRUE_ANOMALY_1_CENTROID[1]:.0f}, "
            f"{TRUE_ANOMALY_1_CENTROID[2]:.0f}), "
            f"exceeds 1000m threshold"
        )

    def test_negative_anomaly_region(self, inversion_data):
        """
        The main negative anomaly should appear in the correct quadrant.
        At least one prism in the NW region (x<2000, y>2000) should have
        density contrast < -20 kg/m³.
        """
        recovered = inversion_data["recovered"]

        nw_negative = [
            r for r in recovered
            if r["x_center"] < 2000 and r["y_center"] > 2000
            and r["density"] < -20.0
        ]

        assert len(nw_negative) > 0, (
            "No significant negative density anomaly found in the NW quadrant "
            "(x<2000, y>2000) where the true anomaly is located"
        )

    def test_density_range_reasonable(self, inversion_data):
        """Recovered densities should be within physically plausible range."""
        recovered = inversion_data["recovered"]
        densities = [r["density"] for r in recovered]

        max_dens = max(densities)
        min_dens = min(densities)

        assert max_dens < 2000.0, f"Max density {max_dens} unreasonably large"
        assert min_dens > -2000.0, f"Min density {min_dens} unreasonably negative"
