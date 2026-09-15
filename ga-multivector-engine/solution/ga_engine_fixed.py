"""Geometric algebra computation engine — FIXED VERSION.

Hybrid Rust/Python implementation. Core operations (mask tables, reorder sign,
product kernel) are in a compiled Rust shared library; higher-level operations
(reverse, grade projection, sandwich, grade involution) are in Python.
"""

import ctypes
import os

# --- Load Rust library ---

_lib_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "libga", "target", "release", "libga.so"
)
_lib = ctypes.CDLL(_lib_path)

# --- FFI type declarations ---

_lib.ga_mask_tables.argtypes = [
    ctypes.c_uint32,
    ctypes.POINTER(ctypes.c_uint32),
    ctypes.POINTER(ctypes.c_uint32),
]
_lib.ga_mask_tables.restype = None

_lib.ga_blade_grade.argtypes = [ctypes.c_uint32]
_lib.ga_blade_grade.restype = ctypes.c_uint32

_lib.ga_reorder_sign.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
_lib.ga_reorder_sign.restype = ctypes.c_int32

_lib.ga_metric.argtypes = [
    ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32,
    ctypes.c_uint32, ctypes.c_uint32,
]
_lib.ga_metric.restype = ctypes.c_int32

_lib.ga_product_core.argtypes = [
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double),
    ctypes.POINTER(ctypes.c_double),
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_uint32,
    ctypes.c_uint32,
]
_lib.ga_product_core.restype = None


# --- Flavor encoding ---

def _parse_flavor(flavor):
    """Convert a Python flavor specification to (flavor_id, p, q, r) for Rust."""
    if flavor == "VGA":
        return (0, 0, 0, 0)
    if flavor == "PGA":
        return (1, 0, 0, 0)
    if isinstance(flavor, (tuple, list)) and flavor[0] == "Cl":
        _, p, q, r = flavor
        # FIX: correct parameter order (was swapped)
        return (2, p, q, r)
    raise ValueError(f"Unknown flavor: {flavor}")


# --- Public API ---

def mask_tables(dims):
    """Compute blade-ordering mask tables for *dims* dimensions."""
    n = 1 << dims
    mt = (ctypes.c_uint32 * n)()
    inv = (ctypes.c_uint32 * n)()
    _lib.ga_mask_tables(dims, mt, inv)
    return list(mt), list(inv)


def blade_grade(bitmask):
    """Return the grade (popcount) of a basis blade bitmask."""
    return _lib.ga_blade_grade(bitmask)


def reorder_sign(mask_a, mask_b):
    """Sign factor from reordering the product of two basis blades."""
    return _lib.ga_reorder_sign(mask_a, mask_b)


def metric(flavor, bit_index):
    """Metric value (square of basis vector) for a given flavor and index."""
    flav, p, q, r = _parse_flavor(flavor)
    return _lib.ga_metric(flav, p, q, r, bit_index)


# --- Product functions ---

def _call_product(mv_a, mv_b, dims, flavor, mode):
    """Call the Rust product kernel with the given grade-filter mode."""
    n = 1 << dims
    a_arr = (ctypes.c_double * n)()
    b_arr = (ctypes.c_double * n)()
    result = (ctypes.c_double * n)()

    for i in range(min(len(mv_a), n)):
        a_arr[i] = float(mv_a[i])
    for i in range(min(len(mv_b), n)):
        b_arr[i] = float(mv_b[i])

    flav, p, q, r = _parse_flavor(flavor)
    _lib.ga_product_core(a_arr, b_arr, result, n, dims, flav, p, q, r, mode)

    return [result[i] for i in range(n)]


def geo_product(mv_a, mv_b, dims, flavor="VGA"):
    """Geometric product of two multivectors."""
    return _call_product(mv_a, mv_b, dims, flavor, 0)


def outer_product(mv_a, mv_b, dims, flavor="VGA"):
    """Outer (wedge) product of two multivectors."""
    return _call_product(mv_a, mv_b, dims, flavor, 1)


def inner_product(mv_a, mv_b, dims, flavor="VGA"):
    """Hestenes inner product of two multivectors."""
    # FIX: mode 2 for inner product (was mode 1 = outer)
    return _call_product(mv_a, mv_b, dims, flavor, 2)


# --- Higher-level operations ---

def reverse_mv(mv, dims):
    """Reverse of a multivector (grade-dependent sign flip)."""
    n = 1 << dims
    mt, _ = mask_tables(dims)
    result = [0.0] * n
    for i in range(min(len(mv), n)):
        k = blade_grade(mt[i])
        # FIX: exponent is k*(k-1)/2, not k*(k+1)/2
        sign = (-1) ** (k * (k - 1) // 2)
        result[i] = sign * mv[i]
    return result


def grade_project(mv, grade, dims):
    """Extract only the components of a specific grade."""
    n = 1 << dims
    mt, _ = mask_tables(dims)
    result = [0.0] * n
    for i in range(min(len(mv), n)):
        if blade_grade(mt[i]) == grade:
            result[i] = mv[i]
    return result


def sandwich(R, x, dims, flavor="VGA"):
    """Sandwich product: R * x * reverse(R)."""
    R_rev = reverse_mv(R, dims)
    temp = geo_product(R, x, dims, flavor)
    return geo_product(temp, R_rev, dims, flavor)


def grade_involution(mv, dims):
    """Grade involution: multiply each grade-k component by (-1)^k."""
    n = 1 << dims
    mt, _ = mask_tables(dims)
    result = [0.0] * n
    for i in range(min(len(mv), n)):
        k = blade_grade(mt[i])
        sign = (-1) ** k
        result[i] = sign * mv[i]
    return result
