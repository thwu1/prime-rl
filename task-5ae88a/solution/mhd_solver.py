"""
2D Ideal MHD Finite Volume Solver with Constrained Transport
Solves the ideal MHD equations on a uniform periodic grid using a
second-order Godunov method with Rusanov flux and constrained transport
for divergence-free magnetic field evolution.

"""

import numpy as np
import h5py
import json


def getCurl(Az, dx):
    """
    Compute the discrete curl of a node-centered vector potential Az
    to obtain face-centered magnetic field components.
    """
    R = -1
    L = 1
    bx = (Az - np.roll(Az, L, axis=1)) / dx
    by = -(Az - np.roll(Az, L, axis=0)) / dx
    return bx, by


def getDiv(bx, by, dx):
    """
    Compute the discrete divergence of the face-centered magnetic field.
    """
    R = -1
    L = 1
    divB = (bx - np.roll(bx, L, axis=0) + by - np.roll(by, L, axis=1)) / dx
    return divB


def getBavg(bx, by):
    """
    Compute cell-centered magnetic field by averaging adjacent face values.
    """
    R = -1
    L = 1
    Bx = 0.5 * (bx + np.roll(bx, L, axis=0))
    By = 0.5 * (by + np.roll(by, L, axis=1))
    return Bx, By


def getConserved(rho, vx, vy, P, Bx, By, gamma, vol):
    """
    Convert primitive variables to conserved variables.
    P is the TOTAL pressure = P_gas + (Bx^2 + By^2)/2.
    """
    Mass = rho * vol
    Momx = rho * vx * vol
    Momy = rho * vy * vol
    Energy = (
        (P - 0.5 * (Bx**2 + By**2)) / (gamma - 1)
        + 0.5 * rho * (vx**2 + vy**2)
        + 0.5 * (Bx**2 + By**2)
    ) * vol
    return Mass, Momx, Momy, Energy


def getPrimitive(Mass, Momx, Momy, Energy, Bx, By, gamma, vol):
    """
    Convert conserved variables to primitive variables.
    Returns total pressure P = P_gas + (Bx^2 + By^2)/2.
    """
    rho = Mass / vol
    vx = Momx / rho / vol
    vy = Momy / rho / vol
    P = (Energy / vol - 0.5 * rho * (vx**2 + vy**2) - 0.5 * (Bx**2 + By**2)) * (
        gamma - 1
    ) + 0.5 * (Bx**2 + By**2)
    return rho, vx, vy, P


def getGradient(f, dx):
    """Compute centered gradients with periodic BCs."""
    R = -1
    L = 1
    f_dx = (np.roll(f, R, axis=0) - np.roll(f, L, axis=0)) / (2 * dx)
    f_dy = (np.roll(f, R, axis=1) - np.roll(f, L, axis=1)) / (2 * dx)
    return f_dx, f_dy


def slopeLimit(f, dx, f_dx, f_dy):
    """Apply minmod-type slope limiter."""
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
    """Extrapolate field from cell centers to face centers."""
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
    """Apply conservative flux update."""
    R = -1
    L = 1
    F += -dt * dx * flux_F_X
    F += dt * dx * np.roll(flux_F_X, L, axis=0)
    F += -dt * dx * flux_F_Y
    F += dt * dx * np.roll(flux_F_Y, L, axis=1)
    return F


def constrainedTransport(bx, by, flux_By_X, flux_Bx_Y, dx, dt):
    """
    Update face-centered magnetic field using constrained transport.
    """
    R = -1
    L = 1
    Ez = 0.25 * (
        -flux_By_X
        - np.roll(flux_By_X, R, axis=1)
        + flux_Bx_Y
        + np.roll(flux_Bx_Y, R, axis=0)
    )
    dbx, dby = getCurl(-Ez, dx)
    bx += dt * dbx
    by += dt * dby
    return bx, by


