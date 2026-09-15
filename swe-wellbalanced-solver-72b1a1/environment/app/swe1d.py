"""
1D shallow water equation solver for open-channel flow scenarios.
Uses compiled HLL Riemann flux library (libflux.so) via ctypes.
Outputs results in HDF5 format.
"""

import numpy as np
import ctypes
import os
import sys
import json

G = 9.81
H_DRY = 1e-2  # Wet/dry threshold


# ---------- C Library Interface ----------

def _load_hll_library():
    """Load the compiled HLL flux shared library."""
    lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "lib", "libflux.so")
    lib = ctypes.CDLL(lib_path)
    lib.hll_flux.argtypes = [
        ctypes.c_double,                    # h_L
        ctypes.c_double,                    # h_R
        ctypes.c_double,                    # hu_L
        ctypes.c_double,                    # hu_R
        ctypes.c_float,                     # g
        ctypes.POINTER(ctypes.c_double),    # F_h
        ctypes.POINTER(ctypes.c_double),    # F_hu
    ]
    lib.hll_flux.restype = None
    return lib


_hll_lib = None


def _get_hll_lib():
    global _hll_lib
    if _hll_lib is None:
        _hll_lib = _load_hll_library()
    return _hll_lib


def _hll_flux_c(h_L, h_R, hu_L, hu_R, g=G):
    """Compute HLL flux at a single interface using the C library."""
    lib = _get_hll_lib()
    F_h = ctypes.c_double(0.0)
    F_hu = ctypes.c_double(0.0)
    lib.hll_flux(h_L, h_R, hu_L, hu_R, g,
                 ctypes.byref(F_h), ctypes.byref(F_hu))
    return F_h.value, F_hu.value


# ---------- Parameter File Parsing ----------

def parse_params(filepath):
    """Parse a .dat parameter file into a dictionary.

    Format: one key per line, its value on the next non-comment, non-blank line.
    Numeric values are returned as float, non-numeric as str.
    """
    params = {}
    with open(filepath, 'r') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith('#'):
            i += 1
            continue
        key = line
        i += 1
        while i < len(lines):
            val_line = lines[i].strip()
            if val_line and not val_line.startswith('#'):
                break
            i += 1
        if i < len(lines):
            val_str = lines[i].strip()
            try:
                params[key] = float(val_str)
            except ValueError:
                params[key] = val_str
            i += 1

    return params


# ---------- Topography ----------

def bump_topo(x):
    return np.maximum(0.0, 0.2 - 0.05 * (x - 10.0) ** 2)


# ---------- Grid ----------

def _make_grid(x_min, x_max, N):
    dx = (x_max - x_min) / N
    x = np.linspace(x_min + 0.5 * dx, x_max - 0.5 * dx, N)
    return x, dx


def _time_step(h, u, dx, cfl=0.9):
    c = np.sqrt(G * np.maximum(h, 0.0))
    max_speed = np.max(np.abs(u) + c)
    if max_speed < 1e-12:
        return 1e10
    return cfl * dx / max_speed


# ---------- Boundary Conditions ----------

def _apply_bc_left(h, u, zb, bc_type, params):
    if bc_type == "wall":
        return h[0], -u[0], zb[0]
    elif bc_type == "transmissive":
        return h[0], u[0], zb[0]
    elif bc_type == "imposed_discharge":
        q_imposed = params["q"]
        h_ghost = h[0]
        if h_ghost > H_DRY:
            u_ghost = q_imposed / h_ghost
        else:
            u_ghost = 0.0
        return h_ghost, u_ghost, zb[0]
    else:
        return h[0], u[0], zb[0]


def _apply_bc_right(h, u, zb, bc_type, params):
    if bc_type == "wall":
        return h[-1], -u[-1], zb[-1]
    elif bc_type == "transmissive":
        return h[-1], u[-1], zb[-1]
    elif bc_type == "imposed_discharge":
        q_imposed = params["q"]
        h_ghost = h[-1]
        if h_ghost > H_DRY:
            u_ghost = q_imposed / h_ghost
        else:
            u_ghost = 0.0
        return h_ghost, u_ghost, zb[-1]
    else:
        return h[-1], u[-1], zb[-1]


