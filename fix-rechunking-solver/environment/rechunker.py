"""
Rechunking plan solver for multi-dimensional chunked array storage.

This module implements algorithms to compute optimal rechunking plans
for multi-dimensional arrays stored in chunked formats (Zarr, TileDB, etc.).
The planner determines how to transform source chunk layouts to target
chunk layouts while respecting memory constraints and minimizing I/O.

"""

import warnings
from math import ceil, floor, gcd, prod
from typing import List, Optional, Sequence, Tuple

import numpy as np


def lcm(a: int, b: int) -> int:
    """Compute the least common multiple of two integers."""
    return abs(a * b) // gcd(a, b)


def consolidate_chunks(
    shape: Sequence[int],
    chunks: Sequence[int],
    itemsize: int,
    max_mem: int,
    chunk_limits: Optional[Sequence[Optional[int]]] = None,
) -> Tuple[int, ...]:
    """Consolidate input chunks up to a certain memory limit.

    Consolidation starts on the highest axis and proceeds toward axis 0.
    For each axis, attempt to set the chunk size to the upper bound
    (shape or limit). If that exceeds memory, fall back to increasing
    the chunk by a factor derived from the remaining headroom.

    Parameters
    ----------
    shape : tuple of int
        Array shape.
    chunks : tuple of int
        Original chunk shape.
    itemsize : int
        Bytes per element.
    max_mem : int
        Maximum chunk memory in bytes.
    chunk_limits : tuple of int or None, optional
        Per-axis upper bound. None means don't consolidate that axis.
        -1 means no limit (use full shape extent).

    Returns
    -------
    tuple of int
        Consolidated chunk shape, guaranteed to produce chunks <= max_mem.
    """
    ndim = len(shape)
    if chunk_limits is None:
        chunk_limits = list(shape)

    chunk_limit_per_axis = {}
    for n_ax, cl in enumerate(chunk_limits):
        if cl is not None:
            if cl == -1:
                chunk_limit_per_axis[n_ax] = shape[n_ax]
            elif chunks[n_ax] <= cl <= shape[n_ax]:
                chunk_limit_per_axis[n_ax] = cl
            elif cl > shape[n_ax]:
                chunk_limit_per_axis[n_ax] = shape[n_ax]
            else:
                raise ValueError(f"Invalid chunk_limits {chunk_limits}.")

    chunk_mem = itemsize * prod(chunks)
    if chunk_mem > max_mem:
        raise ValueError(f"chunk_mem {chunk_mem} > max_mem {max_mem}")
    headroom = max_mem / chunk_mem

    new_chunks = list(chunks)
    axes = sorted(chunk_limit_per_axis.keys())[::-1]
    for n_axis in axes:
        upper_bound = min(shape[n_axis], chunk_limit_per_axis[n_axis])
        new_chunks[n_axis] = upper_bound
        chunk_mem = itemsize * prod(new_chunks)
        upper_bound_headroom = max_mem / chunk_mem
        if upper_bound_headroom > 1:
            headroom = upper_bound_headroom
        else:
            larger_chunk = int(chunks[n_axis] * headroom)
            new_chunks[n_axis] = min(larger_chunk, upper_bound)
            chunk_mem = itemsize * prod(new_chunks)
            headroom = max_mem / chunk_mem

        assert headroom >= 1

    return tuple(new_chunks)


def _calculate_shared_chunks(
    read_chunks: Sequence[int], write_chunks: Sequence[int]
) -> Tuple[int, ...]:
    """Compute the shared intermediate chunks between read and write layouts.

    Intermediate chunks must be compatible with both the source read
    layout and the target write layout — each dimension of the
    intermediate chunk must fit within both the corresponding read
    and write chunk sizes.

    Example:
        read_chunks:         (20, 5)
        write_chunks:        (4, 25)
        shared_chunks:       (4, 5)
    """
    return tuple(
        max(c_read, c_write) for c_read, c_write in zip(read_chunks, write_chunks)
    )


