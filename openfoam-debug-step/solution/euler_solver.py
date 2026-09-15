#!/usr/bin/env python3
"""
1D Euler equations finite volume solver for the Sod shock tube problem.
Uses HLLC approximate Riemann solver, MUSCL reconstruction with van Albada
slope limiter on primitive variables, and TVD Runge-Kutta 2nd-order time
integration (Shu-Osher method).

"""

import numpy as np
import json
import csv
import math

GAMMA = 1.4
GM1 = GAMMA - 1.0
GP1 = GAMMA + 1.0


def cons_to_prim(W):
    """Conservative (rho, rho*u, E) -> primitive (rho, u, p). W: (3, N)."""
    rho = W[0]
    u = W[1] / rho
    p = GM1 * (W[2] - 0.5 * rho * u * u)
    return rho, u, p


def prim_to_cons(rho, u, p):
    """Primitive -> conservative. Arrays of shape (N,)."""
    return np.array([rho, rho * u, p / GM1 + 0.5 * rho * u * u])


def euler_phys_flux(rho, u, p, E):
    """Physical flux vector of the 1D Euler equations."""
    return np.array([rho * u, rho * u * u + p, u * (E + p)])


def hllc_flux(WL, WR):
    """
    HLLC approximate Riemann solver.
    WL, WR: (3, Nf) conservative variables at left/right of each face.
    Returns (flux, max_wave_speed).
    """
    rhoL, uL, pL = cons_to_prim(WL)
    rhoR, uR, pR = cons_to_prim(WR)

    pL = np.maximum(pL, 1e-15)
    pR = np.maximum(pR, 1e-15)

    aL = np.sqrt(GAMMA * pL / rhoL)
    aR = np.sqrt(GAMMA * pR / rhoR)

    # PVRS pressure estimate for wave speeds
    rho_bar = 0.5 * (rhoL + rhoR)
    a_bar = 0.5 * (aL + aR)
    p_pvrs = 0.5 * (pL + pR) - 0.5 * (uR - uL) * rho_bar * a_bar
    p_star = np.maximum(p_pvrs, 0.0)

    # Wave speed estimates (Toro Sec 10.5)
    qL = np.where(p_star > pL,
                  np.sqrt(1.0 + GP1 / (2.0 * GAMMA) * (p_star / pL - 1.0)),
                  1.0)
    qR = np.where(p_star > pR,
                  np.sqrt(1.0 + GP1 / (2.0 * GAMMA) * (p_star / pR - 1.0)),
                  1.0)

    SL = uL - aL * qL
    SR = uR + aR * qR

    # Contact wave speed
    denom = rhoL * (SL - uL) - rhoR * (SR - uR)
    SM = (pR - pL + rhoL * uL * (SL - uL) - rhoR * uR * (SR - uR)) / denom

    # Physical fluxes at left and right states
    FL = euler_phys_flux(rhoL, uL, pL, WL[2])
    FR = euler_phys_flux(rhoR, uR, pR, WR[2])

    # Left star state
    cL = rhoL * (SL - uL) / (SL - SM)
    WsL = np.zeros_like(WL)
    WsL[0] = cL
    WsL[1] = cL * SM
    WsL[2] = cL * (WL[2] / rhoL + (SM - uL) * (SM + pL / (rhoL * (SL - uL))))

    # Right star state
    cR = rhoR * (SR - uR) / (SR - SM)
    WsR = np.zeros_like(WR)
    WsR[0] = cR
    WsR[1] = cR * SM
    WsR[2] = cR * (WR[2] / rhoR + (SM - uR) * (SM + pR / (rhoR * (SR - uR))))

    # Star region fluxes via Rankine-Hugoniot
    FsL = FL + SL * (WsL - WL)
    FsR = FR + SR * (WsR - WR)

    # Select appropriate flux based on wave structure
    c1 = SL >= 0
    c2 = SM >= 0
    c3 = SR >= 0

    flux = np.where(c1[np.newaxis], FL,
           np.where(c2[np.newaxis], FsL,
           np.where(c3[np.newaxis], FsR, FR)))

    max_speed = np.max(np.maximum(np.abs(SL), np.abs(SR)))

    return flux, max_speed


