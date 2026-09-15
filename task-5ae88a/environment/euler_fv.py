"""
2D Finite Volume Euler Solver
Solves the compressible Euler equations on a uniform periodic grid
using a second-order Godunov method with Rusanov (Lax-Friedrichs) flux.

This solver handles pure hydrodynamics (no magnetic fields).
"""

import numpy as np
import json
import sys


def getConserved(rho, vx, vy, P, gamma, vol):
    """
    Calculate conserved variables from primitive variables.
        rho    : cell density
        vx, vy : cell velocity components
        P      : cell pressure
        gamma  : adiabatic index
        vol    : cell volume
    Returns: Mass, Momx, Momy, Energy (all per cell)
    """
    Mass = rho * vol
    Momx = rho * vx * vol
    Momy = rho * vy * vol
    Energy = (P / (gamma - 1) + 0.5 * rho * (vx**2 + vy**2)) * vol
    return Mass, Momx, Momy, Energy


def getPrimitive(Mass, Momx, Momy, Energy, gamma, vol):
    """
    Calculate primitive variables from conserved variables.
    Returns: rho, vx, vy, P
    """
    rho = Mass / vol
    vx = Momx / rho / vol
    vy = Momy / rho / vol
    P = (Energy / vol - 0.5 * rho * (vx**2 + vy**2)) * (gamma - 1)
    return rho, vx, vy, P


def getGradient(f, dx):
    """
    Calculate centered gradients of a field using periodic BCs.
    Returns: f_dx, f_dy
    """
    R = -1  # right/up
    L = 1   # left/down
    f_dx = (np.roll(f, R, axis=0) - np.roll(f, L, axis=0)) / (2 * dx)
    f_dy = (np.roll(f, R, axis=1) - np.roll(f, L, axis=1)) / (2 * dx)
    return f_dx, f_dy


def slopeLimit(f, dx, f_dx, f_dy):
    """
    Apply minmod-type slope limiter to gradients for stability.
    """
    R = -1
    L = 1
    f_dx = (
        np.maximum(0.0, np.minimum(1.0, ((f - np.roll(f, L, axis=0)) / dx) / (f_dx + 1.0e-8 * (f_dx == 0))))
        * f_dx
    )
    f_dx = (
        np.maximum(0.0, np.minimum(1.0, (-(f - np.roll(f, R, axis=0)) / dx) / (f_dx + 1.0e-8 * (f_dx == 0))))
        * f_dx
    )
    f_dy = (
        np.maximum(0.0, np.minimum(1.0, ((f - np.roll(f, L, axis=1)) / dx) / (f_dy + 1.0e-8 * (f_dy == 0))))
        * f_dy
    )
    f_dy = (
        np.maximum(0.0, np.minimum(1.0, (-(f - np.roll(f, R, axis=1)) / dx) / (f_dy + 1.0e-8 * (f_dy == 0))))
        * f_dy
    )
    return f_dx, f_dy


def extrapolateInSpaceToFace(f, f_dx, f_dy, dx):
    """
    Extrapolate field values from cell centers to face centers.
    Returns: f_XL, f_XR, f_YL, f_YR (left/right states at x/y faces)
    """
    R = -1
    L = 1
    f_XL = f - f_dx * dx / 2
    f_XL = np.roll(f_XL, R, axis=0)
    f_XR = f + f_dx * dx / 2
    f_YL = f - f_dy * dx / 2
    f_YL = np.roll(f_YL, R, axis=1)
    f_YR = f + f_dy * dx / 2
    return f_XL, f_XR, f_YL, f_YR


def applyFluxes(F, flux_F_X, flux_F_Y, dx, dt):
    """
    Apply conservative flux updates to a field.
    """
    R = -1
    L = 1
    F += -dt * dx * flux_F_X
    F += dt * dx * np.roll(flux_F_X, L, axis=0)
    F += -dt * dx * flux_F_Y
    F += dt * dx * np.roll(flux_F_Y, L, axis=1)
    return F


def getFlux(rho_L, rho_R, vx_L, vx_R, vy_L, vy_R, P_L, P_R, gamma):
    """
    Calculate inter-cell fluxes using the Rusanov (local Lax-Friedrichs) scheme.
    Returns: flux_Mass, flux_Momx, flux_Momy, flux_Energy
    """
    # left and right energies
    en_L = P_L / (gamma - 1) + 0.5 * rho_L * (vx_L**2 + vy_L**2)
    en_R = P_R / (gamma - 1) + 0.5 * rho_R * (vx_R**2 + vy_R**2)

    # averaged states
    rho_star = 0.5 * (rho_L + rho_R)
    momx_star = 0.5 * (rho_L * vx_L + rho_R * vx_R)
    momy_star = 0.5 * (rho_L * vy_L + rho_R * vy_R)
    en_star = 0.5 * (en_L + en_R)
    P_star = (gamma - 1) * (en_star - 0.5 * (momx_star**2 + momy_star**2) / rho_star)

    # central fluxes
    flux_Mass = momx_star
    flux_Momx = momx_star**2 / rho_star + P_star
    flux_Momy = momx_star * momy_star / rho_star
    flux_Energy = (en_star + P_star) * momx_star / rho_star

    # max wavespeed for Rusanov dissipation
    C_L = np.sqrt(gamma * P_L / rho_L) + np.abs(vx_L)
    C_R = np.sqrt(gamma * P_R / rho_R) + np.abs(vx_R)
    C = np.maximum(C_L, C_R)

    # dissipative stabilization
    flux_Mass -= C * 0.5 * (rho_L - rho_R)
    flux_Momx -= C * 0.5 * (rho_L * vx_L - rho_R * vx_R)
    flux_Momy -= C * 0.5 * (rho_L * vy_L - rho_R * vy_R)
    flux_Energy -= C * 0.5 * (en_L - en_R)

    return flux_Mass, flux_Momx, flux_Momy, flux_Energy