def calculate_stage_chunks(
    read_chunks: Tuple[int, ...],
    write_chunks: Tuple[int, ...],
    stage_count: int = 1,
) -> List[Tuple[int, ...]]:
    """Calculate intermediate chunk sizes for multi-stage rechunking.

    Computes chunk sizes that progressively transform from read layout
    to write layout across multiple stages. The spacing method should
    preserve approximately equal element counts per chunk at each stage.

    Parameters
    ----------
    read_chunks, write_chunks : tuple of int
        Source and target chunk sizes.
    stage_count : int
        Number of stages (pass-throughs). Returns stage_count - 1
        intermediate chunk tuples.

    Returns
    -------
    list of tuple of int
        Intermediate chunk sizes between stages.

    Examples
    --------
    >>> calculate_stage_chunks((1000000, 1), (1, 1000000), 2)
    [(1000, 1000)]
    >>> calculate_stage_chunks((1000000, 1), (1, 1000000), 3)
    [(10000, 100), (100, 10000)]
    """
    approx_stages = np.linspace(read_chunks, write_chunks, num=stage_count + 1)
    return [tuple(floor(c) for c in stage) for stage in approx_stages[1:-1]]


def _count_intermediate_chunks(source_chunk: int, target_chunk: int, size: int) -> int:
    """Count intermediate chunks required for rechunking along one dimension.

    Uses LCM-based partitioning: within each LCM period of source and target
    chunk sizes, boundaries from both chunk grids create splits. For any
    partial remainder beyond complete LCM periods, splits are computed
    from ceiling divisions.

    Parameters
    ----------
    source_chunk, target_chunk : int
        Source and target chunk sizes along this dimension.
    size : int
        Full extent of this dimension.

    Returns
    -------
    int
        Number of intermediate chunks.

    Examples
    --------
    Rechunking size-20 from chunk-5 to chunk-7:
        source: |0 1 2 3 4|5 6 7 8 9|10 11 12 13 14|15 16 17 18 19|
        target: |0 1 2 3 4 5 6|7 8 9 10 11 12 13|14 15 16 17 18 19|
        shared: |0 1 2 3 4|5 6|7 8 9|10 11 12 13|14|15 16 17 18 19|  -> 6 chunks

    >>> _count_intermediate_chunks(5, 7, 20)
    6
    """
    multiple = lcm(source_chunk, target_chunk)
    splits_per_lcm = multiple // source_chunk + multiple // target_chunk
    lcm_count, remainder = divmod(size, multiple)
    if remainder:
        splits_in_remainder = (
            ceil(remainder / source_chunk) + ceil(remainder / target_chunk) - 1
        )
    else:
        splits_in_remainder = 0
    return lcm_count * splits_per_lcm + splits_in_remainder


def calculate_single_stage_io_ops(
    shape: Sequence[int], in_chunks: Sequence[int], out_chunks: Sequence[int]
) -> int:
    """Count the number of read/write operations for a single rechunking stage.

    This is the product of intermediate chunk counts across all dimensions,
    since each combination of per-dimension splits constitutes one I/O op.
    """
    return prod(map(_count_intermediate_chunks, in_chunks, out_chunks, shape))


MAX_STAGES = 100


