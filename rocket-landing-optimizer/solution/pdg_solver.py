
"""
Powered descent guidance solver using direct optimization with
RK4-consistent forward simulation.

Approach:
  1. Initialize controls via cubic polynomial trajectory that satisfies
     position/velocity boundary conditions (constant-mass approximation).
  2. Use scipy L-BFGS-B with penalty terms to optimize controls:
     minimize fuel + penalty(terminal) + penalty(constraints).
  3. Refine terminal conditions precisely with scipy least_squares.
  4. Return RK4-simulated trajectory (matches test simulation exactly).
"""

import math
import numpy as np
import sys

sys.path.insert(0, '/app')

from problem import (
    g0, m_wet, m_dry, T_min, T_max, Isp, alpha_m,
    r0, v0, z0, x0, rf, vf,
    gamma_gs, tan_gs, tf, N, dt, max_fuel,
    continuous_dynamics,
)

# Pre-compute constants as Python floats for fast scalar arithmetic
_G0 = float(g0)
_AM = float(alpha_m)
_DT = float(dt)
_TF = float(tf)
_TMIN = float(T_min)
_TMAX = float(T_max)
_TAN_GS = float(tan_gs)
_N = int(N)
_SUBS = 10
_DT_SUB = _DT / _SUBS
_H2 = 0.5 * _DT_SUB
_H6 = _DT_SUB / 6.0

_X0 = tuple(float(x0[i]) for i in range(5))


def _simulate(controls):
    """Fast RK4 forward simulation using scalar arithmetic.

    Produces results numerically equivalent to the test's
    simulate_rk4(x0, controls, tf, N, substeps=10).  Uses pure-Python
    scalars in the inner loop to avoid numpy array-creation overhead.
    """
    traj = np.empty((_N + 1, 5))
    rx, ry, vx, vy, z = _X0
    traj[0] = x0  # first row is exactly x0

    for k in range(_N):
        tx = float(controls[k, 0])
        ty = float(controls[k, 1])
        sig = math.sqrt(tx * tx + ty * ty)
        asig = _AM * sig

        for _ in range(_SUBS):
            # --- k1 ---
            mi = math.exp(-z)
            k1_2 = tx * mi
            k1_3 = ty * mi - _G0
            k1_4 = -asig * mi

            # --- k2 (midpoint using k1) ---
            s2 = vx + _H2 * k1_2
            s3 = vy + _H2 * k1_3
            s4 = z + _H2 * k1_4
            mi = math.exp(-s4)
            k2_2 = tx * mi
            k2_3 = ty * mi - _G0
            k2_4 = -asig * mi

            # --- k3 (midpoint using k2) ---
            s2b = vx + _H2 * k2_2
            s3b = vy + _H2 * k2_3
            s4b = z + _H2 * k2_4
            mi = math.exp(-s4b)
            k3_2 = tx * mi
            k3_3 = ty * mi - _G0
            k3_4 = -asig * mi

            # --- k4 (endpoint using k3) ---
            s2c = vx + _DT_SUB * k3_2
            s3c = vy + _DT_SUB * k3_3
            s4c = z + _DT_SUB * k3_4
            mi = math.exp(-s4c)
            k4_2 = tx * mi
            k4_3 = ty * mi - _G0
            k4_4 = -asig * mi

            # --- RK4 update ---
            # Position: drx/dt=vx, dry/dt=vy
            # k_pos = [vx, s2, s2b, s2c] and [vy, s3, s3b, s3c]
            rx += _H6 * (vx + 2.0 * s2 + 2.0 * s2b + s2c)
            ry += _H6 * (vy + 2.0 * s3 + 2.0 * s3b + s3c)
            vx += _H6 * (k1_2 + 2.0 * k2_2 + 2.0 * k3_2 + k4_2)
            vy += _H6 * (k1_3 + 2.0 * k2_3 + 2.0 * k3_3 + k4_3)
            z += _H6 * (k1_4 + 2.0 * k2_4 + 2.0 * k3_4 + k4_4)

        traj[k + 1] = [rx, ry, vx, vy, z]

    return traj


