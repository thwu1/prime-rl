"""Spatial domain decomposition for distributed particle simulations.

This module handles the partitioning of a 3D periodic simulation domain
into a regular grid of rectangular subdomains, and the assignment of
particles to their owning subdomains (ranks).

The minimum subdomain size constraint ensures correct neighbor list
construction: each subdomain dimension must be at least twice the
interaction cutoff radius.
"""

import numpy as np


def valid_grids(P, domain_extents, cutoff):
    """Enumerate all valid (Px, Py, Pz) factorizations of P.

    A factorization is valid iff every subdomain dimension is at least
    2 * cutoff, ensuring proper short-range interaction handling.

    Args:
        P: total number of processors
        domain_extents: (Lx, Ly, Lz) simulation box dimensions
        cutoff: interaction cutoff radius

    Returns:
        List of valid (Px, Py, Pz) tuples
    """
    Lx, Ly, Lz = domain_extents
    min_size = 2 * cutoff
    results = []
    for px in range(1, P + 1):
        if P % px != 0:
            continue
        if Lx / px < min_size:
            continue
        rem = P // px
        for py in range(1, rem + 1):
            if rem % py != 0:
                continue
            if Ly / py < min_size:
                continue
            pz = rem // py
            if Lz / pz < min_size:
                continue
            results.append((px, py, pz))
    return results


def assign_particles(positions, grid, domain_extents):
    """Assign particles to subdomains via regular spatial binning.

    Each particle is placed in the subdomain whose rectangular region
    contains it.  Particles at the upper boundary of a dimension are
    clamped to the last subdomain.

    Args:
        positions: (N, 3) array of particle positions
        grid: (Px, Py, Pz) processor grid
        domain_extents: (Lx, Ly, Lz) box dimensions

    Returns:
        ix, iy, iz: per-particle grid indices
        dx, dy, dz: subdomain dimensions
    """
    px, py, pz = grid
    Lx, Ly, Lz = domain_extents
    dx, dy, dz = Lx / px, Ly / py, Lz / pz
    ix = np.minimum((positions[:, 0] / dx).astype(int), px - 1)
    iy = np.minimum((positions[:, 1] / dy).astype(int), py - 1)
    iz = np.minimum((positions[:, 2] / dz).astype(int), pz - 1)
    return ix, iy, iz, dx, dy, dz
