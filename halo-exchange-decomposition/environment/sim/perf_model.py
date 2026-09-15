"""Performance modelling for domain-decomposed particle simulations.

The per-timestep wall time of a bulk-synchronous parallel simulation is
determined by the slowest rank in each phase:

    T_total = T_comp + T_comm

where

    T_comp = max_over_ranks(particles_in_rank) * per_particle_cost
    T_comm = max_over_ranks(rank_communication_time)

The communication time of a single rank is the sum of message costs
over all active face directions.
"""

import numpy as np

try:
    from .decompose import valid_grids, assign_particles
    from .comm import compute_face_halos, aggregate_comm_costs
except ImportError:
    from decompose import valid_grids, assign_particles
    from comm import compute_face_halos, aggregate_comm_costs


def evaluate_grid(positions, grid, domain_extents, cutoff,
                  msg_latency, per_datum_xfer, per_particle_compute):
    """Evaluate performance metrics for a single processor grid.

    Args:
        positions: (N, 3) particle positions
        grid: (Px, Py, Pz) processor grid
        domain_extents: (Lx, Ly, Lz) box dimensions
        cutoff: interaction cutoff radius
        msg_latency: per-message latency (seconds)
        per_datum_xfer: per-particle transfer cost (seconds)
        per_particle_compute: computation cost per particle (seconds)

    Returns:
        dict with keys: grid, T_total, T_comp, T_comm,
        load_imbalance, max_particles_per_rank, comm_volume
    """
    px, py, pz = grid
    n_ranks = px * py * pz

    ix, iy, iz, dx, dy, dz = assign_particles(positions, grid, domain_extents)
    rank_id = ix * (py * pz) + iy * pz + iz
    rank_counts = np.bincount(rank_id, minlength=n_ranks)

    max_load = int(rank_counts.max())
    load_imbalance = max_load / (len(positions) / n_ranks)

    face_sends, _, _ = compute_face_halos(
        positions, grid, domain_extents, cutoff,
        (ix, iy, iz), (dx, dy, dz))
    halo_totals, comm_times = aggregate_comm_costs(
        face_sends, grid, n_ranks, msg_latency, per_datum_xfer)

    T_comp = float(max_load * per_particle_compute)
    T_comm = float(comm_times.max())

    return {
        'grid': list(grid),
        'T_total': T_comp + T_comm,
        'T_comp': T_comp,
        'T_comm': T_comm,
        'load_imbalance': float(load_imbalance),
        'max_particles_per_rank': max_load,
        'comm_volume': int(halo_totals.sum()),
    }
