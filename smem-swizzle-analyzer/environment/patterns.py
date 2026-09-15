"""Shared memory access pattern generators for bank conflict analysis.

These functions generate lists of byte addresses representing the shared
memory access pattern of a single warp (32 threads) during one access step.

For a shared memory array T smem[NY][NX]:
  - Element at [row][col] has byte address: (row * NX + col) * sizeof(T)
  - Column access: all threads read the same column, different rows
  - Row access: all threads read the same row, different columns
"""


DTYPE_SIZES = {
    "float32": 4,
    "float64": 8,
    "float16": 2,
}


def generate_column_addresses(NX, NY, col, sizeof_T):
    """Generate byte addresses for column access pattern.

    32 warp threads each read from a different row of the same column.
    Thread t reads smem[t % NY][col].

    byte_address = (row * NX + col) * sizeof_T

    Args:
        NX: Number of columns in shared memory array
        NY: Number of rows in shared memory array
        col: Column index being accessed by all threads
        sizeof_T: Size of each element in bytes

    Returns:
        List of 32 byte addresses (one per warp thread)
    """
    addresses = []
    for t in range(32):
        row = t % NY
        byte_addr = (row * NY + col) * sizeof_T
        addresses.append(byte_addr)
    return addresses


def generate_row_addresses(NX, NY, row, sizeof_T):
    """Generate byte addresses for row access pattern.

    32 warp threads each read from a different column of the same row.
    Thread t reads smem[row][t % NX].

    Args:
        NX: Number of columns in shared memory array
        NY: Number of rows in shared memory array
        row: Row index being accessed by all threads
        sizeof_T: Size of each element in bytes

    Returns:
        List of 32 byte addresses (one per warp thread)
    """
    raise NotImplementedError("Row access pattern generation not yet implemented")


def generate_column_addresses_swizzled(NX, NY, col, sizeof_T, swizzle_fn):
    """Generate byte addresses for swizzled column access pattern.

    Same as column access, but the column index is remapped through
    swizzle_fn before computing the byte address.
    Thread t reads smem[t % NY][swizzle_fn(t % NY, col)].

    Args:
        NX: Number of columns
        NY: Number of rows
        col: Original (logical) column index
        sizeof_T: Element size in bytes
        swizzle_fn: Function(y, x) -> swizzled_x

    Returns:
        List of 32 byte addresses
    """
    addresses = []
    for t in range(32):
        row = t % NY
        swizzled_col = swizzle_fn(row, col)
        byte_addr = (row * NX + swizzled_col) * sizeof_T
        addresses.append(byte_addr)
    return addresses


def generate_row_addresses_swizzled(NX, NY, row, sizeof_T, swizzle_fn):
    """Generate byte addresses for swizzled row access pattern.

    Thread t reads smem[row][swizzle_fn(row, t % NX)].

    Args:
        NX: Number of columns
        NY: Number of rows
        row: Row index being accessed
        sizeof_T: Element size in bytes
        swizzle_fn: Function(y, x) -> swizzled_x

    Returns:
        List of 32 byte addresses
    """
    raise NotImplementedError(
        "Swizzled row access pattern generation not yet implemented"
    )
