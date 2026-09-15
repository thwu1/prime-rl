"""
2D Ideal MHD Finite Volume Solver with Constrained Transport

Extends the Euler finite volume solver to the ideal MHD equations.
Uses Rusanov (Local Lax-Friedrichs) flux with MHD terms and
constrained transport for divergence-free magnetic field evolution.

Runs the Orszag-Tang vortex problem and saves output to /app/output/.
"""


import numpy as np
import h5py
import json
import os


# ============================================================
# Utility functions (shared with Euler solver)
# ============================================================

def getGradient(f, dx):
    """Compute centered finite-difference gradients of field f."""
    R = -1
    L = 1
    f_dx = (np.roll(f, R, axis=0) - np.roll(f, L, axis=0)) / (2 * dx)
    f_dy = (np.roll(f, R, axis=1) - np.roll(f, L, axis=1)) / (2 * dx)
    return f_dx, f_dy


def slopeLimit(f, dx, f_dx, f_dy):
    """Apply minmod-style slope limiter to gradients."""
    R = -1
    L = 1
    f_dx = (
        np.maximum(0.0, np.minimum(1.0,
            ((f - np.roll(f, L, axis=0)) / dx) / (f_dx + 1.0e-8 * (f_dx == 0))
        )) * f_dx
    )
    f_dx = (
        np.maximum(0.0, np.minimum(1.0,
            (-(f - np.roll(f, R, axis=0)) / dx) / (f_dx + 1.0e-8 * (f_dx == 0))
        )) * f_dx
    )
    f_dy = (
        np.maximum(0.0, np.minimum(1.0,
            ((f - np.roll(f, L, axis=1)) / dx) / (f_dy + 1.0e-8 * (f_dy == 0))
        )) * f_dy
    )
    f_dy = (
        np.maximum(0.0, np.minimum(1.0,
            (-(f - np.roll(f, R, axis=1)) / dx) / (f_dy + 1.0e-8 * (f_dy == 0))
        )) * f_dy
    )
    return f_dx, f_dy


def extrapolateInSpaceToFace(f, f_dx, f_dy, dx):
    """Extrapolate field values to cell face centers using gradients."""
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
    """Apply conservative flux update to field F."""
    R = -1
    L = 1
    F += -dt * dx * flux_F_X
    F += dt * dx * np.roll(flux_F_X, L, axis=0)
    F += -dt * dx * flux_F_Y
    F += dt * dx * np.roll(flux_F_Y, L, axis=1)
    return F


# ============================================================
# MHD-specific functions
# ============================================================

def getCurl(Az, dx):
    """
    Compute discrete curl of a scalar potential Az to get
    face-centered magnetic field components.
    Az is defined at cell corner nodes (top-right of each cell).
    Returns face-centered bx (at x-faces) and by (at y-faces).
    """
    R = -1
    L = 1
    bx = (Az - np.roll(Az, L, axis=1)) / dx   # d Az / d y
    by = -(Az - np.roll(Az, L, axis=0)) / dx   # -d Az / d x
    return bx, by


def getDiv(bx, by, dx):
    """
    Compute discrete divergence of face-centered magnetic field.
    divB[i,j] = (bx[i,j] - bx[i-1,j] + by[i,j] - by[i,j-1]) / dx
    """
    R = -1
    L = 1
    divB = (bx - np.roll(bx, L, axis=0) + by - np.roll(by, L, axis=1)) / dx
    return divB


def getBavg(bx, by):
    """
    Compute cell-averaged magnetic field from face-centered values.
    Bx[i,j] = 0.5 * (bx[i,j] + bx[i-1,j])
    By[i,j] = 0.5 * (by[i,j] + by[i,j-1])
    """
    R = -1
    L = 1
    Bx = 0.5 * (bx + np.roll(bx, L, axis=0))
    By = 0.5 * (by + np.roll(by, L, axis=1))
    return Bx, By


