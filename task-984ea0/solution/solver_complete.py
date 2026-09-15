
import numpy as np
import ctypes
import os


def solver(Vx0, density0, pressure0, t_coordinate, eta, zeta):
    """Solve the 1D compressible Navier-Stokes equations using C kernels."""

    # ── Load C library ───────────────────────────────────────────────
    lib_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "src", "libkernels.so"
    )
    if not os.path.exists(lib_path):
        raise RuntimeError(
            f"Compiled library not found at {lib_path}. "
            "Build it first: make -C /app/src"
        )
    lib = ctypes.CDLL(lib_path)

    # ── ctypes setup ─────────────────────────────────────────────────
    DP = ctypes.POINTER(ctypes.c_double)

    lib.compute_rhs.argtypes = [
        DP, DP, DP, DP, DP, DP,
        ctypes.c_int, ctypes.c_double, ctypes.c_double, ctypes.c_double,
        ctypes.c_double, ctypes.c_double,
    ]
    lib.compute_rhs.restype = None

    lib.euler_step.argtypes = [
        DP, DP, DP, DP, DP, DP, ctypes.c_int, ctypes.c_double,
    ]
    lib.euler_step.restype = None

    lib.compute_cfl_timestep.argtypes = [
        DP, DP, DP, ctypes.c_int,
        ctypes.c_double, ctypes.c_double, ctypes.c_double,
        ctypes.c_double, ctypes.c_double, ctypes.c_double,
    ]
    lib.compute_cfl_timestep.restype = ctypes.c_double

    lib.has_nan.argtypes = [DP, ctypes.c_int]
    lib.has_nan.restype = ctypes.c_int

    # ── Constants ────────────────────────────────────────────────────
    GAMMA = 5.0 / 3.0
    SAFETY = 0.1
    MIN_DT = 5e-7
    MAX_DT = 1e-4
    ART_VISC = 1.5

    batch_size, N = Vx0.shape
    T = len(t_coordinate) - 1
    dx = 2.0 / (N - 1)

    # ── Allocate output ──────────────────────────────────────────────
    Vx_pred = np.zeros((batch_size, T + 1, N), dtype=np.float64)
    density_pred = np.zeros((batch_size, T + 1, N), dtype=np.float64)
    pressure_pred = np.zeros((batch_size, T + 1, N), dtype=np.float64)
    Vx_pred[:, 0] = Vx0
    density_pred[:, 0] = density0
    pressure_pred[:, 0] = pressure0

    def ptr(a):
        return a.ctypes.data_as(DP)

    # ── Time integration (per batch element) ─────────────────────────
    for b in range(batch_size):
        cv = np.ascontiguousarray(Vx0[b], dtype=np.float64).copy()
        cd = np.ascontiguousarray(density0[b], dtype=np.float64).copy()
        cp = np.ascontiguousarray(pressure0[b], dtype=np.float64).copy()
        drho = np.zeros(N, dtype=np.float64)
        dv = np.zeros(N, dtype=np.float64)
        dp = np.zeros(N, dtype=np.float64)
        t_cur = 0.0

        for step in range(1, T + 1):
            t_tgt = float(t_coordinate[step])

            while t_cur < t_tgt - 1e-12:
                # NaN recovery
                if (lib.has_nan(ptr(cv), N) or
                        lib.has_nan(ptr(cd), N) or
                        lib.has_nan(ptr(cp), N)):
                    if step > 1:
                        cv[:] = Vx_pred[b, step - 1]
                        cd[:] = density_pred[b, step - 1]
                        cp[:] = pressure_pred[b, step - 1]
                    else:
                        cv[:] = Vx0[b]
                        cd[:] = density0[b]
                        cp[:] = pressure0[b]

                rem = t_tgt - t_cur
                dt = lib.compute_cfl_timestep(
                    ptr(cv), ptr(cd), ptr(cp),
                    N, dx, GAMMA, SAFETY, MIN_DT, MAX_DT, rem,
                )

                lib.compute_rhs(
                    ptr(cv), ptr(cd), ptr(cp),
                    ptr(drho), ptr(dv), ptr(dp),
                    N, dx, eta, zeta, GAMMA, ART_VISC,
                )

                # NaN-guard the RHS
                drho[np.isnan(drho)] = 0.0
                dv[np.isnan(dv)] = 0.0
                dp[np.isnan(dp)] = 0.0

                lib.euler_step(
                    ptr(cv), ptr(cd), ptr(cp),
                    ptr(drho), ptr(dv), ptr(dp),
                    N, dt,
                )
                t_cur += dt

            Vx_pred[b, step] = cv
            density_pred[b, step] = cd
            pressure_pred[b, step] = cp

    return Vx_pred, density_pred, pressure_pred
