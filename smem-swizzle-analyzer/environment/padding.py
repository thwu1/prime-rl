"""Padding-based shared memory bank conflict avoidance.

Adding extra columns (padding) to a shared memory tile changes the
inter-row stride in bytes, which can break bank-aliasing patterns
that cause column-access conflicts.

For T smem[NY][NX], column access to col c has byte address:
  addr(row) = (row * NX + c) * sizeof_T
The row-to-row stride is NX * sizeof_T bytes.  When this stride is
a multiple of 32 * bank_width = 128 bytes, every row maps col c to
the same bank -> worst-case conflict.

Padding adds 'pad' extra (unused) columns, making the stride
(NX + pad) * sizeof_T.  Choosing pad so that the stride is NOT
a multiple of 128 spreads accesses across banks.

Alignment constraint for vectorized loads:
  (NX + pad) must be divisible by vectorize_width so that
  int4/float4/etc. loads remain aligned at row boundaries.

Memory overhead:
  pad * NY * sizeof_T bytes wasted per tile.
"""

DTYPE_SIZES = {"float32": 4, "float64": 8, "float16": 2}


def find_optimal_padding(NX, NY, sizeof_T, vectorize_width, access):
    """Find the minimum padding that minimizes bank conflicts.

    For column access: searches pad values in ascending order, subject
    to the vectorize_width alignment constraint, and returns the
    smallest pad that achieves the minimum possible conflict count.

    For row access: padding does not change within-row addresses,
    so the baseline conflict count is returned with pad=0.

    Args:
        NX: number of columns in the tile
        NY: number of rows in the tile
        sizeof_T: element size in bytes
        vectorize_width: elements per vectorized load (1 = scalar)
        access: "column" or "row"

    Returns:
        (pad_amount, conflict_count, overhead_bytes)
    """
    raise NotImplementedError("Padding strategy not yet implemented")