def getConservedMHD(rho, vx, vy, P, Bx, By, gamma, vol):
    """
    Convert primitive to conserved variables for MHD.
    P is the TOTAL pressure (gas + magnetic).
    Energy includes kinetic + thermal + magnetic contributions.
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


def getPrimitiveMHD(Mass, Momx, Momy, Energy, Bx, By, gamma, vol):
    """
    Convert conserved to primitive variables for MHD.
    Returns TOTAL pressure P = P_gas + 0.5 * B^2.
    """
    rho = Mass / vol
    vx = Momx / rho / vol
    vy = Momy / rho / vol
    P = (
        (Energy / vol - 0.5 * rho * (vx**2 + vy**2) - 0.5 * (Bx**2 + By**2))
        * (gamma - 1)
        + 0.5 * (Bx**2 + By**2)
    )
    return rho, vx, vy, P


def getFluxMHD(rho_L, rho_R, vx_L, vx_R, vy_L, vy_R,
               P_L, P_R, Bx_L, Bx_R, By_L, By_R, gamma):
    """
    Compute Rusanov (Local Lax-Friedrichs) fluxes for the MHD equations.

    The "normal" direction is the first velocity/B component.
    To compute y-direction fluxes, swap (vx,vy) and (Bx,By) in the call.

    P is total pressure (gas + magnetic).

    Returns: flux_Mass, flux_Momx, flux_Momy, flux_Energy, flux_By
    """
    # Energy densities (total: internal + kinetic + magnetic)
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

    # Averaged states
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

    # Central fluxes (MHD)
    flux_Mass = momx_star
    flux_Momx = momx_star**2 / rho_star + P_star - Bx_star * Bx_star
    flux_Momy = momx_star * momy_star / rho_star - Bx_star * By_star
    flux_Energy = (
        (en_star + P_star) * momx_star / rho_star
        - Bx_star * (Bx_star * momx_star + By_star * momy_star) / rho_star
    )
    flux_By = (By_star * momx_star - Bx_star * momy_star) / rho_star

    # Wave speeds: fast magnetosonic + flow
    c0_L = np.sqrt(gamma * (P_L - 0.5 * (Bx_L**2 + By_L**2)) / rho_L)
    c0_R = np.sqrt(gamma * (P_R - 0.5 * (Bx_R**2 + By_R**2)) / rho_R)
    ca_L = np.sqrt((Bx_L**2 + By_L**2) / rho_L)
    ca_R = np.sqrt((Bx_R**2 + By_R**2) / rho_R)
    cf_L = np.sqrt(0.5 * (c0_L**2 + ca_L**2) + 0.5 * np.sqrt((c0_L**2 + ca_L**2)**2))
    cf_R = np.sqrt(0.5 * (c0_R**2 + ca_R**2) + 0.5 * np.sqrt((c0_R**2 + ca_R**2)**2))
    C_L = cf_L + np.abs(vx_L)
    C_R = cf_R + np.abs(vx_R)
    C = np.maximum(C_L, C_R)

    # Rusanov diffusion
    flux_Mass -= C * 0.5 * (rho_L - rho_R)
    flux_Momx -= C * 0.5 * (rho_L * vx_L - rho_R * vx_R)
    flux_Momy -= C * 0.5 * (rho_L * vy_L - rho_R * vy_R)
    flux_Energy -= C * 0.5 * (en_L - en_R)
    flux_By -= C * 0.5 * (By_L - By_R)

    return flux_Mass, flux_Momx, flux_Momy, flux_Energy, flux_By


def constrainedTransport(bx, by, flux_By_X, flux_Bx_Y, dx, dt):
    """
    Update face-centered magnetic fields using constrained transport.
    Averages 4 flux values around each cell corner to get the corner
    electric field Ez, then updates face fields via the discrete curl.
    This preserves div(B) = 0 to machine precision.
    """
    R = -1
    L = 1

    # Ez at top-right node of each cell: average of 4 surrounding fluxes
    Ez = 0.25 * (
        -flux_By_X
        - np.roll(flux_By_X, R, axis=1)
        + flux_Bx_Y
        + np.roll(flux_Bx_Y, R, axis=0)
    )

    # Update face fields via curl of -Ez
    dbx, dby = getCurl(-Ez, dx)
    bx += dt * dbx
    by += dt * dby

    return bx, by


# ============================================================
# Main simulation
# ============================================================

def main():
    """Run the Orszag-Tang vortex MHD problem."""

    # Parameters
    N = 128
    boxsize = 1.0
    gamma = 5.0 / 3.0
    courant_fac = 0.4
    t = 0.0
    tEnd = 0.5
    useSlopeLimiting = True

    # Mesh
    dx = boxsize / N
    vol = dx**2
    xlin = np.linspace(0.5 * dx, boxsize - 0.5 * dx, N)
    Y, X = np.meshgrid(xlin, xlin)

    # Node positions (top-right corner of each cell)
    xlin_node = np.linspace(dx, boxsize, N)
    Yn, Xn = np.meshgrid(xlin_node, xlin_node)

    # ---- Orszag-Tang initial conditions ----
    rho = (gamma**2 / (4.0 * np.pi)) * np.ones(X.shape)
    vx = -np.sin(2.0 * np.pi * Y)
    vy = np.sin(2.0 * np.pi * X)
    P_gas = (gamma / (4.0 * np.pi)) * np.ones(X.shape)

    # Magnetic vector potential at cell corner nodes
    Az = (
        np.cos(4.0 * np.pi * Xn) / (4.0 * np.pi * np.sqrt(4.0 * np.pi))
        + np.cos(2.0 * np.pi * Yn) / (2.0 * np.pi * np.sqrt(4.0 * np.pi))
    )

    # Face-centered B from curl of Az
    bx, by = getCurl(Az, dx)

    # Cell-averaged B
    Bx, By = getBavg(bx, by)

    # Total pressure = gas pressure + magnetic pressure
    P = P_gas + 0.5 * (Bx**2 + By**2)

    # Conserved variables
    Mass, Momx, Momy, Energy = getConservedMHD(rho, vx, vy, P, Bx, By, gamma, vol)

    # Conservation tracking
    mass_history = [float(np.sum(Mass))]
    energy_history = [float(np.sum(Energy))]

    step = 0

    # ---- Time integration loop ----
    while t < tEnd:
        # Get cell-averaged B and primitive variables
        Bx, By = getBavg(bx, by)
        rho, vx, vy, P = getPrimitiveMHD(Mass, Momx, Momy, Energy, Bx, By, gamma, vol)

        # CFL condition using fast magnetosonic speed
        c0 = np.sqrt(gamma * (P - 0.5 * (Bx**2 + By**2)) / rho)
        ca = np.sqrt((Bx**2 + By**2) / rho)
        cf = np.sqrt(0.5 * (c0**2 + ca**2) + 0.5 * np.sqrt((c0**2 + ca**2)**2))
        dt_step = courant_fac * np.min(dx / (cf + np.sqrt(vx**2 + vy**2)))
        if t + dt_step > tEnd:
            dt_step = tEnd - t

        # Compute gradients of all primitive variables
        rho_dx, rho_dy = getGradient(rho, dx)
        vx_dx, vx_dy = getGradient(vx, dx)
        vy_dx, vy_dy = getGradient(vy, dx)
        P_dx, P_dy = getGradient(P, dx)
        Bx_dx, Bx_dy = getGradient(Bx, dx)
        By_dx, By_dy = getGradient(By, dx)

        # Slope limiting
        if useSlopeLimiting:
            rho_dx, rho_dy = slopeLimit(rho, dx, rho_dx, rho_dy)
            vx_dx, vx_dy = slopeLimit(vx, dx, vx_dx, vx_dy)
            vy_dx, vy_dy = slopeLimit(vy, dx, vy_dx, vy_dy)
            P_dx, P_dy = slopeLimit(P, dx, P_dx, P_dy)
            Bx_dx, Bx_dy = slopeLimit(Bx, dx, Bx_dx, Bx_dy)
            By_dx, By_dy = slopeLimit(By, dx, By_dx, By_dy)

        # Half-step time extrapolation using MHD primitive equations
        rho_prime = rho - 0.5 * dt_step * (
            vx * rho_dx + rho * vx_dx + vy * rho_dy + rho * vy_dy
        )
        vx_prime = vx - 0.5 * dt_step * (
            vx * vx_dx + vy * vx_dy + (1.0 / rho) * P_dx
            - (2.0 * Bx / rho) * Bx_dx
            - (By / rho) * Bx_dy
            - (Bx / rho) * By_dy
        )
        vy_prime = vy - 0.5 * dt_step * (
            vx * vy_dx + vy * vy_dy + (1.0 / rho) * P_dy
            - (2.0 * By / rho) * By_dy
            - (Bx / rho) * By_dx
            - (By / rho) * Bx_dx
        )
        P_prime = P - 0.5 * dt_step * (
            (gamma * (P - 0.5 * (Bx**2 + By**2)) + By**2) * vx_dx
            - Bx * By * vy_dx
            + vx * P_dx
            + (gamma - 2.0) * (Bx * vx + By * vy) * Bx_dx
            - By * Bx * vx_dy
            + (gamma * (P - 0.5 * (Bx**2 + By**2)) + Bx**2) * vy_dy
            + vy * P_dy
            + (gamma - 2.0) * (Bx * vx + By * vy) * By_dy
        )
        Bx_prime = Bx - 0.5 * dt_step * (
            -By * vx_dy + Bx * vy_dy + vy * Bx_dy - vx * By_dy
        )
        By_prime = By - 0.5 * dt_step * (
            By * vx_dx - Bx * vy_dx - vy * Bx_dx + vx * By_dx
        )

        # Extrapolate to face centers
        rho_XL, rho_XR, rho_YL, rho_YR = extrapolateInSpaceToFace(rho_prime, rho_dx, rho_dy, dx)
        vx_XL, vx_XR, vx_YL, vx_YR = extrapolateInSpaceToFace(vx_prime, vx_dx, vx_dy, dx)
        vy_XL, vy_XR, vy_YL, vy_YR = extrapolateInSpaceToFace(vy_prime, vy_dx, vy_dy, dx)
        P_XL, P_XR, P_YL, P_YR = extrapolateInSpaceToFace(P_prime, P_dx, P_dy, dx)
        Bx_XL, Bx_XR, Bx_YL, Bx_YR = extrapolateInSpaceToFace(Bx_prime, Bx_dx, Bx_dy, dx)
        By_XL, By_XR, By_YL, By_YR = extrapolateInSpaceToFace(By_prime, By_dx, By_dy, dx)

        # X-direction fluxes (normal = x)
        flux_Mass_X, flux_Momx_X, flux_Momy_X, flux_Energy_X, flux_By_X = getFluxMHD(
            rho_XL, rho_XR, vx_XL, vx_XR, vy_XL, vy_XR,
            P_XL, P_XR, Bx_XL, Bx_XR, By_XL, By_XR, gamma
        )

        # Y-direction fluxes (swap velocity and B components)
        flux_Mass_Y, flux_Momy_Y, flux_Momx_Y, flux_Energy_Y, flux_Bx_Y = getFluxMHD(
            rho_YL, rho_YR, vy_YL, vy_YR, vx_YL, vx_YR,
            P_YL, P_YR, By_YL, By_YR, Bx_YL, Bx_YR, gamma
        )

        # Update conserved variables via finite volume fluxes
        Mass = applyFluxes(Mass, flux_Mass_X, flux_Mass_Y, dx, dt_step)
        Momx = applyFluxes(Momx, flux_Momx_X, flux_Momx_Y, dx, dt_step)
        Momy = applyFluxes(Momy, flux_Momy_X, flux_Momy_Y, dx, dt_step)
        Energy = applyFluxes(Energy, flux_Energy_X, flux_Energy_Y, dx, dt_step)

        # Update face-centered B via constrained transport
        bx, by = constrainedTransport(bx, by, flux_By_X, flux_Bx_Y, dx, dt_step)

        t += dt_step
        step += 1

        mass_history.append(float(np.sum(Mass)))
        energy_history.append(float(np.sum(Energy)))

    # ---- Final state ----
    Bx, By = getBavg(bx, by)
    rho, vx_f, vy_f, P_f = getPrimitiveMHD(Mass, Momx, Momy, Energy, Bx, By, gamma, vol)
    divB = getDiv(bx, by, dx)

    # ---- Save output ----
    os.makedirs("/app/output", exist_ok=True)

    # HDF5 output
    with h5py.File("/app/output/results.h5", "w") as hf:
        hf.create_dataset("density", data=rho)
        hf.create_dataset("divB", data=divB)
        hf.create_dataset("Bx", data=Bx)
        hf.create_dataset("By", data=By)
        hf.create_dataset("mass_history", data=np.array(mass_history))
        hf.create_dataset("energy_history", data=np.array(energy_history))

    # Parameters JSON
    with open("/app/output/params.json", "w") as f:
        json.dump({
            "N": N,
            "gamma": gamma,
            "tEnd": tEnd,
            "courant_fac": courant_fac
        }, f)

    # Text data for gnuplot
    np.savetxt("/app/output/density.dat", rho)
    np.savetxt("/app/output/divB_abs.dat", np.abs(divB))

    print(f"Orszag-Tang MHD simulation complete: {step} steps, t = {t:.6f}")
    print(f"Density range: [{np.min(rho):.6f}, {np.max(rho):.6f}]")
    print(f"Max |divB|: {np.max(np.abs(divB)):.2e}")
    print(f"Mass conservation: {np.abs(mass_history[-1] - mass_history[0]) / abs(mass_history[0]):.2e}")
    print(f"Energy conservation: {np.abs(energy_history[-1] - energy_history[0]) / abs(energy_history[0]):.2e}")


if __name__ == "__main__":
    main()