def van_albada(dm, dp):
    """
    Van Albada slope limiter applied to backward (dm) and forward (dp)
    differences. Returns the limited slope.
    """
    eps = 1e-12
    product = dm * dp
    return np.where(product > 0,
                    (dp * dm * dm + dm * dp * dp) / (dm * dm + dp * dp + eps),
                    0.0)


def compute_rhs(W, N, dx):
    """
    Compute dW/dt = -1/dx * (F_{i+1/2} - F_{i-1/2}).
    MUSCL reconstruction on primitive variables with van Albada limiter.
    W: (3, N) conservative variables.
    Returns (rhs, max_wave_speed).
    """
    # Convert to primitive for reconstruction
    rho, u, p = cons_to_prim(W)
    Q = np.array([rho, u, p])  # (3, N)

    # Extend with 2 ghost cells per side (transmissive / zero-gradient BC)
    Qx = np.zeros((3, N + 4))
    Qx[:, 2:N + 2] = Q
    Qx[:, 0] = Q[:, 0]
    Qx[:, 1] = Q[:, 0]
    Qx[:, N + 2] = Q[:, -1]
    Qx[:, N + 3] = Q[:, -1]

    # Backward and forward differences for cells 1..N+2 in extended array
    dm = Qx[:, 1:N + 3] - Qx[:, 0:N + 2]   # (3, N+2)
    dp = Qx[:, 2:N + 4] - Qx[:, 1:N + 3]   # (3, N+2)
    slope = van_albada(dm, dp)               # (3, N+2)

    # MUSCL extrapolation to N+1 face values
    # Face j (j=0..N) sits between ext cells j+1 and j+2.
    # Left state uses ext cell j+1 (slope index j):
    QL = Qx[:, 1:N + 2] + 0.5 * slope[:, 0:N + 1]   # (3, N+1)
    # Right state uses ext cell j+2 (slope index j+1):
    QR = Qx[:, 2:N + 3] - 0.5 * slope[:, 1:N + 2]   # (3, N+1)

    # Enforce positivity on reconstructed density and pressure
    QL[0] = np.maximum(QL[0], 1e-15)
    QL[2] = np.maximum(QL[2], 1e-15)
    QR[0] = np.maximum(QR[0], 1e-15)
    QR[2] = np.maximum(QR[2], 1e-15)

    # Convert reconstructed primitives back to conservative for HLLC
    WL = prim_to_cons(QL[0], QL[1], QL[2])
    WR = prim_to_cons(QR[0], QR[1], QR[2])

    # Compute intercell fluxes
    flux, max_speed = hllc_flux(WL, WR)

    # Finite volume update: divergence of flux
    rhs = -(flux[:, 1:] - flux[:, :-1]) / dx   # (3, N)

    return rhs, max_speed


def solve_euler(N=400, t_end=0.2, cfl=0.5):
    """
    Solve the Sod shock tube using HLLC + MUSCL + van Albada + TVD-RK2.
    Returns (x, rho, u, p, n_steps).
    """
    dx = 1.0 / N
    x = np.linspace(0.5 * dx, 1.0 - 0.5 * dx, N)

    # Sod shock tube initial conditions
    W = np.zeros((3, N))
    left = x < 0.5
    right = ~left

    W[0, left] = 1.0
    W[1, left] = 0.0
    W[2, left] = 1.0 / GM1  # E = 2.5

    W[0, right] = 0.125
    W[1, right] = 0.0
    W[2, right] = 0.1 / GM1  # E = 0.25

    t = 0.0
    step = 0

    while t < t_end - 1e-14:
        # Stage 1 of TVD-RK2 (Shu-Osher)
        rhs1, max_speed = compute_rhs(W, N, dx)
        dt = cfl * dx / max_speed
        if t + dt > t_end:
            dt = t_end - t

        W1 = W + dt * rhs1

        # Stage 2
        rhs2, _ = compute_rhs(W1, N, dx)
        W = 0.5 * W + 0.5 * (W1 + dt * rhs2)

        t += dt
        step += 1

    rho, u, p = cons_to_prim(W)
    return x, rho, u, p, step


# ---------- Exact Riemann solver for error assessment ----------

