"""Python wrapper around the BitPool C library (libbitpool.so)."""

import ctypes
import os

_LIB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "libbitpool.so")
_lib = ctypes.CDLL(_LIB_PATH)

_lib.bitpool_create.argtypes = [ctypes.c_uint64]
_lib.bitpool_create.restype = ctypes.c_void_p
_lib.bitpool_free.argtypes = [ctypes.c_void_p]
_lib.bitpool_free.restype = None
_lib.bitpool_get_bit.argtypes = [ctypes.c_void_p]
_lib.bitpool_get_bit.restype = ctypes.c_int
_lib.bitpool_bits_used.argtypes = [ctypes.c_void_p]
_lib.bitpool_bits_used.restype = ctypes.c_int
_lib.bitpool_reset.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
_lib.bitpool_reset.restype = None


class BitSource:
    """Provides random bits from the C-based BitPool PRNG.

    Each instance maintains independent state, so multiple BitSource
    objects with different seeds produce independent bit streams.
    """

    def __init__(self, seed=42):
        self._handle = _lib.bitpool_create(ctypes.c_uint64(seed))
        if not self._handle:
            raise MemoryError("Failed to allocate bitpool")

    def get_bit(self):
        """Return the next random bit (0 or 1)."""
        return _lib.bitpool_get_bit(self._handle)

    @property
    def count(self):
        """Total number of bits consumed so far."""
        return _lib.bitpool_bits_used(self._handle)

    def __del__(self):
        if hasattr(self, "_handle") and self._handle:
            _lib.bitpool_free(self._handle)
            self._handle = None
