"""
Simulates GPU warp-level operations for parallel reduction.
Models __shfl_down_sync-based tree reduction within a warp of 32 threads.
"""


def warp_reduce(accumulators, combine_fn, warp_size=32):
    """Tree reduction within a simulated warp.

    Each element is combined with the element at (index + offset), where
    offset halves each iteration (like __shfl_down_sync on a GPU).

    Args:
        accumulators: list of WelfordAccumulator objects (may be < warp_size)
        combine_fn: function(a, b) -> combined accumulator
        warp_size: number of threads in a warp (default 32)

    Returns:
        Single combined WelfordAccumulator with the reduction result.
    """
    from .accumulator import WelfordAccumulator

    if not accumulators:
        return WelfordAccumulator()

    # Copy working set
    working = [a.copy() for a in accumulators]

    # Pad to warp_size with copies of first element
    while len(working) < warp_size:
        working.append(working[0].copy())

    # Tree reduction using simulated __shfl_down_sync
    offset = warp_size // 2
    while offset > 0:
        for i in range(offset):
            partner = i + offset
            working[i] = combine_fn(working[i], working[partner])
        offset //= 2

    return working[0]


def block_reduce(accumulators, combine_fn, warp_size=32):
    """Two-level reduction: first within warps, then across warp leaders.

    Args:
        accumulators: list of WelfordAccumulator objects (one per thread)
        combine_fn: function(a, b) -> combined accumulator
        warp_size: number of threads per warp

    Returns:
        Single combined WelfordAccumulator.
    """
    from .accumulator import WelfordAccumulator

    if not accumulators:
        return WelfordAccumulator()

    # Split into warps
    warps = []
    for i in range(0, len(accumulators), warp_size):
        warp = accumulators[i:i + warp_size]
        warps.append(warp)

    # Reduce within each warp
    warp_results = []
    for warp in warps:
        result = warp_reduce(warp, combine_fn, warp_size)
        warp_results.append(result)

    # Reduce across warp leaders
    if len(warp_results) <= warp_size:
        return warp_reduce(warp_results, combine_fn, warp_size)
    else:
        # Hierarchical reduction for many warps
        while len(warp_results) > 1:
            next_level = []
            for i in range(0, len(warp_results), warp_size):
                batch = warp_results[i:i + warp_size]
                next_level.append(warp_reduce(batch, combine_fn, warp_size))
            warp_results = next_level
        return warp_results[0]