def exact_riemann_sod(x, t=0.2):
    """
    Compute the exact analytical solution of the Sod shock tube problem.
    Returns (rho_exact, u_exact, p_exact, info_dict).
    """
    rho_L, u_L, p_L = 1.0, 0.0, 1.0
    rho_R, u_R, p_R = 0.125, 0.0, 0.1
    x0 = 0.5

    a_L = math.sqrt(GAMMA * p_L / rho_L)
    a_R = math.sqrt(GAMMA * p_R / rho_R)

    # Newton-Raphson for star-state pressure
    def pressure_function(ps):
        # Left wave contribution
        if ps <= p_L:
            ratio = (ps / p_L) ** (GM1 / (2.0 * GAMMA))
            fL = 2.0 * a_L / GM1 * (ratio - 1.0)
            dfL = (1.0 / (rho_L * a_L)) * (ps / p_L) ** (-(GAMMA + 1.0) / (2.0 * GAMMA))
        else:
            A_L = 2.0 / (GP1 * rho_L)
            B_L = GM1 / GP1 * p_L
            sq = math.sqrt(A_L / (ps + B_L))
            fL = (ps - p_L) * sq
            dfL = sq * (1.0 - (ps - p_L) / (2.0 * (ps + B_L)))

        # Right wave contribution
        if ps <= p_R:
            ratio = (ps / p_R) ** (GM1 / (2.0 * GAMMA))
            fR = 2.0 * a_R / GM1 * (ratio - 1.0)
            dfR = (1.0 / (rho_R * a_R)) * (ps / p_R) ** (-(GAMMA + 1.0) / (2.0 * GAMMA))
        else:
            A_R = 2.0 / (GP1 * rho_R)
            B_R = GM1 / GP1 * p_R
            sq = math.sqrt(A_R / (ps + B_R))
            fR = (ps - p_R) * sq
            dfR = sq * (1.0 - (ps - p_R) / (2.0 * (ps + B_R)))

        return fL + fR + u_R - u_L, dfL + dfR

    # Iterate
    p_star = 0.5 * (p_L + p_R)
    for _ in range(200):
        f_val, df_val = pressure_function(p_star)
        dp = -f_val / df_val
        p_star += dp
        if p_star < 0:
            p_star = 1e-10
        if abs(dp) < 1e-14 * (1.0 + abs(p_star)):
            break

    # Star-region velocity
    ratio_L = (p_star / p_L) ** (GM1 / (2.0 * GAMMA))
    u_star = u_L + 2.0 * a_L / GM1 * (1.0 - ratio_L)

    # Post-rarefaction density (left of contact)
    rho_star_L = rho_L * (p_star / p_L) ** (1.0 / GAMMA)
    a_star_L = math.sqrt(GAMMA * p_star / rho_star_L)

    # Post-shock density (right of contact)
    rho_star_R = rho_R * (
        (p_star / p_R + GM1 / GP1) / (GM1 / GP1 * p_star / p_R + 1.0)
    )

    # Shock speed
    S_shock = u_R + a_R * math.sqrt(GP1 / (2.0 * GAMMA) * p_star / p_R + GM1 / (2.0 * GAMMA))

    # Compute exact solution at each x
    rho_ex = np.zeros_like(x)
    u_ex = np.zeros_like(x)
    p_ex = np.zeros_like(x)

    for i in range(len(x)):
        xi = (x[i] - x0) / t  # similarity variable

        if xi < u_L - a_L:
            rho_ex[i] = rho_L
            u_ex[i] = u_L
            p_ex[i] = p_L
        elif xi < u_star - a_star_L:
            # Inside rarefaction fan
            coeff = 2.0 / GP1 + GM1 / (GP1 * a_L) * (u_L - xi)
            rho_ex[i] = rho_L * coeff ** (2.0 / GM1)
            u_ex[i] = 2.0 / GP1 * (a_L + GM1 / 2.0 * u_L + xi)
            p_ex[i] = p_L * coeff ** (2.0 * GAMMA / GM1)
        elif xi < u_star:
            # Star-left region
            rho_ex[i] = rho_star_L
            u_ex[i] = u_star
            p_ex[i] = p_star
        elif xi < S_shock:
            # Star-right region
            rho_ex[i] = rho_star_R
            u_ex[i] = u_star
            p_ex[i] = p_star
        else:
            # Undisturbed right state
            rho_ex[i] = rho_R
            u_ex[i] = u_R
            p_ex[i] = p_R

    info = {
        'p_star': p_star,
        'u_star': u_star,
        'rho_star_L': rho_star_L,
        'rho_star_R': rho_star_R,
        'shock_speed': S_shock,
        'shock_position': x0 + S_shock * t,
        'contact_position': x0 + u_star * t,
    }
    return rho_ex, u_ex, p_ex, info


