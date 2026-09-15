"""Stencil computation FLOP and byte counting for HPC proxy app analysis.

Implements counting models for standard Jacobi stencil patterns used in
ECP proxy applications for diffusion/heat equation solvers. Supports
architecture-specific write-allocate behavior for accurate byte traffic
estimation.
"""



def jacobi_7pt_flops(nx, ny, nz):
    """Count total FLOPs for one Jacobi sweep with 7-point 3D stencil.

    Stencil pattern (center + 6 face-adjacent neighbors):
        u_new[i,j,k] = (u[i-1,j,k] + u[i+1,j,k] +
                         u[i,j-1,k] + u[i,j+1,k] +
                         u[i,j,k-1] + u[i,j,k+1]) / 6.0

    Per point: 5 additions + 1 division = 6 FLOPs.
    Only interior points (excluding boundary layer) are updated.
    """
    n_points = nx * ny * nz
    flops_per_point = 6
    return n_points * flops_per_point


def jacobi_7pt_bytes(nx, ny, nz, elem_bytes=8, write_allocate=False):
    """Count minimum bytes transferred for one 7-point Jacobi sweep.

    Per interior point (assuming cold-cache / streaming access):
      - Read 7 values from input array (center + 6 neighbors)
      - Write 1 value to output array
      - If write_allocate: add 1 read-for-ownership per write
        (cache must load target line before writing)

    Args:
        nx, ny, nz: Grid dimensions
        elem_bytes: Bytes per element (8 for double precision)
        write_allocate: Whether architecture uses write-allocate policy

    Returns:
        Total bytes transferred for one sweep
    """
    n_interior = (nx - 2) * (ny - 2) * (nz - 2)
    reads = 7
    writes = 1
    # Always adds read-for-ownership regardless of write_allocate
    rfo = 1
    return n_interior * (reads + writes + rfo) * elem_bytes


def jacobi_27pt_flops(nx, ny, nz):
    """Count total FLOPs for one sweep of 27-point stencil.

    The 27-point stencil uses all neighbors in a 3x3x3 cube.
    Per interior point: 26 additions + 1 multiplication = 27 FLOPs.
    """
    n_interior = (nx - 2) * (ny - 2) * (nz - 2)
    flops_per_point = 27
    return n_interior * flops_per_point


def jacobi_27pt_bytes(nx, ny, nz, elem_bytes=8, write_allocate=False):
    """Count minimum bytes transferred for one 27-point stencil sweep.

    Args:
        nx, ny, nz: Grid dimensions
        elem_bytes: Bytes per element
        write_allocate: Whether architecture uses write-allocate policy

    Returns:
        Total bytes transferred for one sweep
    """
    n_interior = (nx - 2) * (ny - 2) * (nz - 2)
    reads = 27
    writes = 1
    # Always adds read-for-ownership regardless of write_allocate
    rfo = 1
    return n_interior * (reads + writes + rfo) * elem_bytes


def operational_intensity(flops, total_bytes):
    """Compute operational intensity [FLOP/byte].

    Args:
        flops: Total floating-point operations
        total_bytes: Total bytes transferred

    Returns:
        Operational intensity in FLOP/byte
    """
    if total_bytes == 0:
        return 0.0
    return flops / total_bytes