def multistage_rechunking_plan(
    shape: Sequence[int],
    source_chunks: Sequence[int],
    target_chunks: Sequence[int],
    itemsize: int,
    min_mem: int,
    max_mem: int,
    consolidate_reads: bool = True,
    consolidate_writes: bool = True,
) -> List[Tuple[Tuple[int, ...], Tuple[int, ...], Tuple[int, ...]]]:
    """Compute a rechunking plan that may use multiple split/consolidate steps.

    The algorithm first consolidates write chunks (enlarging target chunks
    up to max_mem), then consolidates read chunks similarly. It then
    iteratively increases the number of stages until the intermediate
    chunk memory is at least min_mem, or until adding stages increases
    I/O operations (diminishing returns).

    Parameters
    ----------
    shape : tuple of int
        Array shape.
    source_chunks, target_chunks : tuple of int
        Source and target chunk sizes.
    itemsize : int
        Bytes per element.
    min_mem : int
        Minimum intermediate chunk memory (bytes). More stages are added
        until intermediate chunks are at least this large.
    max_mem : int
        Maximum chunk memory (bytes). Consolidated chunks must not exceed this.
    consolidate_reads, consolidate_writes : bool
        Whether to consolidate read/write chunks up to max_mem.

    Returns
    -------
    list of (pre_chunks, int_chunks, post_chunks)
        Each tuple represents one stage. pre_chunks are read, int_chunks
        are intermediate (shared), post_chunks are written.
    """
    ndim = len(shape)
    if len(source_chunks) != ndim:
        raise ValueError(f"source_chunks must have length {ndim}")
    if len(target_chunks) != ndim:
        raise ValueError(f"target_chunks must have length {ndim}")

    source_chunk_mem = itemsize * prod(source_chunks)
    target_chunk_mem = itemsize * prod(target_chunks)

    if source_chunk_mem > max_mem:
        raise ValueError("Source chunk memory exceeds max_mem")
    if target_chunk_mem > max_mem:
        raise ValueError("Target chunk memory exceeds max_mem")
    if max_mem < min_mem:
        raise ValueError("max_mem cannot be smaller than min_mem")

    if consolidate_writes:
        write_chunks = consolidate_chunks(shape, target_chunks, itemsize, max_mem)
    else:
        write_chunks = tuple(target_chunks)

    if consolidate_reads:
        read_chunk_limits: List[Optional[int]] = []
        for sc, wc in zip(source_chunks, write_chunks):
            limit: Optional[int]
            if wc > sc:
                limit = wc
            else:
                limit = None
            read_chunk_limits.append(limit)
        read_chunks = consolidate_chunks(
            shape, source_chunks, itemsize, max_mem, read_chunk_limits
        )
    else:
        read_chunks = tuple(source_chunks)

    prev_io_ops: Optional[float] = None
    prev_plan = None

    for stage_count in range(1, MAX_STAGES):
        stage_chunks = calculate_stage_chunks(read_chunks, write_chunks, stage_count)
        pre_chunks = [read_chunks] + stage_chunks
        post_chunks = stage_chunks + [write_chunks]

        int_chunks = [
            _calculate_shared_chunks(pre, post)
            for pre, post in zip(pre_chunks, post_chunks)
        ]
        plan = list(zip(pre_chunks, int_chunks, post_chunks))

        int_mem = min(itemsize * prod(chunks) for chunks in int_chunks)
        if int_mem >= min_mem:
            return plan

        io_ops = sum(
            calculate_single_stage_io_ops(shape, pre, post)
            for pre, post in zip(pre_chunks, post_chunks)
        )
        if prev_io_ops is not None and io_ops > prev_io_ops:
            assert prev_plan is not None
            return prev_plan

        prev_io_ops = io_ops
        prev_plan = plan

    raise RuntimeError("Failed to find feasible rechunking plan")


def rechunking_plan(
    shape: Sequence[int],
    source_chunks: Sequence[int],
    target_chunks: Sequence[int],
    itemsize: int,
    max_mem: int,
    consolidate_reads: bool = True,
    consolidate_writes: bool = True,
) -> Tuple[Tuple[int, ...], Tuple[int, ...], Tuple[int, ...]]:
    """Compute a single-stage rechunking plan.

    Convenience wrapper around multistage_rechunking_plan that sets
    min_mem=itemsize (minimal constraint) and expects exactly one stage.
    """
    (stage,) = multistage_rechunking_plan(
        shape,
        source_chunks,
        target_chunks,
        itemsize=itemsize,
        min_mem=itemsize,
        max_mem=max_mem,
        consolidate_writes=consolidate_writes,
        consolidate_reads=consolidate_reads,
    )
    return stage