# ---------- Godunov Step ----------

def _godunov_step(h, q, zb, dx, dt, bc_type, bc_params, n_manning=0.0):
    """One Godunov time step using the C HLL flux library."""
    N = len(h)
    u = np.zeros(N)
    for i in range(N):
        if h[i] > H_DRY:
            u[i] = q[i] / h[i]

    h_gL, u_gL, zb_gL = _apply_bc_left(h, u, zb, bc_type[0],
                                         bc_params.get("left", {}))
    h_gR, u_gR, zb_gR = _apply_bc_right(h, u, zb, bc_type[1],
                                          bc_params.get("right", {}))

    h_ext = np.concatenate(([h_gL], h, [h_gR]))
    u_ext = np.concatenate(([u_gL], u, [u_gR]))
    zb_ext = np.concatenate(([zb_gL], zb, [zb_gR]))
    hu_ext = h_ext * u_ext

    flux1 = np.zeros(N + 1)
    flux2 = np.zeros(N + 1)

    for i in range(N + 1):
        f1, f2 = _hll_flux_c(h_ext[i], h_ext[i + 1],
                              hu_ext[i], hu_ext[i + 1])
        flux1[i] = f1
        flux2[i] = f2

    h_new = h.copy()
    q_new = q.copy()

    for i in range(N):
        h_new[i] = h[i] - dt / dx * (flux1[i + 1] - flux1[i])
        # Source term: centered difference for bed slope
        q_new[i] = (q[i] - dt / dx * (flux2[i + 1] - flux2[i])
                    - dt * G * h[i] * (zb_ext[i + 2] - zb_ext[i])
                    / (2.0 * dx))

        if h_new[i] < 0:
            h_new[i] = 0.0
            q_new[i] = 0.0

    # Manning friction (implicit)
    if n_manning > 0:
        for i in range(N):
            if h_new[i] > H_DRY:
                u_val = q_new[i] / h_new[i]
                coeff = (1.0 + dt * G * n_manning ** 2 * abs(u_val)
                         / (h_new[i] ** (4.0 / 3.0)))
                q_new[i] = q_new[i] / coeff

    return h_new, q_new


# ---------- Main Solver Loop ----------

def _run_solver(x, dx, h0, q0, zb, t_end, bc_type, bc_params,
                n_manning=0.0, cfl=0.9):
    h = h0.copy()
    q = q0.copy()
    t = 0.0
    while t < t_end - 1e-14:
        u = np.zeros_like(h)
        mask = h > H_DRY
        u[mask] = q[mask] / h[mask]
        dt = _time_step(h, u, dx, cfl)
        dt = min(dt, t_end - t)
        h, q = _godunov_step(h, q, zb, dx, dt, bc_type, bc_params,
                             n_manning)
        t += dt
    u = np.zeros_like(h)
    mask = h > H_DRY
    u[mask] = q[mask] / h[mask]
    eta = h + zb
    return h, u, eta, t


# ---------- HDF5 Output ----------

def _write_hdf5(filepath, x, h, u, eta, t_final, g):
    """Write solver results to HDF5 file."""
    import h5py

    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with h5py.File(filepath, "w") as f:
        f.create_dataset("x", data=x.astype(np.float64))
        f.create_dataset("depth", data=h.astype(np.float64))
        f.create_dataset("velocity", data=u.astype(np.float64))
        f.create_dataset("eta", data=eta.astype(np.float64))
        f.create_dataset("t_final", data=np.float64(t_final))
        f.attrs["gravity"] = g


# ---------- Scenario Solvers ----------

