#!/usr/bin/env python3
"""
Canonical ABI layout engine for WebAssembly Component Model types.

Skeleton providing API signatures, primitive type constants, and basic utility
functions. All public functions raising NotImplementedError must be implemented
per the canonical ABI specification:
https://github.com/WebAssembly/component-model/blob/main/design/mvp/CanonicalABI.md

"""

import json
import struct
import math


# Canonical ABI primitive type sizes and alignments: (size, alignment)
PRIMITIVES = {
    "bool": (1, 1),
    "u8": (1, 1), "s8": (1, 1),
    "u16": (2, 2), "s16": (2, 2),
    "u32": (4, 4), "s32": (4, 4),
    "u64": (8, 8), "s64": (8, 8),
    "f32": (4, 4), "f64": (8, 8),
    "char": (4, 4),
    "string": (8, 4),
}

# Flat core wasm valtypes for each primitive type
PRIMITIVE_FLAT = {
    "bool": ["i32"],
    "u8": ["i32"], "s8": ["i32"],
    "u16": ["i32"], "s16": ["i32"],
    "u32": ["i32"], "s32": ["i32"],
    "u64": ["i64"], "s64": ["i64"],
    "f32": ["f32"], "f64": ["f64"],
    "char": ["i32"],
    "string": ["i32", "i32"],
}

MAX_FLAT_PARAMS = 16
MAX_FLAT_RESULTS = 1


def load_types(path):
    """Load type definitions from a JSON file."""
    with open(path) as f:
        return json.load(f)


def _resolve(types, type_ref):
    """Resolve a type reference to a type definition dict.

    - If type_ref is a primitive name string, returns {"kind": "primitive", "name": ...}
    - If type_ref is a named type in types dict, returns that type's definition
    - If type_ref is already a dict (inline type), returns it as-is
    - None returns None
    """
    if type_ref is None:
        return None
    if isinstance(type_ref, str):
        if type_ref in PRIMITIVES:
            return {"kind": "primitive", "name": type_ref}
        if type_ref in types:
            return types[type_ref]
        raise ValueError(f"Unknown type: {type_ref}")
    return type_ref


def _align_to(ptr, alignment):
    """Round ptr up to the next multiple of alignment."""
    if alignment <= 0:
        return ptr
    return ((ptr + alignment - 1) // alignment) * alignment


def _discriminant_size(n):
    """Size in bytes of the discriminant for a variant with n cases.

    Per spec: discriminant is the smallest of {1, 2, 4} bytes that
    can represent all case indices 0..n-1.
    """
    if n <= 1:
        return 1
    bits = (n - 1).bit_length()
    byte_count = (bits + 7) // 8
    if byte_count <= 1:
        return 1
    elif byte_count <= 2:
        return 2
    else:
        return 4


def _num_i32_flags(n):
    """Number of u32 words needed for n flags."""
    return (n + 31) // 32


# ---------------------------------------------------------------------------
# Core API — implement all of the functions below
# ---------------------------------------------------------------------------

def size_of(types, type_ref):
    """Return the canonical ABI size of a type in bytes.

    Must handle: primitives, records, variants, flags, lists,
    and sugar types (tuple, enum, option, result).
    """
    raise NotImplementedError("size_of")


def align_of(types, type_ref):
    """Return the canonical ABI alignment of a type.

    Must handle all type kinds.
    """
    raise NotImplementedError("align_of")


def field_offsets(types, type_ref):
    """Return field offsets for a record (or tuple) type.

    Keys are field names (or stringified indices "0","1",... for tuples).
    Values are byte offsets from the start of the record.
    """
    raise NotImplementedError("field_offsets")


def flatten_type(types, type_ref):
    """Return the flat representation as a list of core wasm valtype strings
    (each one of "i32", "i64", "f32", "f64").

    Records concatenate their fields' flat representations.
    Variants prepend a discriminant "i32" then join payload valtypes at
    corresponding positions across all cases.
    """
    raise NotImplementedError("flatten_type")


def exceeds_max_flat_params(types, type_ref):
    """Return True if the flat representation exceeds MAX_FLAT_PARAMS (16)."""
    raise NotImplementedError("exceeds_max_flat_params")


def lift(types, type_ref, buffer, offset=0):
    """Lift a value from a byte buffer at the given offset.

    Return types vary by kind:
    - Records: dict {field_name: value}
    - Tuples: Python tuple of values
    - Enums: case name string (NOT a tuple)
    - Variants/options/results: (case_name, payload_value) tuple
    - Flags: integer bitmask
    - Bool: any nonzero byte is True
    - Char: single-character string
    - String/list: (ptr, length) tuple of integers
    - Other primitives: native Python int or float
    """
    raise NotImplementedError("lift")


def lower(types, type_ref, value):
    """Lower a value to a byte buffer of exactly size_of(type) bytes.

    Input value format matches lift() output for the same type.
    Unused padding/payload bytes must be zero.
    """
    raise NotImplementedError("lower")


def flatten_functype(types, params, results):
    """Compute the core wasm function type for a component-model function.

    Concatenates flat representations of all parameter/result types.
    If total flat params exceed MAX_FLAT_PARAMS, replace with ["i32"].
    If total flat results exceed MAX_FLAT_RESULTS, replace with ["i32"].

    Args:
        types: Type definitions dict.
        params: List of component-level parameter type references.
        results: List of component-level result type references.

    Returns:
        Tuple (core_params, core_results) of valtype string lists.
    """
    raise NotImplementedError("flatten_functype")


def store_list(types, element_type, values):
    """Serialize a list of component-level values into a contiguous byte buffer
    following canonical ABI list storage layout.

    Returns empty bytes for an empty list.
    """
    raise NotImplementedError("store_list")


def load_list(types, element_type, buffer, count):
    """Deserialize component-level values from a contiguous byte buffer
    following canonical ABI list storage layout.

    Returns empty list for count=0.
    """
    raise NotImplementedError("load_list")
