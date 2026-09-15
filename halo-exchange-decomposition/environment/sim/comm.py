"""Halo exchange communication model for domain-decomposed simulations.

In a spatial domain decomposition with short-range interactions, each rank
needs particle data from neighbouring subdomains within the interaction
cutoff distance.  This is accomplished through halo exchange: particles
near subdomain faces are sent to adjacent ranks.

This module implements a 6-direction face-neighbor halo exchange with
periodic boundary conditions.  Each rank exchanges with its six face
neighbours (+/-x, +/-y, +/-z).

Communication cost per message follows the latency-bandwidth model:

    t_msg = latency + bandwidth_cost * n_particles

where `latency` is the per-message startup overhead and `bandwidth_cost`
is the per-particle transfer cost.
"""

import numpy as np


def compute_face_halos(positions, grid, domain_extents, cutoff,
                       rank_indices, subdomain_dims):
    """Identify halo particles for each face direction.

    For each active dimension (P_dim > 1), particles within ``cutoff``
    of a subdomain face are candidates for halo exchange.  The counts
    are returned per rank and per face label.

    Args:
        positions: (N, 3) particle coordinates
        grid: (Px, Py, Pz) processor grid
        domain_extents: (Lx, Ly, Lz) box dimensions
        cutoff: interaction cutoff radius
        rank_indices: (ix, iy, iz) arrays from ``assign_particles``
        subdomain_dims: (dx, dy, dz) from ``assign_particles``

    Returns:
        face_sends: dict mapping face label to per-rank send counts
        rank_id: linearised rank index per particle
        n_ranks: total number of ranks
    """
    px, py, pz = grid
    ix, iy, iz = rank_indices
    dx, dy, dz = subdomain_dims
    n_ranks = px * py * pz

    rank_id = ix * (py * pz) + iy * pz + iz

    # Fractional position within each particle's subdomain [0, 1)
    fx = (positions[:, 0] - ix * dx) / dx
    fy = (positions[:, 1] - iy * dy) / dy
    fz = (positions[:, 2] - iz * dz) / dz

    face_sends = {}
    if px > 1:
        face_sends['x_lo'] = np.bincount(
            rank_id[fx < cutoff / dx], minlength=n_ranks)
        face_sends['x_hi'] = np.bincount(
            rank_id[fx > 1 - cutoff / dx], minlength=n_ranks)
    if py > 1:
        face_sends['y_lo'] = np.bincount(
            rank_id[fy < cutoff / dy], minlength=n_ranks)
        face_sends['y_hi'] = np.bincount(
            rank_id[fy > 1 - cutoff / dy], minlength=n_ranks)
    if pz > 1:
        face_sends['z_lo'] = np.bincount(
            rank_id[fz < cutoff / dz], minlength=n_ranks)
        face_sends['z_hi'] = np.bincount(
            rank_id[fz > 1 - cutoff / dz], minlength=n_ranks)

    return face_sends, rank_id, n_ranks


def aggregate_comm_costs(face_sends, grid, n_ranks, latency, per_datum_cost):
    """Compute per-rank communication cost from face halo data.

    Each rank receives halos from its periodic face neighbours:

    * From the +x neighbour: their ``x_lo`` particles
    * From the -x neighbour: their ``x_hi`` particles
    * (analogously for y and z)

    Per-direction cost:  ``latency + per_datum_cost * n_halo``

    Args:
        face_sends: dict from ``compute_face_halos``
        grid: (Px, Py, Pz) processor grid
        n_ranks: total number of ranks
        latency: per-message startup cost (seconds)
        per_datum_cost: per-particle transfer cost (seconds)

    Returns:
        halo_totals: per-rank total received halo particles
        comm_times: per-rank total communication time
    """
    px, py, pz = grid
    comm_times = np.zeros(n_ranks)
    halo_totals = np.zeros(n_ranks, dtype=np.int64)

    for cx in range(px):
        for cy in range(py):
            for cz in range(pz):
                r = cx * (py * pz) + cy * pz + cz

                if px > 1:
                    nbr = ((cx + 1) % px) * (py * pz) + cy * pz + cz
                    h = int(face_sends['x_lo'][nbr])
                    halo_totals[r] += h
                    comm_times[r] += latency + per_datum_cost * h

                    nbr = ((cx - 1) % px) * (py * pz) + cy * pz + cz
                    h = int(face_sends['x_hi'][nbr])
                    halo_totals[r] += h
                    comm_times[r] += latency + per_datum_cost * h

                if py > 1:
                    nbr = cx * (py * pz) + ((cy + 1) % py) * pz + cz
                    h = int(face_sends['y_lo'][nbr])
                    halo_totals[r] += h
                    comm_times[r] += latency + per_datum_cost * h

                    nbr = cx * (py * pz) + ((cy - 1) % py) * pz + cz
                    h = int(face_sends['y_hi'][nbr])
                    halo_totals[r] += h
                    comm_times[r] += latency + per_datum_cost * h

                if pz > 1:
                    nbr = cx * (py * pz) + cy * pz + (cz + 1) % pz
                    h = int(face_sends['z_lo'][nbr])
                    halo_totals[r] += h
                    comm_times[r] += latency + per_datum_cost * h

                    nbr = cx * (py * pz) + cy * pz + (cz - 1) % pz
                    h = int(face_sends['z_hi'][nbr])
                    halo_totals[r] += h
                    comm_times[r] += latency + per_datum_cost * h

    return halo_totals, comm_times