def solve(scenario):
    """Run the solver for a predefined scenario.

    Returns dict with keys: x, h, u, eta (numpy arrays), t_final (float).
    Also writes HDF5 output to /app/output/<scenario>.h5.
    """
    if scenario == "lake_at_rest":
        return _solve_lake_at_rest()
    elif scenario == "dam_break_dry":
        return _solve_dam_break(dry=True)
    elif scenario == "dam_break_wet":
        return _solve_dam_break(dry=False)
    elif scenario == "subcritical_bump":
        return _solve_subcritical_bump()
    elif scenario == "transcritical_shock":
        return _solve_transcritical_shock()
    else:
        raise ValueError(f"Unknown scenario: {scenario}")


def _solve_lake_at_rest():
    N = 200
    x, dx = _make_grid(0.0, 25.0, N)
    zb = bump_topo(x)
    eta0 = 0.5
    h0 = np.maximum(eta0 - zb, 0.0)
    q0 = np.zeros(N)
    h, u, eta, t = _run_solver(x, dx, h0, q0, zb, 100.0,
                                bc_type=("wall", "wall"),
                                bc_params={})
    _write_hdf5(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "output", "lake_at_rest.h5"),
                x, h, u, eta, t, G)
    return {"x": x, "h": h, "u": u, "eta": eta, "t_final": t}


def _solve_dam_break(dry=True):
    N = 500
    x, dx = _make_grid(0.0, 50.0, N)
    zb = np.zeros(N)
    h_L, h_R = 5.0, (0.0 if dry else 1.0)
    h0 = np.where(x < 25.0, h_L, h_R)
    q0 = np.zeros(N)
    name = "dam_break_dry" if dry else "dam_break_wet"
    h, u, eta, t = _run_solver(x, dx, h0, q0, zb, 2.0,
                                bc_type=("transmissive", "transmissive"),
                                bc_params={})
    _write_hdf5(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "output", f"{name}.h5"),
                x, h, u, eta, t, G)
    return {"x": x, "h": h, "u": u, "eta": eta, "t_final": t}


def _solve_subcritical_bump():
    N = 200
    x, dx = _make_grid(0.0, 25.0, N)
    zb = bump_topo(x)
    q_imposed = 4.42
    h_downstream = 2.0
    h0 = np.full(N, h_downstream)
    q0 = np.full(N, q_imposed)
    h, u, eta, t = _run_solver(x, dx, h0, q0, zb, 200.0,
                                bc_type=("imposed_discharge",
                                         "imposed_height"),
                                bc_params={"left": {"q": q_imposed},
                                           "right": {"h": h_downstream}},
                                n_manning=0.0, cfl=0.5)
    _write_hdf5(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "output", "subcritical_bump.h5"),
                x, h, u, eta, t, G)
    return {"x": x, "h": h, "u": u, "eta": eta, "t_final": t}


def _solve_transcritical_shock():
    N = 200
    x, dx = _make_grid(0.0, 25.0, N)
    zb = bump_topo(x)
    q_imposed = 0.18
    h_downstream = 0.33
    h0 = np.full(N, h_downstream)
    for i in range(N):
        if h0[i] + zb[i] < zb[i] + 0.1:
            h0[i] = max(0.1, h_downstream)
    q0 = np.full(N, q_imposed)
    h, u, eta, t = _run_solver(x, dx, h0, q0, zb, 200.0,
                                bc_type=("imposed_discharge",
                                         "imposed_height"),
                                bc_params={"left": {"q": q_imposed},
                                           "right": {"h": h_downstream}},
                                n_manning=0.0, cfl=0.5)
    _write_hdf5(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "output", "transcritical_shock.h5"),
                x, h, u, eta, t, G)
    return {"x": x, "h": h, "u": u, "eta": eta, "t_final": t}


# ---------- CLI ----------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 swe1d.py <scenario>", file=sys.stderr)
        sys.exit(1)

    scenario_name = sys.argv[1]
    result = solve(scenario_name)
    output = {
        "x": result["x"].tolist(),
        "h": result["h"].tolist(),
        "u": result["u"].tolist(),
        "eta": result["eta"].tolist(),
        "t_final": float(result["t_final"]),
    }
    print(json.dumps(output))
