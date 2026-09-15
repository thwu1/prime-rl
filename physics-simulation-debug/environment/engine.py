"""Physics simulation engine — Python integrators and C library wrappers.
"""
import ctypes
import json
import math
import os

# ---------------------------------------------------------------------------
# Pure-Python integrators
# ---------------------------------------------------------------------------

def rk4_step(f, state, t, dt):
    """4th-order Runge-Kutta step (pure Python)."""
    k1 = f(state, t)
    s2 = [s + 0.5 * dt * k for s, k in zip(state, k1)]
    k2 = f(s2, t + 0.5 * dt)
    s3 = [s + 0.5 * dt * k for s, k in zip(state, k2)]
    k3 = f(s3, t + 0.5 * dt)
    s4 = [s + dt * k for s, k in zip(state, k3)]
    k4 = f(s4, t + dt)
    return [
        s + dt / 6.0 * (a + 2 * b + 2 * c + d)
        for s, a, b, c, d in zip(state, k1, k2, k3, k4)
    ]


# ---------------------------------------------------------------------------
# C library loading and callback types
# ---------------------------------------------------------------------------

_lib = ctypes.CDLL("/app/lib/libintegrators.so")

# accel_fn: void (*)(const double *pos, double *acc_out, int dim, const void *)
ACCEL_FN = ctypes.CFUNCTYPE(
    None,
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double),
    ctypes.c_int,
    ctypes.c_void_p,
)

_lib.verlet_step.argtypes = [
    ctypes.POINTER(ctypes.c_double),   # pos
    ctypes.POINTER(ctypes.c_double),   # vel
    ctypes.c_double,                    # dt
    ctypes.c_int,                       # dim
    ACCEL_FN,                           # accel callback
    ctypes.c_void_p,                    # params
]
_lib.verlet_step.restype = None

_lib.ftcs_step.argtypes = [
    ctypes.POINTER(ctypes.c_double),   # u
    ctypes.POINTER(ctypes.c_double),   # u_new
    ctypes.c_int,                       # n
    ctypes.c_double,                    # r
]
_lib.ftcs_step.restype = None


# ---------------------------------------------------------------------------
# Wrappers that marshal Python lists <-> ctypes arrays
# ---------------------------------------------------------------------------

_accel_ref = None  # prevent callback GC during C call


def verlet_step_c(pos, vel, dt, dim, accel_py):
    """Velocity-Verlet via C library.  accel_py(pos_list) -> acc_list."""
    global _accel_ref
    pos_arr = (ctypes.c_double * dim)(*pos)
    vel_arr = (ctypes.c_double * dim)(*vel)

    @ACCEL_FN
    def _accel(p, a, d, _params):
        pv = [p[i] for i in range(d)]
        av = accel_py(pv)
        for i in range(d):
            a[i] = av[i]

    _accel_ref = _accel
    _lib.verlet_step(pos_arr, vel_arr, ctypes.c_double(dt),
                     ctypes.c_int(dim), _accel, None)
    return [pos_arr[i] for i in range(dim)], [vel_arr[i] for i in range(dim)]


def ftcs_step_c(u_list, n, r):
    """FTCS diffusion step via C library."""
    u_in  = (ctypes.c_double * n)(*u_list)
    u_out = (ctypes.c_double * n)()
    _lib.ftcs_step(u_in, u_out, ctypes.c_int(n), ctypes.c_double(r))
    return [u_in[i] for i in range(n)]


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def save_trajectory(filepath, times, data, headers):
    with open(filepath, "w") as fh:
        json.dump({"times": times, "headers": headers, "data": data}, fh)


def load_trajectory(filepath):
    with open(filepath) as fh:
        return json.load(fh)