def run_simulation(config):
    """Run the Euler finite volume simulation with the given configuration."""
    N = config["N"]
    boxsize = config["boxsize"]
    gamma = config["gamma"]
    courant_fac = config["courant_fac"]
    tEnd = config["tEnd"]
    useSlopeLimiting = config["useSlopeLimiting"]

    dx = boxsize / N
    vol = dx**2
    xlin = np.linspace(0.5 * dx, boxsize - 0.5 * dx, N)
    Y, X = np.meshgrid(xlin, xlin)

    # Kelvin-Helmholtz instability initial conditions
    w0 = 0.1
    sigma = 0.05 / np.sqrt(2.0)
    rho = 1.0 + (np.abs(Y - 0.5) < 0.25)
    vx = -0.5 + (np.abs(Y - 0.5) < 0.25)
    vy = w0 * np.sin(4 * np.pi * X) * (
        np.exp(-((Y - 0.25) ** 2) / (2 * sigma**2))
        + np.exp(-((Y - 0.75) ** 2) / (2 * sigma**2))
    )
    P = 2.5 * np.ones(X.shape)

    Mass, Momx, Momy, Energy = getConserved(rho, vx, vy, P, gamma, vol)
    total_mass_init = np.sum(Mass)
    total_energy_init = np.sum(Energy)

    t = 0
    step = 0

    while t < tEnd:
        rho, vx, vy, P = getPrimitive(Mass, Momx, Momy, Energy, gamma, vol)

        dt = courant_fac * np.min(dx / (np.sqrt(gamma * P / rho) + np.sqrt(vx**2 + vy**2)))
        if t + dt > tEnd:
            dt = tEnd - t

        rho_dx, rho_dy = getGradient(rho, dx)
        vx_dx, vx_dy = getGradient(vx, dx)
        vy_dx, vy_dy = getGradient(vy, dx)
        P_dx, P_dy = getGradient(P, dx)

        if useSlopeLimiting:
            rho_dx, rho_dy = slopeLimit(rho, dx, rho_dx, rho_dy)
            vx_dx, vx_dy = slopeLimit(vx, dx, vx_dx, vx_dy)
            vy_dx, vy_dy = slopeLimit(vy, dx, vy_dx, vy_dy)
            P_dx, P_dy = slopeLimit(P, dx, P_dx, P_dy)

        rho_prime = rho - 0.5 * dt * (vx * rho_dx + rho * vx_dx + vy * rho_dy + rho * vy_dy)
        vx_prime = vx - 0.5 * dt * (vx * vx_dx + vy * vx_dy + (1 / rho) * P_dx)
        vy_prime = vy - 0.5 * dt * (vx * vy_dx + vy * vy_dy + (1 / rho) * P_dy)
        P_prime = P - 0.5 * dt * (gamma * P * (vx_dx + vy_dy) + vx * P_dx + vy * P_dy)

        rho_XL, rho_XR, rho_YL, rho_YR = extrapolateInSpaceToFace(rho_prime, rho_dx, rho_dy, dx)
        vx_XL, vx_XR, vx_YL, vx_YR = extrapolateInSpaceToFace(vx_prime, vx_dx, vx_dy, dx)
        vy_XL, vy_XR, vy_YL, vy_YR = extrapolateInSpaceToFace(vy_prime, vy_dx, vy_dy, dx)
        P_XL, P_XR, P_YL, P_YR = extrapolateInSpaceToFace(P_prime, P_dx, P_dy, dx)

        flux_Mass_X, flux_Momx_X, flux_Momy_X, flux_Energy_X = getFlux(
            rho_XL, rho_XR, vx_XL, vx_XR, vy_XL, vy_XR, P_XL, P_XR, gamma
        )
        flux_Mass_Y, flux_Momy_Y, flux_Momx_Y, flux_Energy_Y = getFlux(
            rho_YL, rho_YR, vy_YL, vy_YR, vx_YL, vx_YR, P_YL, P_YR, gamma
        )

        Mass = applyFluxes(Mass, flux_Mass_X, flux_Mass_Y, dx, dt)
        Momx = applyFluxes(Momx, flux_Momx_X, flux_Momx_Y, dx, dt)
        Momy = applyFluxes(Momy, flux_Momy_X, flux_Momy_Y, dx, dt)
        Energy = applyFluxes(Energy, flux_Energy_X, flux_Energy_Y, dx, dt)

        t += dt
        step += 1

    rho, vx, vy, P = getPrimitive(Mass, Momx, Momy, Energy, gamma, vol)

    results = {
        "total_mass": float(np.sum(Mass)),
        "total_energy": float(np.sum(Energy)),
        "total_momx": float(np.sum(Momx)),
        "total_momy": float(np.sum(Momy)),
        "max_density": float(np.max(rho)),
        "min_density": float(np.min(rho)),
        "mean_density": float(np.mean(rho)),
        "num_steps": step,
    }
    return results


if __name__ == "__main__":
    with open("/app/config.json") as f:
        config = json.load(f)
    results = run_simulation(config)
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("Simulation complete. Results written to /app/results.json")
