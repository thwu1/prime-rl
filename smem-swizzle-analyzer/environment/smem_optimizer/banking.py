"""Python wrapper around the C shared memory bank conflict library (libsmembank).

The C library implements the core bank-conflict simulation for performance.
This module loads it via ctypes and exposes a Python-friendly interface.
"""

import ctypes
import os

NUM_BANKS = 32
BANK_WIDTH = 4  # bytes

_LIB_SEARCH_PATHS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib", "libsmembank.so"),
    "/app/lib/libsmembank.so",
    "/app/build/libsmembank.so",
]


def _load_lib():
    """Search for and load libsmembank.so from known paths."""
    for path in _LIB_SEARCH_PATHS:
        if os.path.isfile(path):
            lib = ctypes.CDLL(path)
            lib.compute_bank_id.argtypes = [ctypes.c_int]
            lib.compute_bank_id.restype = ctypes.c_int
            lib.count_bank_conflicts.argtypes = [
                ctypes.POINTER(ctypes.c_int),
                ctypes.c_size_t,
            ]
            lib.count_bank_conflicts.restype = ctypes.c_int
            return lib
    raise RuntimeError(
        f"libsmembank.so not found in any of: {_LIB_SEARCH_PATHS}\n"
        "The C library must be built as a shared library. Run: make -C /app build"
    )


_lib = None


def _get_lib():
    global _lib
    if _lib is None:
        _lib = _load_lib()
    return _lib


def compute_bank_id(byte_address):
    """Map a byte address to its shared memory bank index (0..31)."""
    return _get_lib().compute_bank_id(byte_address)


def count_bank_conflicts(byte_addresses):
    """Return conflict severity for a warp access pattern.

    Given a list of byte addresses (one per thread, typically 32),
    returns the number of serialization rounds needed:
      - 0 if no addresses (empty warp)
      - 1 if conflict-free (all threads hit distinct banks)
      - N if the most-loaded bank has N threads hitting it

    Args:
        byte_addresses: list of byte addresses accessed by warp threads

    Returns:
        int: serialization rounds (max threads per bank)
    """
    if not byte_addresses:
        return 0
    arr = (ctypes.c_int * len(byte_addresses))(*byte_addresses)
    return _get_lib().count_bank_conflicts(arr, len(byte_addresses))