def getFlux(rho_L, rho_R, vx_L, vx_R, vy_L, vy_R, P_L, P_R,
            Bx_L, Bx_R, By_L, By_R, gamma):
    """
    Compute inter-cell fluxes using the Rusanov scheme for ideal MHD.
    """
    en_L = (
        (P_L - 0.5 * (Bx_L**2 + By_L**2)) / (gamma - 1)
        + 0.5 * rho_L * (vx_L**2 + vy_L**2)
        + 0.5 * (Bx_L**2 + By_L**2)
    )
    en_R = (
        (P_R - 0.5 * (Bx_R**2 + By_R**2)) / (gamma - 1)
        + 0.5 * rho_R * (vx_R**2 + vy_R**2)
        + 0.5 * (Bx_R**2 + By_R**2)
    )

    rho_star = 0.5 * (rho_L + rho_R)
    momx_star = 0.5 * (rho_L * vx_L + rho_R * vx_R)
    momy_star = 0.5 * (rho_L * vy_L + rho_R * vy_R)
    en_star = 0.5 * (en_L + en_R)
    Bx_star = 0.5 * (Bx_L + Bx_R)
    By_star = 0.5 * (By_L + By_R)

    P_star = (gamma - 1) * (
        en_star
        - 0.5 * (momx_star**2 + momy_star**2) / rho_star
        - 0.5 * (Bx_star**2 + By_star**2)
    ) + 0.5 * (Bx_star**2 + By_star**2)

    flux_Mass = momx_star
    flux_Momx = momx_star**2 / rho_star + P_star - Bx_star * Bx_star
    flux_Momy = momx_star * momy_star / rho_star - Bx_star * By_star
    flux_Energy = (en_star + P_star) * momx_star / rho_star - Bx_star * (
        Bx_star * momx_star + By_star * momy_star
    ) / rho_star
    flux_By = (By_star * momx_star - Bx_star * momy_star) / rho_star

    c0_L = np.sqrt(gamma * (P_L - 0.5 * (Bx_L**2 + By_L**2)) / rho_L)
    c0_R = np.sqrt(gamma * (P_R - 0.5 * (Bx_R**2 + By_R**2)) / rho_R)
    ca_L = np.sqrt((Bx_L**2 + By_L**2) / rho_L)
    ca_R = np.sqrt((Bx_R**2 + By_R**2) / rho_R)
    cf_L = np.sqrt(0.5 * (c0_L**2 + ca_L**2) + 0.5 * np.sqrt((c0_L**2 + ca_L**2) ** 2))
    cf_R = np.sqrt(0.5 * (c0_R**2 + ca_R**2) + 0.5 * np.sqrt((c0_R**2 + ca_R**2) ** 2))
    C_L = cf_L + np.abs(vx_L)
    C_R = cf_R + np.abs(vx_R)
    C = np.maximum(C_L, C_R)

    flux_Mass -= C * 0.5 * (rho_L - rho_R)
    flux_Momx -= C * 0.5 * (rho_L * vx_L - rho_R * vx_R)
    flux_Momy -= C * 0.5 * (rho_L * vy_L - rho_R * vy_R)
    flux_Energy -= C * 0.5 * (en_L - en_R)
    flux_By -= C * 0.5 * (By_L - By_R)

    return flux_Mass, flux_Momx, flux_Momy, flux_Energy, flux_By


