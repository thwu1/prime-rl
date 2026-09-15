#!/usr/bin/env python3
"""
2D Incompressible Fluid Solver — staggered MAC grid implementation.

"""
import sys
import os
import time
import tomllib
import numpy as np


U_FIELD = 0
V_FIELD = 1
S_FIELD = 2


class FluidSolver:
    def __init__(self, density, numX, numY, h):
        self.density = density
        self.numX = numX + 2
        self.numY = numY + 2
        self.numCells = self.numX * self.numY
        self.h = h

        self.u = np.zeros(self.numCells, dtype=np.float64)
        self.v = np.zeros(self.numCells, dtype=np.float64)
        self.newU = np.zeros(self.numCells, dtype=np.float64)
        self.newV = np.zeros(self.numCells, dtype=np.float64)
        self.p = np.zeros(self.numCells, dtype=np.float64)
        self.s = np.zeros(self.numCells, dtype=np.float64)
        self.m = np.ones(self.numCells, dtype=np.float64)
        self.newM = np.zeros(self.numCells, dtype=np.float64)

    def integrate(self, dt, gravity):
        n = self.numY
        for i in range(1, self.numX):
            for j in range(1, self.numY - 1):
                if self.s[i * n + j] != 0.0 and self.s[i * n + j - 1] != 0.0:
                    self.v[i * n + j] += gravity * dt

    def solve_incompressibility(self, num_iters, dt, over_relaxation):
        n = self.numY
        cp = self.density * self.h / dt

        for _ in range(num_iters):
            for i in range(1, self.numX - 1):
                for j in range(1, self.numY - 1):
                    if self.s[i * n + j] == 0.0:
                        continue

                    sx0 = self.s[(i - 1) * n + j]
                    sx1 = self.s[(i + 1) * n + j]
                    sy0 = self.s[i * n + j - 1]
                    sy1 = self.s[i * n + j + 1]
                    s_sum = sx0 + sx1 + sy0 + sy1
                    if s_sum == 0.0:
                        continue

                    div = (
                        self.u[(i + 1) * n + j]
                        - self.u[i * n + j]
                        + self.v[i * n + j + 1]
                        - self.v[i * n + j]
                    )

                    p_corr = -div / s_sum * over_relaxation
                    self.p[i * n + j] += cp * p_corr

                    self.u[i * n + j] -= sx0 * p_corr
                    self.u[(i + 1) * n + j] += sx1 * p_corr
                    self.v[i * n + j] -= sy0 * p_corr
                    self.v[i * n + j + 1] += sy1 * p_corr

    def extrapolate(self):
        n = self.numY
        for i in range(self.numX):
            self.u[i * n + 0] = self.u[i * n + 1]
            self.u[i * n + self.numY - 1] = self.u[i * n + self.numY - 2]
        for j in range(self.numY):
            self.v[0 * n + j] = self.v[1 * n + j]
            self.v[(self.numX - 1) * n + j] = self.v[(self.numX - 2) * n + j]

    def sample_field(self, x, y, field):
        n = self.numY
        h = self.h
        h1 = 1.0 / h
        h2 = 0.5 * h

        x = max(min(x, self.numX * h), h)
        y = max(min(y, self.numY * h), h)

        dx = 0.0
        dy = 0.0

        if field == U_FIELD:
            f_arr = self.u
            dy = h2
        elif field == V_FIELD:
            f_arr = self.v
            dx = h2
        else:
            f_arr = self.m
            dx = h2
            dy = h2

        x0 = min(int((x - dx) * h1), self.numX - 1)
        tx = ((x - dx) - x0 * h) * h1
        x1 = min(x0 + 1, self.numX - 1)

        y0 = min(int((y - dy) * h1), self.numY - 1)
        ty = ((y - dy) - y0 * h) * h1
        y1 = min(y0 + 1, self.numY - 1)

        sx = 1.0 - tx
        sy = 1.0 - ty

        return (
            sx * sy * f_arr[x0 * n + y0]
            + tx * sy * f_arr[x1 * n + y0]
            + tx * ty * f_arr[x1 * n + y1]
            + sx * ty * f_arr[x0 * n + y1]
        )

    def avg_u(self, i, j):
        n = self.numY
        return (
            self.u[i * n + j - 1]
            + self.u[i * n + j]
            + self.u[(i + 1) * n + j - 1]
            + self.u[(i + 1) * n + j]
        ) * 0.25

    def avg_v(self, i, j):
        n = self.numY
        return (
            self.v[(i - 1) * n + j]
            + self.v[i * n + j]
            + self.v[(i - 1) * n + j + 1]
            + self.v[i * n + j + 1]
        ) * 0.25

    def advect_vel(self, dt):
        self.newU[:] = self.u
        self.newV[:] = self.v

        n = self.numY
        h = self.h
        h2 = 0.5 * h

        for i in range(1, self.numX):
            for j in range(1, self.numY):
                # u component
                if (
                    self.s[i * n + j] != 0.0
                    and self.s[(i - 1) * n + j] != 0.0
                    and j < self.numY - 1
                ):
                    x = i * h
                    y = j * h + h2
                    u_val = self.u[i * n + j]
                    v_val = self.avg_v(i, j)
                    x -= dt * u_val
                    y -= dt * v_val
                    self.newU[i * n + j] = self.sample_field(x, y, U_FIELD)

                # v component
                if (
                    self.s[i * n + j] != 0.0
                    and self.s[i * n + j - 1] != 0.0
                    and i < self.numX - 1
                ):
                    x = i * h + h2
                    y = j * h
                    u_val = self.avg_u(i, j)
                    v_val = self.v[i * n + j]
                    x -= dt * u_val
                    y -= dt * v_val
                    self.newV[i * n + j] = self.sample_field(x, y, V_FIELD)

        self.u[:] = self.newU
        self.v[:] = self.newV

    def advect_smoke(self, dt):
        self.newM[:] = self.m

        n = self.numY
        h = self.h
        h2 = 0.5 * h

        for i in range(1, self.numX - 1):
            for j in range(1, self.numY - 1):
                if self.s[i * n + j] != 0.0:
                    u_val = (
                        self.u[i * n + j] + self.u[(i + 1) * n + j]
                    ) * 0.5
                    v_val = (
                        self.v[i * n + j] + self.v[i * n + j + 1]
                    ) * 0.5
                    x = i * h + h2 - dt * u_val
                    y = j * h + h2 - dt * v_val
                    self.newM[i * n + j] = self.sample_field(x, y, S_FIELD)

        self.m[:] = self.newM

    def simulate(self, dt, gravity, num_iters, over_relaxation, smoke_enabled):
        self.integrate(dt, gravity)
        self.p.fill(0.0)
        self.solve_incompressibility(num_iters, dt, over_relaxation)
        self.extrapolate()
        self.advect_vel(dt)
        if smoke_enabled:
            self.advect_smoke(dt)


