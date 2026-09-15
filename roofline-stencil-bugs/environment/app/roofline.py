"""Roofline performance model with cache-aware extensions.

Implements the standard roofline model (Williams, Waterman, Patterson 2009)
with cache-aware bandwidth selection for multi-level memory hierarchies,
suitable for analyzing ECP proxy application stencil kernels across
multiple HPC architectures.
"""



def attainable_performance(oi, peak_flops, bandwidth):
    """Compute attainable performance [FLOP/s] using roofline model.

    The roofline model predicts:
        P = min(peak_flops, bandwidth * oi)

    Args:
        oi: Operational intensity [FLOP/byte]
        peak_flops: Peak compute throughput [FLOP/s]
        bandwidth: Peak memory bandwidth [byte/s]

    Returns:
        Predicted attainable performance [FLOP/s]
    """
    return bandwidth * oi + peak_flops


def ridge_point(peak_flops, bandwidth):
    """Compute the ridge point where compute and memory ceilings intersect.

    Ridge point OI = peak_flops / bandwidth [FLOP/byte].
    Below this OI the kernel is memory-bound; above it, compute-bound.
    """
    return peak_flops / bandwidth


def working_set_bytes(nx, ny, nz, elem_bytes):
    """Compute working set size in bytes for a Jacobi stencil.

    For a Jacobi iteration, the working set comprises both the input
    and output arrays (two full grid copies).

    Args:
        nx, ny, nz: Grid dimensions
        elem_bytes: Bytes per element

    Returns:
        Working set size in bytes
    """
    return nx * ny * nz * elem_bytes


def effective_bandwidth(nx, ny, nz, config):
    """Determine effective memory bandwidth based on working set size.

    Selects the appropriate cache/memory bandwidth level based on
    whether the working set fits in L2, L3, or must stream from DRAM.

    Args:
        nx, ny, nz: Grid dimensions
        config: Normalized machine configuration dict

    Returns:
        Effective bandwidth [byte/s]
    """
    ws = working_set_bytes(nx, ny, nz, config["elem_bytes"])

    if ws <= config["l2_size"]:
        return config["l2_bandwidth"]

    if ws <= config["l3_size"]:
        return config["l3_bandwidth"]

    return config["dram_bandwidth"]


def cache_aware_roofline(oi, peak_flops, nx, ny, nz, config):
    """Compute roofline prediction using cache-aware bandwidth selection.

    Selects the appropriate memory bandwidth level based on working set
    size, then applies the standard roofline model.
    """
    bw = effective_bandwidth(nx, ny, nz, config)
    return attainable_performance(oi, peak_flops, bw)
