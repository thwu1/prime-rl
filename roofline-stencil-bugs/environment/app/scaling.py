"""Parallel scaling models for HPC proxy application analysis.

Implements Amdahl's Law and Gustafson-Barsis' Law for predicting
parallel speedup of stencil-based proxy applications under strong
and weak scaling scenarios. Includes communication overhead estimation
for domain-decomposed stencil computations.
"""



def amdahl_speedup(num_procs, f_parallel):
    """Compute predicted speedup using Amdahl's Law (strong scaling).

    Amdahl's Law: S(p) = 1 / ((1 - f) + f / p)

    where f is the parallel fraction and p is the number of processors.

    Args:
        num_procs: Number of processors (p >= 1)
        f_parallel: Fraction of code that is parallelizable (0 <= f <= 1)

    Returns:
        Predicted speedup factor
    """
    f_serial = 1.0 - f_parallel
    return 1.0 / (f_serial + f_parallel * num_procs)


def gustafson_speedup(num_procs, f_serial):
    """Compute predicted scaled speedup using Gustafson-Barsis' Law.

    Gustafson's Law (weak scaling): S(p) = p - s * (p - 1)

    where s is the serial fraction and p is the number of processors.
    Models the scenario where problem size grows proportionally with
    processor count.

    Args:
        num_procs: Number of processors (p >= 1)
        f_serial: Serial fraction of the workload (0 <= s <= 1)

    Returns:
        Predicted scaled speedup
    """
    return num_procs + f_serial * (num_procs - 1)


def parallel_efficiency(speedup, num_procs):
    """Compute parallel efficiency: E = S(p) / p."""
    return speedup / num_procs


def strong_scaling_efficiency(num_procs, f_parallel):
    """Compute strong scaling efficiency using Amdahl's law."""
    s = amdahl_speedup(num_procs, f_parallel)
    return parallel_efficiency(s, num_procs)


def weak_scaling_efficiency(num_procs, f_serial):
    """Compute weak scaling efficiency using Gustafson's law."""
    s = gustafson_speedup(num_procs, f_serial)
    return parallel_efficiency(s, num_procs)


def communication_overhead(p, grid_nx, grid_ny, grid_nz, halo_width=1):
    """Estimate communication overhead from halo exchange in domain decomposition.

    Assumes 1D decomposition along the longest dimension.
    Each subdomain boundary requires exchanging a face of halo_width thickness.

    Communication volume per process = avg_faces * face_area * halo_width * elem_bytes
    where avg_faces accounts for interior vs edge processes.

    Args:
        p: Number of processes
        grid_nx, grid_ny, grid_nz: Global grid dimensions
        halo_width: Width of halo/ghost zone (default 1)

    Returns:
        Surface-to-volume communication ratio (dimensionless)
    """
    # Find longest dimension for 1D decomposition
    dims = [(grid_nx, 'x'), (grid_ny, 'y'), (grid_nz, 'z')]
    dims.sort(key=lambda d: d[0], reverse=True)
    split_dim_size = dims[0][0]
    other_dims = [d[0] for d in dims[1:]]

    # Each process has a subdomain of size (split_dim_size/p) in the split dimension
    local_split = split_dim_size / p

    # Face area (perpendicular to split dimension)
    face_area = other_dims[0] * other_dims[1]

    # Each internal process exchanges 2 faces (left + right boundaries)
    # Edge processes exchange 1 face each
    if p == 1:
        return 0.0

    # Average over all processes: (2*(p-2) + 1 + 1) / p = 2*(p-1)/p faces per process
    avg_faces = 2.0 * (p - 1) / p

    comm_volume_per_proc = avg_faces * face_area * halo_width * 8  # 8 bytes per double

    # Compute ratio to local computation volume
    local_volume = local_split * other_dims[0] * other_dims[1]
    surface_to_volume = comm_volume_per_proc / (local_volume * 8)

    return surface_to_volume
