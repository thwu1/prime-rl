"""1D Compressible Navier-Stokes solver using pure NumPy.

Forward Euler time integration with adaptive CFL-based timestep,
central finite differences, artificial viscosity, and positivity preservation.

"""
import numpy as np


def solver(Vx0, density0, pressure0, t_coordinate, eta, zeta):
    """Solves the 1D compressible Navier-Stokes equations for all times."""

    Vx0 = np.asarray(Vx0, dtype=np.float64)
    density0 = np.asarray(density0, dtype=np.float64)
    pressure0 = np.asarray(pressure0, dtype=np.float64)
    t_coordinate = np.asarray(t_coordinate, dtype=np.float64)

    batch_size, N = Vx0.shape
    T = len(t_coordinate) - 1

    # Physical constants
    GAMMA = 5.0 / 3.0
    # Grid: N points on [-1, 1] with both endpoints included (coincident
    # under periodic BCs), so there are N-1 distinct cells.
    dx = 2.0 / (N - 1)
    inv_2dx = 0.5 / dx
    inv_dx2 = 1.0 / (dx * dx)

    # Effective viscosity: zeta + 4*eta/3
    mu = eta + zeta + eta / 3.0

    # CFL safety factors
    HYPER_CFL = 0.15
    VISC_CFL = 0.4
    ART_VISC_COEFF = 1.5

    # Output arrays
    Vx_out = np.zeros((batch_size, T + 1, N), dtype=np.float64)
    rho_out = np.zeros((batch_size, T + 1, N), dtype=np.float64)
    p_out = np.zeros((batch_size, T + 1, N), dtype=np.float64)

    Vx_out[:, 0] = Vx0
    rho_out[:, 0] = density0
    p_out[:, 0] = pressure0

    # Working arrays
    v = Vx0.copy()
    rho = density0.copy()
    p = pressure0.copy()

    def _pad(x):
        """Periodic padding for coincident-endpoint grid.
        x[0] and x[N-1] represent the same physical point, so the
        left ghost value is x[N-2] and the right ghost value is x[1]."""
        return np.concatenate([x[:, -2:-1], x, x[:, 1:2]], axis=1)

    t_now = float(t_coordinate[0])

    for save_idx in range(1, T + 1):
        t_target = float(t_coordinate[save_idx])

        while t_now < t_target - 1e-14:
            # Adaptive CFL timestep
            cs = np.sqrt(GAMMA * np.maximum(p, 1e-8) / np.maximum(rho, 1e-8))
            max_wave = np.max(np.abs(v) + cs)

            dt_hyp = HYPER_CFL * dx / (max_wave + 1e-10)
            dt_vis = VISC_CFL * dx * dx / (2.0 * mu + 1e-10)
            dt = min(dt_hyp, dt_vis, t_target - t_now)
            dt = max(dt, 1e-9)

            # Velocity derivatives
            vp = _pad(v)
            dv_dx = (vp[:, 2:] - vp[:, :-2]) * inv_2dx
            d2v_dx2 = (vp[:, 2:] - 2.0 * v + vp[:, :-2]) * inv_dx2

            # Continuity: drho/dt = -d(rho*v)/dx
            rv = rho * v
            rvp = _pad(rv)
            drho_dt = -(rvp[:, 2:] - rvp[:, :-2]) * inv_2dx

            # Momentum (non-conservative):
            # dv/dt = -v*dv/dx - (1/rho)*dp/dx + mu*d2v/dx2
            pp = _pad(p)
            dp_dx = (pp[:, 2:] - pp[:, :-2]) * inv_2dx
            safe_rho = np.maximum(rho, 1e-4)

            dv_dt = -v * dv_dx - dp_dx / safe_rho + mu * d2v_dx2

            # Artificial viscosity for shock stabilization
            art_visc = ART_VISC_COEFF * rho * dx * dx * np.abs(dv_dx) * dv_dx
            dv_dt = dv_dt + art_visc
            dv_dt = np.clip(dv_dt, -100.0, 100.0)

            # Energy equation
            epsilon = p / (GAMMA - 1.0)
            E = epsilon + 0.5 * rho * v * v
            sigma = mu * dv_dx
            E_flux = (E + p) * v - v * sigma
            efp = _pad(E_flux)
            dE_dt = -(efp[:, 2:] - efp[:, :-2]) * inv_2dx

            # Convert dE/dt to dp/dt
            KE_change = v * rho * dv_dt + 0.5 * v * v * drho_dt
            dp_dt = (GAMMA - 1.0) * (dE_dt - KE_change)
            max_dp = 100.0 * np.abs(p)
            dp_dt = np.clip(dp_dt, -max_dp, max_dp)

            # NaN protection
            drho_dt = np.nan_to_num(drho_dt, nan=0.0)
            dv_dt = np.nan_to_num(dv_dt, nan=0.0)
            dp_dt = np.nan_to_num(dp_dt, nan=0.0)

            # Forward Euler update with positivity preservation
            v = v + dt * dv_dt
            rho = np.clip(rho + dt * drho_dt, 1e-4, 1e5)
            p = np.clip(p + dt * dp_dt, 1e-4, 1e5)

            t_now += dt

        # NaN recovery at save points
        bad = (np.isnan(v).any(axis=-1)
               | np.isnan(rho).any(axis=-1)
               | np.isnan(p).any(axis=-1))
        if bad.any():
            prev = max(save_idx - 1, 0)
            v[bad] = Vx_out[bad, prev]
            rho[bad] = rho_out[bad, prev]
            p[bad] = p_out[bad, prev]

        Vx_out[:, save_idx] = v
        rho_out[:, save_idx] = rho
        p_out[:, save_idx] = p

    return Vx_out, rho_out, p_out
