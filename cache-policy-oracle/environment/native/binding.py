"""Python ctypes wrapper for the native LRU cache simulator."""

import ctypes
import os

_lib = None


class CSimBlock(ctypes.Structure):
    _fields_ = [
        ("tag", ctypes.c_uint64),
        ("last_access", ctypes.c_uint64),
        ("valid", ctypes.c_int),
    ]


class CSimCache(ctypes.Structure):
    _fields_ = [
        ("num_sets", ctypes.c_int),
        ("num_ways", ctypes.c_int),
        ("block_size", ctypes.c_int),
        ("blocks", ctypes.POINTER(CSimBlock)),
        ("clock", ctypes.c_uint64),
        ("hits", ctypes.c_uint64),
        ("misses", ctypes.c_uint64),
    ]


def load_library():
    """Load the native cache simulator shared library."""
    global _lib
    if _lib is not None:
        return _lib
    lib_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "cachesim.a")
    _lib = ctypes.CDLL(lib_path)

    _lib.csim_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
    _lib.csim_create.restype = ctypes.POINTER(CSimCache)

    _lib.csim_access.argtypes = [ctypes.POINTER(CSimCache), ctypes.c_uint64]
    _lib.csim_access.restype = ctypes.c_int

    _lib.csim_destroy.argtypes = [ctypes.POINTER(CSimCache)]
    _lib.csim_destroy.restype = None

    return _lib


def simulate_lru_native(accesses, num_sets, num_ways, block_size):
    """Run LRU cache simulation using the native C engine.

    Args:
        accesses: list of (pc, addr, access_type) tuples
        num_sets, num_ways, block_size: cache configuration

    Returns:
        (hits, misses) tuple
    """
    lib = load_library()
    cache = lib.csim_create(num_sets, num_ways, block_size)

    for pc, addr, atype in accesses:
        lib.csim_access(cache, pc)

    hits = cache.contents.hits
    misses = cache.contents.misses

    lib.csim_destroy(cache)
    return hits, misses