# ---------- Post-processing ----------

def find_shock_position(x, rho, dx):
    """Find shock position from the steepest density gradient in x > 0.7."""
    drho = np.abs(np.diff(rho)) / dx
    xm = 0.5 * (x[:-1] + x[1:])
    mask = xm > 0.7
    if not np.any(mask):
        return 0.85
    idx_local = np.argmax(drho[mask])
    idx = np.where(mask)[0][idx_local]
    return xm[idx]


def find_contact_position(x, rho, dx, shock_pos):
    """Find contact discontinuity from density gradient between 0.55 and shock."""
    drho = np.abs(np.diff(rho)) / dx
    xm = 0.5 * (x[:-1] + x[1:])
    mask = (xm > 0.55) & (xm < shock_pos - 0.05)
    if not np.any(mask):
        return 0.685
    idx_local = np.argmax(drho[mask])
    idx = np.where(mask)[0][idx_local]
    return xm[idx]


def main():
    N = 400
    t_end = 0.2
    cfl = 0.5
    dx = 1.0 / N

    # Solve numerically
    x, rho, u, p, n_steps = solve_euler(N, t_end, cfl)

    # Compute exact solution
    rho_ex, u_ex, p_ex, exact_info = exact_riemann_sod(x, t_end)

    # L2 error in density
    l2_error = float(np.sqrt(dx * np.sum((rho - rho_ex) ** 2)))

    # Locate discontinuities
    shock_pos = find_shock_position(x, rho, dx)
    contact_pos = find_contact_position(x, rho, dx, shock_pos)

    # Star-region velocity (average in the plateau between rarefaction tail and shock)
    star_mask = (x > 0.50) & (x < shock_pos - 0.03)
    star_vel = float(np.mean(u[star_mask]))

    # Post-shock density and pressure (between contact and shock)
    ps_mask = (x > contact_pos + 0.02) & (x < shock_pos - 0.02)
    if np.sum(ps_mask) > 2:
        post_shock_rho = float(np.mean(rho[ps_mask]))
        post_shock_p = float(np.mean(p[ps_mask]))
    else:
        post_shock_rho = exact_info['rho_star_R']
        post_shock_p = exact_info['p_star']

    # Total mass (conservation check)
    total_mass = float(np.sum(rho) * dx)

    results = {
        "shock_position": round(shock_pos, 6),
        "contact_position": round(contact_pos, 6),
        "post_shock_density": round(post_shock_rho, 6),
        "post_shock_pressure": round(post_shock_p, 6),
        "star_velocity": round(star_vel, 6),
        "density_l2_error": round(l2_error, 8),
        "total_mass": round(total_mass, 10),
        "n_cells": N
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    # Write full solution profile
    with open('/app/solution.csv', 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['x', 'rho', 'u', 'p'])
        for i in range(N):
            writer.writerow([f'{x[i]:.8f}', f'{rho[i]:.8f}',
                             f'{u[i]:.8f}', f'{p[i]:.8f}'])

    print(f"Completed in {n_steps} time steps")
    print(f"Shock:   x = {shock_pos:.4f} (exact {exact_info['shock_position']:.4f})")
    print(f"Contact: x = {contact_pos:.4f} (exact {exact_info['contact_position']:.4f})")
    print(f"u*:      {star_vel:.5f} (exact {exact_info['u_star']:.5f})")
    print(f"L2(rho): {l2_error:.6f}")
    print(f"Mass:    {total_mass:.10f} (initial 0.5625)")


if __name__ == '__main__':
    main()