def run_simulation(config):
    """Run the MHD constrained transport simulation."""
    N = config["N"]
    boxsize = config["boxsize"]
    gamma = config["gamma"]
    courant_fac = config["courant_fac"]
    tEnd = config["tEnd"]
    useSlopeLimiting = config["useSlopeLimiting"]

    dx = boxsize / N
    vol = dx**2

    # Read initial conditions from HDF5
    with h5py.File('/app/initial_conditions.h5', 'r') as f:
        rho = f['rho'][:]
        vx = f['vx'][:]
        vy = f['vy'][:]
        P_gas = f['P_gas'][:]
        bx = f['bx_face'][:]
        by = f['by_face'][:]

    Bx, By = getBavg(bx, by)
    P = P_gas + 0.5 * (Bx**2 + By**2)

    Mass, Momx, Momy, Energy = getConserved(rho, vx, vy, P, Bx, By, gamma, vol)

    t = 0
    step = 0

    while t < tEnd:
        Bx, By = getBavg(bx, by)
        rho, vx, vy, P = getPrimitive(Mass, Momx, Momy, Energy, Bx, By, gamma, vol)

        c0 = np.sqrt(gamma * (P - 0.5 * (Bx**2 + By**2)) / rho)
        ca = np.sqrt((Bx**2 + By**2) / rho)
        cf = np.sqrt(0.5 * (c0**2 + ca**2) + 0.5 * np.sqrt((c0**2 + ca**2) ** 2))
        dt = courant_fac * np.min(dx / (cf + np.sqrt(vx**2 + vy**2)))
        if t + dt > tEnd:
            dt = tEnd - t

        rho_dx, rho_dy = getGradient(rho, dx)
        vx_dx, vx_dy = getGradient(vx, dx)
        vy_dx, vy_dy = getGradient(vy, dx)
        P_dx, P_dy = getGradient(P, dx)
        Bx_dx, Bx_dy = getGradient(Bx, dx)
        By_dx, By_dy = getGradient(By, dx)

        if useSlopeLimiting:
            rho_dx, rho_dy = slopeLimit(rho, dx, rho_dx, rho_dy)
            vx_dx, vx_dy = slopeLimit(vx, dx, vx_dx, vx_dy)
            vy_dx, vy_dy = slopeLimit(vy, dx, vy_dx, vy_dy)
            P_dx, P_dy = slopeLimit(P, dx, P_dx, P_dy)
            Bx_dx, Bx_dy = slopeLimit(Bx, dx, Bx_dx, Bx_dy)
            By_dx, By_dy = slopeLimit(By, dx, By_dx, By_dy)

        rho_prime = rho - 0.5 * dt * (
            vx * rho_dx + rho * vx_dx + vy * rho_dy + rho * vy_dy
        )
        vx_prime = vx - 0.5 * dt * (
            vx * vx_dx + vy * vx_dy + (1 / rho) * P_dx
            - (2 * Bx / rho) * Bx_dx - (By / rho) * Bx_dy - (Bx / rho) * By_dy
        )
        vy_prime = vy - 0.5 * dt * (
            vx * vy_dx + vy * vy_dy + (1 / rho) * P_dy
            - (2 * By / rho) * By_dy - (Bx / rho) * By_dx - (By / rho) * Bx_dx
        )
        P_prime = P - 0.5 * dt * (
            (gamma * (P - 0.5 * (Bx**2 + By**2)) + By**2) * vx_dx
            - Bx * By * vy_dx + vx * P_dx
            + (gamma - 2) * (Bx * vx + By * vy) * Bx_dx
            - By * Bx * vx_dy
            + (gamma * (P - 0.5 * (Bx**2 + By**2)) + Bx**2) * vy_dy
            + vy * P_dy
            + (gamma - 2) * (Bx * vx + By * vy) * By_dy
        )
        Bx_prime = Bx - 0.5 * dt * (-By * vx_dy + Bx * vy_dy + vy * Bx_dy - vx * By_dy)
        By_prime = By - 0.5 * dt * (By * vx_dx - Bx * vy_dx - vy * Bx_dx + vx * By_dx)

        rho_XL, rho_XR, rho_YL, rho_YR = extrapolateInSpaceToFace(rho_prime, rho_dx, rho_dy, dx)
        vx_XL, vx_XR, vx_YL, vx_YR = extrapolateInSpaceToFace(vx_prime, vx_dx, vx_dy, dx)
        vy_XL, vy_XR, vy_YL, vy_YR = extrapolateInSpaceToFace(vy_prime, vy_dx, vy_dy, dx)
        P_XL, P_XR, P_YL, P_YR = extrapolateInSpaceToFace(P_prime, P_dx, P_dy, dx)
        Bx_XL, Bx_XR, Bx_YL, Bx_YR = extrapolateInSpaceToFace(Bx_prime, Bx_dx, Bx_dy, dx)
        By_XL, By_XR, By_YL, By_YR = extrapolateInSpaceToFace(By_prime, By_dx, By_dy, dx)

        flux_Mass_X, flux_Momx_X, flux_Momy_X, flux_Energy_X, flux_By_X = getFlux(
            rho_XL, rho_XR, vx_XL, vx_XR, vy_XL, vy_XR,
            P_XL, P_XR, Bx_XL, Bx_XR, By_XL, By_XR, gamma
        )
        flux_Mass_Y, flux_Momy_Y, flux_Momx_Y, flux_Energy_Y, flux_Bx_Y = getFlux(
            rho_YL, rho_YR, vy_YL, vy_YR, vx_YL, vx_YR,
            P_YL, P_YR, By_YL, By_YR, Bx_YL, Bx_YR, gamma
        )

        Mass = applyFluxes(Mass, flux_Mass_X, flux_Mass_Y, dx, dt)
        Momx = applyFluxes(Momx, flux_Momx_X, flux_Momx_Y, dx, dt)
        Momy = applyFluxes(Momy, flux_Momy_X, flux_Momy_Y, dx, dt)
        Energy = applyFluxes(Energy, flux_Energy_X, flux_Energy_Y, dx, dt)

        bx, by = constrainedTransport(bx, by, flux_By_X, flux_Bx_Y, dx, dt)

        t += dt
        step += 1

    # Final state
    Bx, By = getBavg(bx, by)
    rho, vx, vy, P = getPrimitive(Mass, Momx, Momy, Energy, Bx, By, gamma, vol)
    divB = getDiv(bx, by, dx)
    P_gas = P - 0.5 * (Bx**2 + By**2)

    # Write density grid for gnuplot
    np.savetxt('/app/density_final.dat', rho, fmt='%.8e')

    results = {
        "total_mass": float(np.sum(Mass)),
        "total_energy": float(np.sum(Energy)),
        "total_momx": float(np.sum(Momx)),
        "total_momy": float(np.sum(Momy)),
        "max_divB": float(np.max(np.abs(divB))),
        "max_density": float(np.max(rho)),
        "min_density": float(np.min(rho)),
        "mean_density": float(np.mean(rho)),
        "magnetic_energy": float(np.sum(0.5 * (Bx**2 + By**2) * vol)),
        "kinetic_energy": float(np.sum(0.5 * rho * (vx**2 + vy**2) * vol)),
        "internal_energy": float(np.sum(P_gas / (gamma - 1) * vol)),
        "num_steps": step,
    }
    return results


if __name__ == "__main__":
    with open("/app/config.json") as f:
        config = json.load(f)
    results = run_simulation(config)
    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("MHD simulation complete. Results written to /app/results.json")
    for k, v in results.items():
        print(f"  {k}: {v}")