# ======================================================================
# Geometry helpers
# ======================================================================

def point_in_polygon(x, y, vertices):
    """Ray casting algorithm for point-in-polygon test."""
    n = len(vertices)
    inside = False
    j_idx = n - 1
    for i in range(n):
        xi, yi = vertices[i]
        xj, yj = vertices[j_idx]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j_idx = i
    return inside


def read_polygon_from_obj(filepath):
    """Parse Wavefront OBJ file, extract 2D polygon (x,y from vertices)."""
    vertices = []
    face_indices = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('v '):
                parts = line.split()
                vertices.append((float(parts[1]), float(parts[2])))
            elif line.startswith('f '):
                parts = line.split()
                face_indices = [int(p.split('/')[0]) - 1 for p in parts[1:]]
    if face_indices:
        return [vertices[i] for i in face_indices]
    return vertices


# ======================================================================
# Setup helpers
# ======================================================================

def setup_boundary(fluid, config):
    n = fluid.numY
    btype = config["boundary"]["type"]

    if btype == "wind_tunnel":
        for i in range(fluid.numX):
            for j in range(fluid.numY):
                s = 1.0
                if i == 0 or j == 0 or j == fluid.numY - 1:
                    s = 0.0
                fluid.s[i * n + j] = s

        inflow = config["boundary"]["inflow_velocity"]
        for j in range(fluid.numY):
            fluid.u[1 * n + j] = inflow

    elif btype == "tank":
        for i in range(fluid.numX):
            for j in range(fluid.numY):
                s = 1.0
                if i == 0 or i == fluid.numX - 1 or j == 0:
                    s = 0.0
                fluid.s[i * n + j] = s


