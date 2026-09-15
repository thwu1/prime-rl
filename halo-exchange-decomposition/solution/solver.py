
"""
Reference solver: determines performance-optimal 3D processor grids
by reading the simulation framework code, HDF5 particle data, and
YAML configuration.
"""

import numpy as np
import h5py
import yaml
import json


def enumerate_grids(P, box, rc):
    """Enumerate all valid (Px, Py, Pz) factorizations of P."""
    Lx, Ly, Lz = box
    grids = []
    for px in range(1, P + 1):
        if P % px != 0:
            continue
        if Lx / px < 2 * rc:
            continue
        remainder = P // px
        for py in range(1, remainder + 1):
            if remainder % py != 0:
                continue
            if Ly / py < 2 * rc:
                continue
            pz = remainder // py
            if Lz / pz < 2 * rc:
                continue
            grids.append((px, py, pz))
    return grids


def analyze_grid(particles, box, rc, grid, alpha, beta, t_compute):
    """Analyze a single processor grid decomposition."""
    px, py, pz = grid
    Lx, Ly, Lz = box
    dx, dy, dz = Lx / px, Ly / py, Lz / pz
    N = len(particles)
    total_ranks = px * py * pz

    ix = np.minimum((particles[:, 0] / dx).astype(int), px - 1)
    iy = np.minimum((particles[:, 1] / dy).astype(int), py - 1)
    iz = np.minimum((particles[:, 2] / dz).astype(int), pz - 1)
    rank_ids = ix * (py * pz) + iy * pz + iz

    rank_counts = np.bincount(rank_ids, minlength=total_ranks)
    max_load = int(rank_counts.max())
    load_imbalance = max_load / (N / total_ranks)

    frac_x = (particles[:, 0] - ix * dx) / dx
    frac_y = (particles[:, 1] - iy * dy) / dy
    frac_z = (particles[:, 2] - iz * dz) / dz

    face_sends = {}
    if px > 1:
        face_sends['x_lo'] = np.bincount(
            rank_ids[frac_x < (rc / dx)], minlength=total_ranks)
        face_sends['x_hi'] = np.bincount(
            rank_ids[frac_x > (1.0 - rc / dx)], minlength=total_ranks)
    if py > 1:
        face_sends['y_lo'] = np.bincount(
            rank_ids[frac_y < (rc / dy)], minlength=total_ranks)
        face_sends['y_hi'] = np.bincount(
            rank_ids[frac_y > (1.0 - rc / dy)], minlength=total_ranks)
    if pz > 1:
        face_sends['z_lo'] = np.bincount(
            rank_ids[frac_z < (rc / dz)], minlength=total_ranks)
        face_sends['z_hi'] = np.bincount(
            rank_ids[frac_z > (1.0 - rc / dz)], minlength=total_ranks)

    comm_times = np.zeros(total_ranks)
    halo_counts = np.zeros(total_ranks, dtype=np.int64)

    for cx in range(px):
        for cy in range(py):
            for cz in range(pz):
                r = cx * (py * pz) + cy * pz + cz

                if px > 1:
                    nbr = ((cx + 1) % px) * (py * pz) + cy * pz + cz
                    h = int(face_sends['x_lo'][nbr])
                    halo_counts[r] += h
                    comm_times[r] += alpha + beta * h

                    nbr = ((cx - 1) % px) * (py * pz) + cy * pz + cz
                    h = int(face_sends['x_hi'][nbr])
                    halo_counts[r] += h
                    comm_times[r] += alpha + beta * h

                if py > 1:
                    nbr = cx * (py * pz) + ((cy + 1) % py) * pz + cz
                    h = int(face_sends['y_lo'][nbr])
                    halo_counts[r] += h
                    comm_times[r] += alpha + beta * h

                    nbr = cx * (py * pz) + ((cy - 1) % py) * pz + cz
                    h = int(face_sends['y_hi'][nbr])
                    halo_counts[r] += h
                    comm_times[r] += alpha + beta * h

                if pz > 1:
                    nbr = cx * (py * pz) + cy * pz + (cz + 1) % pz
                    h = int(face_sends['z_lo'][nbr])
                    halo_counts[r] += h
                    comm_times[r] += alpha + beta * h

                    nbr = cx * (py * pz) + cy * pz + (cz - 1) % pz
                    h = int(face_sends['z_hi'][nbr])
                    halo_counts[r] += h
                    comm_times[r] += alpha + beta * h

    T_comp = float(max_load * t_compute)
    T_comm = float(comm_times.max())
    T_total = T_comp + T_comm

    return {
        'grid': list(grid),
        'T_total': T_total,
        'T_comp': T_comp,
        'T_comm': T_comm,
        'load_imbalance': float(load_imbalance),
        'max_particles_per_rank': max_load,
        'comm_volume': int(halo_counts.sum()),
    }


def main():
    # Read HDF5 particle data
    with h5py.File('/app/data/particles.h5', 'r') as f:
        particles = f['positions'][:]

    # Read YAML config
    with open('/app/config.yaml') as f:
        raw = yaml.safe_load(f)

    box = raw['simulation']['domain']['extents']
    rc = raw['simulation']['interactions']['cutoff']
    proc_counts = raw['scaling_study']['target_counts']
    alpha = raw['platform']['network']['msg_startup_latency_sec']
    beta = raw['platform']['network']['per_datum_transfer_cost_sec']
    t_compute = raw['platform']['compute']['per_particle_flop_cost_sec']

    output = {'decompositions': {}}

    for P in proc_counts:
        grids = enumerate_grids(P, box, rc)
        candidates = []
        for g in grids:
            result = analyze_grid(particles, box, rc, g, alpha, beta, t_compute)
            candidates.append(result)

        candidates.sort(key=lambda c: c['T_total'])
        best = candidates[0]

        output['decompositions'][str(P)] = {
            'optimal': best['grid'],
            'T_total': best['T_total'],
            'T_comp': best['T_comp'],
            'T_comm': best['T_comm'],
            'load_imbalance': best['load_imbalance'],
            'max_particles_per_rank': best['max_particles_per_rank'],
            'comm_volume': best['comm_volume'],
            'all_candidates': candidates,
        }

    with open('/app/results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == '__main__':
    main()
