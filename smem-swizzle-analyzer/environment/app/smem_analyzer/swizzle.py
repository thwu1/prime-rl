"""XOR-based shared memory index swizzling.

Swizzling rearranges the column index mapping in shared memory to avoid
bank conflicts without wasting memory (unlike padding).

For a shared memory array T smem[NY][NX] where SWIZZLE_SIZE = NX * sizeof(T),
the swizzle transforms column index x based on row index y.

The core idea: divide the row into sizeof(TC)-byte chunks, compute chunk
indices, XOR the y-chunk with the x-chunk, then convert back to element
indices. This redistributes accesses across banks when threads read from
the same column but different rows.

Formula:
    i_chunk = (y * NX + x) * sizeof(T) / sizeof(TC)
    y_chunk = i_chunk / (SWIZZLE_SIZE / sizeof(TC))
    x_chunk = i_chunk % (SWIZZLE_SIZE / sizeof(TC))
    x_chunk_swz = y_chunk ^ x_chunk
    x_swz = x_chunk_swz * sizeof(TC) / sizeof(T) % NX + x % (sizeof(TC) / sizeof(T))

Simplified (when x < NX):
    x_chunk = x * sizeof(T) / sizeof(TC)
    y_chunk = y
    x_chunk_swz = y ^ x_chunk
    x_swz = x_chunk_swz * (sizeof(TC) / sizeof(T)) % NX + x % (sizeof(TC) / sizeof(T))
"""


def apply_swizzle(y, x, NX, sizeof_T=4, sizeof_TC=4):
    """Compute swizzled column index.

    Given array T smem[NY][NX], transforms column index x based on
    row index y to avoid bank conflicts when reading columns.

    Args:
        y: Row index
        x: Column index (must be in range [0, NX))
        NX: Number of columns in the shared memory array (must be power of 2)
        sizeof_T: Size of element type in bytes (e.g., 4 for float)
        sizeof_TC: Size of chunk for XOR operation in bytes (typically 4)

    Returns:
        Swizzled column index x_swz in range [0, NX)
    """
    # TODO: Implement the XOR-based swizzling formula.
    # The formula is documented in the module docstring above.
    # For float (sizeof_T == sizeof_TC == 4), it simplifies to:
    #   x_swz = (y ^ x) % NX
    # The general case must handle sizeof_T != sizeof_TC.
    return x


def verify_bijective(NX, NY, sizeof_T=4, sizeof_TC=4):
    """Verify that the swizzle mapping is bijective for given dimensions.

    For each row y, the swizzle must map the set {0, 1, ..., NX-1} to
    a permutation of {0, 1, ..., NX-1}. If the swizzle is not bijective,
    data would be lost or overwritten during the index remapping.

    Args:
        NX: Number of columns (must be power of 2)
        NY: Number of rows to check
        sizeof_T: Element size in bytes
        sizeof_TC: Chunk size for XOR in bytes

    Returns:
        True if the mapping is bijective for all rows in [0, NY)
    """
    # TODO: Implement bijectivity verification.
    # For each row y in range(NY), check that apply_swizzle maps
    # {0, 1, ..., NX-1} to NX distinct values all within [0, NX).
    return True
