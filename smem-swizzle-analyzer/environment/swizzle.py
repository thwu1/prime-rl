"""XOR-based shared memory index swizzling for bank conflict avoidance.

For a 2D shared memory tile  T smem[NY][NX]  where
  SWIZZLE_SIZE = NX * sizeof(T),
the swizzle remaps column index x based on row index y so that
column-wise access patterns spread across different banks.

The transformation operates at sizeof_TC-byte chunk granularity.
sizeof_TC controls the trade-off between conflict reduction and
vectorized-load alignment:
  - Smaller sizeof_TC distributes accesses more finely across banks
  - Larger sizeof_TC preserves alignment for wider vector loads
    (e.g., sizeof_TC=16 keeps float4/int4 loads aligned)

Full formula (from the general swizzle derivation):
  i_chunk  = (y * NX + x) * sizeof_T / sizeof_TC
  y_chunk  = i_chunk / (SWIZZLE_SIZE / sizeof_TC)
  x_chunk  = i_chunk % (SWIZZLE_SIZE / sizeof_TC)
  x_chunk_swz = y_chunk ^ x_chunk
  x_swz = x_chunk_swz * sizeof_TC / sizeof_T % NX
         + x % (sizeof_TC / sizeof_T)

Simplified (valid when x < NX, which is always true):
  x_chunk   = x * sizeof_T // sizeof_TC
  y_chunk   = y
  x_chunk_swz = y ^ x_chunk
  elems_per_chunk = sizeof_TC // sizeof_T
  x_swz = (x_chunk_swz * elems_per_chunk) % NX + x % elems_per_chunk
"""


def apply_swizzle(y, x, NX, sizeof_T=4, sizeof_TC=4):
    """Compute the swizzled column index.

    Args:
        y:  row index
        x:  column index (0 <= x < NX)
        NX: number of columns (must be power of 2)
        sizeof_T:  element size in bytes (e.g. 4 for float, 2 for half)
        sizeof_TC: chunk size for XOR in bytes (must be >= sizeof_T,
                   power of 2; larger values preserve wider vector alignment)

    Returns:
        Swizzled column index in [0, NX).
    """
    # TODO: implement the XOR-based swizzle formula described above.
    # Hint for float32 with sizeof_TC==sizeof_T==4, it reduces to
    #   (y ^ x) % NX
    return x


def verify_bijective(NX, NY, sizeof_T=4, sizeof_TC=4):
    """Verify that the swizzle is a bijection on columns for every row.

    For each row y in [0, NY), the mapping x -> apply_swizzle(y, x, ...)
    must produce NX distinct values all within [0, NX).

    Returns:
        True if bijective for all rows, False otherwise.
    """
    # TODO: implement bijectivity check
    return True