def setup_obstacle(fluid, config):
    if not config.get("obstacle", {}).get("enabled", False):
        return
    n = fluid.numY
    h = fluid.h

    obs_type = config["obstacle"].get("type", "circle")

    if obs_type == "circle":
        cx = config["obstacle"]["center_x"]
        cy = config["obstacle"]["center_y"]
        r = config["obstacle"]["radius"]
        for i in range(1, fluid.numX - 1):
            for j in range(1, fluid.numY - 1):
                x = (i + 0.5) * h
                y = (j + 0.5) * h
                if (x - cx) ** 2 + (y - cy) ** 2 < r * r:
                    fluid.s[i * n + j] = 0.0

    elif obs_type == "mesh":
        mesh_file = config["obstacle"]["mesh_file"]
        vertices = read_polygon_from_obj(mesh_file)
        for i in range(1, fluid.numX - 1):
            for j in range(1, fluid.numY - 1):
                x = (i + 0.5) * h
                y = (j + 0.5) * h
                if point_in_polygon(x, y, vertices):
                    fluid.s[i * n + j] = 0.0


def apply_inflow(fluid, config):
    n = fluid.numY
    btype = config["boundary"]["type"]
    if btype == "wind_tunnel":
        inflow = config["boundary"]["inflow_velocity"]
        for j in range(1, fluid.numY - 1):
            fluid.u[1 * n + j] = inflow
        if config.get("smoke", {}).get("enabled", False):
            j_min = config["smoke"]["source_j_min"]
            j_max = config["smoke"]["source_j_max"]
            for j in range(j_min, j_max):
                fluid.m[0 * n + j] = 0.0


# ======================================================================
# Main
# ======================================================================

def main():
    if len(sys.argv) < 3:
        print("Usage: python3 solver.py <config.toml> <output.npz>")
        sys.exit(1)

    config_path = sys.argv[1]
    output_path = sys.argv[2]

    with open(config_path, "rb") as f:
        config = tomllib.load(f)

    numX = config["grid"]["numX"]
    numY = config["grid"]["numY"]
    h = config["grid"]["h"]
    density = config["physics"]["density"]
    gravity = config["physics"]["gravity"]
    dt = config["physics"]["dt"]
    num_iters = config["physics"]["num_iters"]
    over_relaxation = config["physics"]["over_relaxation"]
    num_steps = config["simulation"]["num_steps"]
    smoke_enabled = config.get("smoke", {}).get("enabled", False)

    fluid = FluidSolver(density, numX, numY, h)
    setup_boundary(fluid, config)
    setup_obstacle(fluid, config)

    t0 = time.time()
    for step in range(num_steps):
        apply_inflow(fluid, config)
        fluid.simulate(dt, gravity, num_iters, over_relaxation, smoke_enabled)
    elapsed = time.time() - t0

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    np.savez(
        output_path,
        u=fluid.u,
        v=fluid.v,
        p=fluid.p,
        s=fluid.s,
        m=fluid.m,
        numX=np.int64(fluid.numX),
        numY=np.int64(fluid.numY),
        h=np.float64(h),
    )
    print(f"Saved state to {output_path} ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
