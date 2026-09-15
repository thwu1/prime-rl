"""Tests for 2D incompressible flow solver.

Verifies physical invariants across four simulation scenarios without
depending on specific algorithmic choices.

"""
import pytest
import numpy as np
import os


def load_output(scenario_name):
    path = f"/app/output/{scenario_name}.npz"
    assert os.path.exists(path), f"Output {path} not found. Did the solver run?"
    return dict(np.load(path))


# Polygon vertices from bluff_body.obj (complex_flow obstacle)
BLUFF_BODY_VERTICES = [
    (0.38, 0.38),
    (0.52, 0.30),
    (0.62, 0.37),
    (0.57, 0.50),
    (0.42, 0.48),
]


def point_in_polygon(x, y, vertices):
    """Ray casting point-in-polygon test."""
    n = len(vertices)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = vertices[i]
        xj, yj = vertices[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


# ---------------------------------------------------------------------------
# Wind Tunnel Tests
# ---------------------------------------------------------------------------

class TestWindTunnel:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_output("wind_tunnel")
        self.numX = int(self.data["numX"])
        self.numY = int(self.data["numY"])
        self.u = self.data["u"].flatten()
        self.v = self.data["v"].flatten()
        self.p = self.data["p"].flatten()
        self.s = self.data["s"].flatten()
        self.m = self.data["m"].flatten()
        self.h = float(self.data["h"])

    def test_output_format(self):
        """Output must contain all required keys with correct sizes."""
        for key in ["u", "v", "p", "s", "m", "numX", "numY", "h"]:
            assert key in self.data, f"Missing key: {key}"
        n = self.numX * self.numY
        assert self.u.size == n, f"u size {self.u.size} != {n}"
        assert self.v.size == n, f"v size {self.v.size} != {n}"
        assert self.p.size == n, f"p size {self.p.size} != {n}"
        assert self.s.size == n, f"s size {self.s.size} != {n}"
        assert self.m.size == n, f"m size {self.m.size} != {n}"

    def test_divergence_free(self):
        """Velocity field must be nearly divergence-free at fluid cells."""
        n = self.numY
        divs = []
        for i in range(1, self.numX - 1):
            for j in range(1, self.numY - 1):
                if self.s[i * n + j] == 0.0:
                    continue
                div = abs(
                    self.u[(i + 1) * n + j] - self.u[i * n + j]
                    + self.v[i * n + j + 1] - self.v[i * n + j]
                )
                divs.append(div)
        divs = np.array(divs)
        p95 = np.percentile(divs, 95)
        assert p95 < 0.1, f"95th-percentile divergence {p95:.4f} >= 0.1"

    def test_inflow_boundary(self):
        """Horizontal velocity at inlet must match inflow_velocity."""
        n = self.numY
        inflow_vel = 2.0
        errors = []
        for j in range(1, self.numY - 1):
            if self.s[1 * n + j] == 0.0:
                continue
            u_val = self.u[1 * n + j]
            if abs(u_val - inflow_vel) > 0.5:
                errors.append((j, u_val))
        assert len(errors) == 0, (
            f"Inflow velocity deviates at {len(errors)} cells, "
            f"first 5: {errors[:5]}"
        )

    def test_obstacle_solid_cells(self):
        """Cells well inside the circular obstacle must be marked solid."""
        n = self.numY
        cx, cy, r = 0.8, 0.5, 0.15
        solid_count = 0
        for i in range(1, self.numX - 1):
            for j in range(1, self.numY - 1):
                x = (i + 0.5) * self.h
                y = (j + 0.5) * self.h
                dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                if dist < r * 0.7:
                    assert self.s[i * n + j] == 0.0, (
                        f"Cell ({i},{j}) at dist {dist:.3f} should be solid"
                    )
                    solid_count += 1
        assert solid_count >= 3, f"Only {solid_count} solid cells inside obstacle"


# ---------------------------------------------------------------------------
# Hydrostatic Tank Tests
# ---------------------------------------------------------------------------

class TestHydrostatic:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_output("hydrostatic")
        self.numX = int(self.data["numX"])
        self.numY = int(self.data["numY"])
        self.u = self.data["u"].flatten()
        self.v = self.data["v"].flatten()
        self.p = self.data["p"].flatten()
        self.s = self.data["s"].flatten()

    def test_output_format(self):
        for key in ["u", "v", "p", "s", "numX", "numY", "h"]:
            assert key in self.data, f"Missing key: {key}"

    def test_velocity_equilibrium(self):
        """After many steps, velocity in hydrostatic tank should be near zero."""
        n = self.numY
        max_vel = 0.0
        for i in range(1, self.numX - 1):
            for j in range(1, self.numY - 1):
                if self.s[i * n + j] == 0.0:
                    continue
                vel = (self.u[i * n + j] ** 2 + self.v[i * n + j] ** 2) ** 0.5
                max_vel = max(max_vel, vel)
        assert max_vel < 1.0, (
            f"Max velocity {max_vel:.4f} too large — "
            f"hydrostatic equilibrium not reached"
        )

    def test_pressure_increases_with_depth(self):
        """Pressure at the bottom must exceed pressure near the top."""
        n = self.numY
        bottom_pressures = []
        top_pressures = []

        top_j = 1
        for j in range(self.numY - 2, 0, -1):
            for i in range(1, self.numX - 1):
                if self.s[i * n + j] != 0.0:
                    top_j = j
                    break
            if top_j > 1:
                break

        for i in range(1, self.numX - 1):
            if self.s[i * n + 1] != 0.0:
                bottom_pressures.append(self.p[i * n + 1])
            if self.s[i * n + top_j] != 0.0:
                top_pressures.append(self.p[i * n + top_j])

        assert len(bottom_pressures) > 0, "No fluid cells at bottom row"
        assert len(top_pressures) > 0, "No fluid cells at top row"
        avg_bottom = np.mean(bottom_pressures)
        avg_top = np.mean(top_pressures)
        assert avg_bottom > avg_top, (
            f"Bottom pressure ({avg_bottom:.2f}) must exceed "
            f"top pressure ({avg_top:.2f})"
        )


# ---------------------------------------------------------------------------
# Channel Flow Tests
# ---------------------------------------------------------------------------

class TestChannelFlow:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_output("channel_flow")
        self.numX = int(self.data["numX"])
        self.numY = int(self.data["numY"])
        self.u = self.data["u"].flatten()
        self.v = self.data["v"].flatten()
        self.s = self.data["s"].flatten()
        self.m = self.data["m"].flatten()

    def test_output_format(self):
        for key in ["u", "v", "p", "s", "m", "numX", "numY", "h"]:
            assert key in self.data, f"Missing key: {key}"

    def test_divergence_free(self):
        """Channel flow must also be divergence-free."""
        n = self.numY
        max_div = 0.0
        for i in range(1, self.numX - 1):
            for j in range(1, self.numY - 1):
                if self.s[i * n + j] == 0.0:
                    continue
                div = abs(
                    self.u[(i + 1) * n + j] - self.u[i * n + j]
                    + self.v[i * n + j + 1] - self.v[i * n + j]
                )
                max_div = max(max_div, div)
        assert max_div < 0.05, f"Max divergence {max_div:.6f} exceeds 0.05"

    def test_smoke_within_bounds(self):
        """Smoke density must remain in physically valid range."""
        assert np.all(self.m >= -0.05), (
            f"Smoke below valid range: min={self.m.min():.4f}"
        )
        assert np.all(self.m <= 1.05), (
            f"Smoke above valid range: max={self.m.max():.4f}"
        )


# ---------------------------------------------------------------------------
# Complex Flow Tests (polygon obstacle from OBJ mesh)
# ---------------------------------------------------------------------------

class TestComplexFlow:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.data = load_output("complex_flow")
        self.numX = int(self.data["numX"])
        self.numY = int(self.data["numY"])
        self.u = self.data["u"].flatten()
        self.v = self.data["v"].flatten()
        self.p = self.data["p"].flatten()
        self.s = self.data["s"].flatten()
        self.m = self.data["m"].flatten()
        self.h = float(self.data["h"])

    def test_output_format(self):
        """Output must contain all required keys with correct sizes."""
        for key in ["u", "v", "p", "s", "m", "numX", "numY", "h"]:
            assert key in self.data, f"Missing key: {key}"
        n = self.numX * self.numY
        assert self.u.size == n, f"u size {self.u.size} != {n}"
        assert self.v.size == n, f"v size {self.v.size} != {n}"

    def test_polygon_obstacle_solid_cells(self):
        """Cells well inside the OBJ-defined polygon must be marked solid."""
        n = self.numY
        h = self.h
        solid_inside = 0
        violations = []

        for i in range(1, self.numX - 1):
            for j in range(1, self.numY - 1):
                x = (i + 0.5) * h
                y = (j + 0.5) * h
                if point_in_polygon(x, y, BLUFF_BODY_VERTICES):
                    margin = h * 1.5
                    all_inside = all(
                        point_in_polygon(x + dx, y + dy, BLUFF_BODY_VERTICES)
                        for dx in [-margin, 0, margin]
                        for dy in [-margin, 0, margin]
                    )
                    if all_inside:
                        if self.s[i * n + j] == 0.0:
                            solid_inside += 1
                        else:
                            violations.append((i, j, x, y))

        assert len(violations) == 0, (
            f"{len(violations)} cells well inside polygon are not solid: "
            f"{violations[:5]}"
        )
        assert solid_inside >= 5, (
            f"Only {solid_inside} solid cells found inside polygon"
        )

    def test_polygon_obstacle_exterior_fluid(self):
        """Cells well outside the polygon must remain fluid."""
        n = self.numY
        h = self.h
        violations = []

        for i in range(2, self.numX - 2):
            for j in range(2, self.numY - 2):
                x = (i + 0.5) * h
                y = (j + 0.5) * h
                if not point_in_polygon(x, y, BLUFF_BODY_VERTICES):
                    margin = h * 2.0
                    all_outside = not any(
                        point_in_polygon(x + dx, y + dy, BLUFF_BODY_VERTICES)
                        for dx in [-margin, 0, margin]
                        for dy in [-margin, 0, margin]
                    )
                    if all_outside and self.s[i * n + j] == 0.0:
                        violations.append((i, j, x, y))

        assert len(violations) == 0, (
            f"{len(violations)} cells well outside polygon are incorrectly solid: "
            f"{violations[:5]}"
        )

    def test_divergence_free(self):
        """Flow past polygon obstacle must be nearly divergence-free."""
        n = self.numY
        divs = []
        for i in range(1, self.numX - 1):
            for j in range(1, self.numY - 1):
                if self.s[i * n + j] == 0.0:
                    continue
                div = abs(
                    self.u[(i + 1) * n + j] - self.u[i * n + j]
                    + self.v[i * n + j + 1] - self.v[i * n + j]
                )
                divs.append(div)
        divs = np.array(divs)
        p95 = np.percentile(divs, 95)
        assert p95 < 0.15, f"95th-percentile divergence {p95:.4f} >= 0.15"

    def test_no_velocity_blowup(self):
        """Velocity magnitudes must remain bounded (no numerical instability)."""
        max_vel = max(np.max(np.abs(self.u)), np.max(np.abs(self.v)))
        assert max_vel < 50.0, (
            f"Max velocity {max_vel:.2f} indicates numerical blowup"
        )

    def test_scalar_field_untouched(self):
        """With smoke disabled, scalar field must remain at initial value."""
        fluid_mask = self.s > 0.5
        fluid_m = self.m[fluid_mask]
        assert np.allclose(fluid_m, 1.0, atol=0.01), (
            f"Scalar field modified when smoke disabled: "
            f"min={fluid_m.min():.4f}, max={fluid_m.max():.4f}"
        )