def solve():
    """Solve the powered descent guidance problem.

    Returns
    -------
    dict with keys 'state', 'control', 'sigma', 'tf'.
    """
    from scipy.optimize import minimize, least_squares

    # ------------------------------------------------------------------
    # Cubic polynomial initialization
    # r(t) satisfying r(0)=r0, v(0)=v0, r(tf)=0, v(tf)=0
    # ------------------------------------------------------------------
    coeffs = np.zeros((2, 4))
    for d in range(2):
        p0, vel0 = float(r0[d]), float(v0[d])
        coeffs[d] = [
            p0,
            vel0,
            -3.0 * p0 / _TF ** 2 - 2.0 * vel0 / _TF,
            2.0 * p0 / _TF ** 3 + vel0 / _TF ** 2,
        ]

    u_init = np.zeros((_N, 2))
    for k in range(_N):
        t = k * _DT
        for d in range(2):
            acc = 2.0 * coeffs[d, 2] + 6.0 * coeffs[d, 3] * t
            u_init[k, d] = m_wet * acc
        u_init[k, 1] += m_wet * _G0  # gravity compensation

        mag = math.sqrt(float(u_init[k, 0]) ** 2 + float(u_init[k, 1]) ** 2)
        if mag > _TMAX:
            u_init[k] *= _TMAX / mag
        elif 1e-10 < mag < _TMIN:
            u_init[k] *= _TMIN / mag
        elif mag <= 1e-10:
            u_init[k, 0] = 0.0
            u_init[k, 1] = _TMIN

    u_flat = u_init.flatten()
    bnd = [(-_TMAX, _TMAX)] * (_N * 2)

    # ------------------------------------------------------------------
    # Phase 1: L-BFGS-B with progressive terminal penalty
    # ------------------------------------------------------------------
    for w in [500, 5000]:
        def obj(uf, _w=w):
            c = uf.reshape((_N, 2))
            tr = _simulate(c)
            fuel = -tr[-1, 4]  # minimize = maximize final mass
            term = np.sum(tr[-1, :4] ** 2)
            mags = np.linalg.norm(c, axis=1)
            tv_lo = np.sum(np.maximum(_TMIN - mags, 0) ** 2)
            tv_hi = np.sum(np.maximum(mags - _TMAX, 0) ** 2)
            gs = np.sum(
                np.maximum(_TAN_GS * np.abs(tr[:_N, 0]) - tr[:_N, 1], 0) ** 2
            )
            return fuel + _w * term + 100.0 * (tv_lo + tv_hi) + 100.0 * gs

        res = minimize(
            obj, u_flat, method='L-BFGS-B', bounds=bnd,
            options={'maxiter': 300, 'ftol': 1e-15},
        )
        u_flat = res.x

    # ------------------------------------------------------------------
    # Phase 2: Least-squares terminal refinement
    # ------------------------------------------------------------------
    u_ref = u_flat.copy()

    def residual(uf):
        c = uf.reshape((_N, 2))
        tr = _simulate(c)
        terminal = tr[-1, :4] * 100.0
        reg = (uf - u_ref) * 0.5
        mags = np.linalg.norm(c, axis=1)
        tv = np.maximum(_TMIN - mags, 0) * 10.0
        gs = np.maximum(_TAN_GS * np.abs(tr[:_N, 0]) - tr[:_N, 1], 0) * 10.0
        return np.concatenate([terminal, reg, tv, gs])

    res2 = least_squares(
        residual, u_flat, method='trf',
        bounds=(-_TMAX, _TMAX),
        ftol=1e-12, xtol=1e-12, max_nfev=15000,
    )

    controls = res2.x.reshape((_N, 2))
    traj = _simulate(controls)

    # ------------------------------------------------------------------
    # Fallback: retry with stronger terminal weight if needed
    # ------------------------------------------------------------------
    pos_err = math.sqrt(float(traj[-1, 0]) ** 2 + float(traj[-1, 1]) ** 2)
    vel_err = math.sqrt(float(traj[-1, 2]) ** 2 + float(traj[-1, 3]) ** 2)
    if pos_err > 0.1 or vel_err > 0.1:
        u_ref2 = res2.x.copy()

        def residual2(uf):
            c = uf.reshape((_N, 2))
            tr = _simulate(c)
            terminal = tr[-1, :4] * 500.0
            reg = (uf - u_ref2) * 0.1
            return np.concatenate([terminal, reg])

        res3 = least_squares(
            residual2, res2.x, method='trf',
            bounds=(-_TMAX, _TMAX),
            ftol=1e-14, xtol=1e-14, max_nfev=20000,
        )
        controls = res3.x.reshape((_N, 2))
        traj = _simulate(controls)

    sigma = np.linalg.norm(controls, axis=1)

    return {
        'state': traj,
        'control': controls,
        'sigma': sigma,
        'tf': tf,
    }


if __name__ == '__main__':
    result = solve()
    final_mass = np.exp(result['state'][-1, 4])
    fuel_used = m_wet - final_mass
    print(f"Final mass:      {final_mass:.4f}")
    print(f"Fuel used:       {fuel_used:.4f} (max: {max_fuel})")
    print(f"Terminal pos:    {result['state'][-1, :2]}")
    print(f"Terminal vel:    {result['state'][-1, 2:4]}")
    sig = result['sigma']
    print(f"Thrust range:    [{sig.min():.4f}, {sig.max():.4f}]")
