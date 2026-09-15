#!/usr/bin/env python3
"""
Canonical ABI layout engine for WebAssembly Component Model types.

Implements size/alignment computation, flat representation, and lift/lower
operations per the canonical ABI specification:
https://github.com/WebAssembly/component-model/blob/main/design/mvp/CanonicalABI.md

"""

import json
import struct
import math


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
    """Resolve a type reference to a type definition dict."""
    if type_ref is None:
        return None
    if isinstance(type_ref, str):
        if type_ref in PRIMITIVES:
            return {"kind": "primitive", "name": type_ref}
        if type_ref in types:
            return types[type_ref]
        raise ValueError(f"Unknown type: {type_ref}")
    return type_ref


def _despecialize(types, type_def):
    """Despecialize tuple/enum/option/result into record/variant."""
    kind = type_def.get("kind")
    if kind == "tuple":
        fields = [[str(i), t] for i, t in enumerate(type_def["types"])]
        return {"kind": "record", "fields": fields}
    elif kind == "enum":
        cases = [[label, None] for label in type_def["labels"]]
        return {"kind": "variant", "cases": cases}
    elif kind == "option":
        return {"kind": "variant", "cases": [["none", None], ["some", type_def["type"]]]}
    elif kind == "result":
        ok_type = type_def.get("ok")
        err_type = type_def.get("error")
        return {"kind": "variant", "cases": [["ok", ok_type], ["error", err_type]]}
    return type_def


def _align_to(ptr, alignment):
    """Round ptr up to the next multiple of alignment."""
    if alignment <= 0:
        return ptr
    return ((ptr + alignment - 1) // alignment) * alignment


def _discriminant_size(n):
    """Size in bytes of the discriminant for a variant with n cases."""
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


def _max_case_info(types, cases):
    """Return (max_payload_size, max_payload_align) across variant cases."""
    s = 0
    a = 1
    for _, case_type in cases:
        if case_type is not None:
            s = max(s, size_of(types, case_type))
            a = max(a, align_of(types, case_type))
    return s, a


def _join(a, b):
    """Join two flat valtypes per the canonical ABI."""
    if a == b:
        return a
    if (a == "i32" and b == "f32") or (a == "f32" and b == "i32"):
        return "i32"
    return "i64"


def size_of(types, type_ref):
    """Return the canonical ABI size of a type in bytes."""
    if isinstance(type_ref, str) and type_ref in PRIMITIVES:
        return PRIMITIVES[type_ref][0]

    type_def = _resolve(types, type_ref)
    despec = _despecialize(types, type_def)
    kind = despec["kind"]

    if kind == "primitive":
        return PRIMITIVES[despec["name"]][0]
    elif kind == "record":
        s = 0
        for _, ft in despec["fields"]:
            fa = align_of(types, ft)
            s = _align_to(s, fa) + size_of(types, ft)
        return _align_to(s, align_of(types, type_ref))
    elif kind == "variant":
        cases = despec["cases"]
        n = len(cases)
        disc = _discriminant_size(n)
        s, a = _max_case_info(types, cases)
        total = _align_to(disc, a) + s
        return _align_to(total, align_of(types, type_ref))
    elif kind == "flags":
        labels = despec.get("labels", type_def.get("labels", []))
        n = len(labels)
        if n == 0:
            return 0
        if n <= 8:
            return 1
        if n <= 16:
            return 2
        return 4 * _num_i32_flags(n)
    elif kind == "list":
        return 8

    raise ValueError(f"Unknown kind: {kind}")


def align_of(types, type_ref):
    """Return the canonical ABI alignment of a type."""
    if isinstance(type_ref, str) and type_ref in PRIMITIVES:
        return PRIMITIVES[type_ref][1]

    type_def = _resolve(types, type_ref)
    despec = _despecialize(types, type_def)
    kind = despec["kind"]

    if kind == "primitive":
        return PRIMITIVES[despec["name"]][1]
    elif kind == "record":
        a = 1
        for _, ft in despec["fields"]:
            a = max(a, align_of(types, ft))
        return a
    elif kind == "variant":
        cases = despec["cases"]
        n = len(cases)
        disc_a = _discriminant_size(n)
        _, case_a = _max_case_info(types, cases)
        return max(disc_a, case_a)
    elif kind == "flags":
        labels = despec.get("labels", type_def.get("labels", []))
        n = len(labels)
        if n <= 8:
            return 1
        if n <= 16:
            return 2
        return 4
    elif kind == "list":
        return 4

    raise ValueError(f"Unknown kind: {kind}")


def field_offsets(types, type_ref):
    """Return field offsets for a record (or tuple) type.
    Keys are field names (str indices for tuples), values are byte offsets."""
    type_def = _resolve(types, type_ref)
    despec = _despecialize(types, type_def)

    if despec["kind"] != "record":
        raise ValueError("field_offsets only works on record/tuple types")

    offsets = {}
    s = 0
    for field_name, ft in despec["fields"]:
        fa = align_of(types, ft)
        s = _align_to(s, fa)
        offsets[field_name] = s
        s += size_of(types, ft)
    return offsets


def flatten_type(types, type_ref):
    """Return the flat representation as a list of core wasm valtype strings."""
    if isinstance(type_ref, str) and type_ref in PRIMITIVE_FLAT:
        return list(PRIMITIVE_FLAT[type_ref])

    type_def = _resolve(types, type_ref)
    despec = _despecialize(types, type_def)
    kind = despec["kind"]

    if kind == "primitive":
        return list(PRIMITIVE_FLAT[despec["name"]])
    elif kind == "record":
        result = []
        for _, ft in despec["fields"]:
            result.extend(flatten_type(types, ft))
        return result
    elif kind == "variant":
        cases = despec["cases"]
        n = len(cases)
        disc_flat = ["i32"]

        payloads = []
        for _, ct in cases:
            if ct is not None:
                payloads.append(flatten_type(types, ct))
            else:
                payloads.append([])

        max_len = max((len(p) for p in payloads), default=0)
        joined = []
        for i in range(max_len):
            types_at_i = [p[i] for p in payloads if i < len(p)]
            r = types_at_i[0]
            for t in types_at_i[1:]:
                r = _join(r, t)
            joined.append(r)

        return disc_flat + joined
    elif kind == "flags":
        labels = despec.get("labels", type_def.get("labels", []))
        n = len(labels)
        return ["i32"] * _num_i32_flags(n)
    elif kind == "list":
        return ["i32", "i32"]

    raise ValueError(f"Unknown kind: {kind}")


def exceeds_max_flat_params(types, type_ref):
    """Return True if the flat representation exceeds MAX_FLAT_PARAMS (16)."""
    flat = flatten_type(types, type_ref)
    return len(flat) > MAX_FLAT_PARAMS


def lift(types, type_ref, buffer, offset=0):
    """Lift a value from a byte buffer at the given offset."""
    if isinstance(type_ref, str) and type_ref in PRIMITIVES:
        return _lift_primitive(type_ref, buffer, offset)

    type_def = _resolve(types, type_ref)
    orig_kind = type_def.get("kind")
    despec = _despecialize(types, type_def)
    kind = despec["kind"]

    if kind == "primitive":
        return _lift_primitive(despec["name"], buffer, offset)
    elif kind == "record":
        result = {}
        off = offset
        for field_name, ft in despec["fields"]:
            fa = align_of(types, ft)
            off = _align_to(off, fa)
            val = lift(types, ft, buffer, off)
            result[field_name] = val
            off += size_of(types, ft)
        if orig_kind == "tuple":
            return tuple(result[str(i)] for i in range(len(despec["fields"])))
        return result
    elif kind == "variant":
        cases = despec["cases"]
        n = len(cases)
        disc_sz = _discriminant_size(n)
        if disc_sz == 1:
            disc_val = struct.unpack_from('<B', buffer, offset)[0]
        elif disc_sz == 2:
            disc_val = struct.unpack_from('<H', buffer, offset)[0]
        else:
            disc_val = struct.unpack_from('<I', buffer, offset)[0]

        _, a = _max_case_info(types, cases)
        payload_offset = offset + _align_to(disc_sz, a)

        case_name, case_type = cases[disc_val]
        if case_type is not None:
            payload_val = lift(types, case_type, buffer, payload_offset)
        else:
            payload_val = None

        if orig_kind == "enum":
            return case_name
        else:
            return (case_name, payload_val)
    elif kind == "flags":
        labels = type_def.get("labels", [])
        n = len(labels)
        if n == 0:
            return 0
        if n <= 8:
            return struct.unpack_from('<B', buffer, offset)[0]
        if n <= 16:
            return struct.unpack_from('<H', buffer, offset)[0]
        num_words = _num_i32_flags(n)
        value = 0
        for i in range(num_words):
            word = struct.unpack_from('<I', buffer, offset + i * 4)[0]
            value |= (word << (i * 32))
        return value
    elif kind == "list":
        ptr = struct.unpack_from('<I', buffer, offset)[0]
        length = struct.unpack_from('<I', buffer, offset + 4)[0]
        return (ptr, length)

    raise ValueError(f"Unknown kind: {kind}")


def _lift_primitive(name, buffer, offset):
    """Lift a primitive value from a byte buffer."""
    fmt_map = {
        "bool": '<B', "u8": '<B', "s8": '<b',
        "u16": '<H', "s16": '<h',
        "u32": '<I', "s32": '<i',
        "u64": '<Q', "s64": '<q',
        "f32": '<f', "f64": '<d',
        "char": '<I',
    }
    if name == "bool":
        return struct.unpack_from('<B', buffer, offset)[0] != 0
    elif name == "char":
        cp = struct.unpack_from('<I', buffer, offset)[0]
        return chr(cp)
    elif name == "string":
        ptr = struct.unpack_from('<I', buffer, offset)[0]
        length = struct.unpack_from('<I', buffer, offset + 4)[0]
        return (ptr, length)
    elif name in fmt_map:
        return struct.unpack_from(fmt_map[name], buffer, offset)[0]
    raise ValueError(f"Unknown primitive: {name}")


def lower(types, type_ref, value):
    """Lower a value to a byte buffer of size_of(type) bytes."""
    total_size = size_of(types, type_ref)
    buf = bytearray(total_size)
    _lower_into(types, type_ref, value, buf, 0)
    return bytes(buf)


def _lower_into(types, type_ref, value, buf, offset):
    """Lower a value into a mutable buffer at the given offset."""
    if isinstance(type_ref, str) and type_ref in PRIMITIVES:
        _lower_primitive(type_ref, value, buf, offset)
        return

    type_def = _resolve(types, type_ref)
    orig_kind = type_def.get("kind")
    despec = _despecialize(types, type_def)
    kind = despec["kind"]

    if kind == "primitive":
        _lower_primitive(despec["name"], value, buf, offset)
    elif kind == "record":
        if orig_kind == "tuple":
            off = offset
            for i, (_, ft) in enumerate(despec["fields"]):
                fa = align_of(types, ft)
                off = _align_to(off, fa)
                _lower_into(types, ft, value[i], buf, off)
                off += size_of(types, ft)
        else:
            off = offset
            for field_name, ft in despec["fields"]:
                fa = align_of(types, ft)
                off = _align_to(off, fa)
                _lower_into(types, ft, value[field_name], buf, off)
                off += size_of(types, ft)
    elif kind == "variant":
        cases = despec["cases"]
        n = len(cases)
        disc_sz = _discriminant_size(n)
        _, a = _max_case_info(types, cases)
        payload_offset = offset + _align_to(disc_sz, a)

        if orig_kind == "enum":
            disc_val = next(i for i, (name, _) in enumerate(cases) if name == value)
        else:
            case_name, payload_val = value
            disc_val = next(i for i, (name, _) in enumerate(cases) if name == case_name)

        if disc_sz == 1:
            struct.pack_into('<B', buf, offset, disc_val)
        elif disc_sz == 2:
            struct.pack_into('<H', buf, offset, disc_val)
        else:
            struct.pack_into('<I', buf, offset, disc_val)

        if orig_kind != "enum":
            case_type = cases[disc_val][1]
            if case_type is not None and payload_val is not None:
                _lower_into(types, case_type, payload_val, buf, payload_offset)
    elif kind == "flags":
        labels = type_def.get("labels", [])
        n = len(labels)
        if n == 0:
            return
        if n <= 8:
            struct.pack_into('<B', buf, offset, value & 0xFF)
        elif n <= 16:
            struct.pack_into('<H', buf, offset, value & 0xFFFF)
        else:
            num_words = _num_i32_flags(n)
            for i in range(num_words):
                word = (value >> (i * 32)) & 0xFFFFFFFF
                struct.pack_into('<I', buf, offset + i * 4, word)
    elif kind == "list":
        ptr, length = value
        struct.pack_into('<I', buf, offset, ptr)
        struct.pack_into('<I', buf, offset + 4, length)
    else:
        raise ValueError(f"Unknown kind: {kind}")


def _lower_primitive(name, value, buf, offset):
    """Lower a primitive value into a buffer."""
    if name == "bool":
        struct.pack_into('<B', buf, offset, 1 if value else 0)
    elif name == "char":
        struct.pack_into('<I', buf, offset, ord(value))
    elif name == "string":
        ptr, length = value
        struct.pack_into('<I', buf, offset, ptr)
        struct.pack_into('<I', buf, offset + 4, length)
    else:
        fmt_map = {
            "u8": '<B', "s8": '<b',
            "u16": '<H', "s16": '<h',
            "u32": '<I', "s32": '<i',
            "u64": '<Q', "s64": '<q',
            "f32": '<f', "f64": '<d',
        }
        if name in fmt_map:
            struct.pack_into(fmt_map[name], buf, offset, value)
        else:
            raise ValueError(f"Unknown primitive: {name}")


def flatten_functype(types, params, results):
    """Compute the core wasm function type for a component-model function.

    Flattens parameter and result types into core wasm valtypes. When the
    total flat count exceeds the applicable threshold, all values are passed
    via a single i32 memory pointer instead.

    Args:
        types: Type definitions dict.
        params: List of component-level parameter type references.
        results: List of component-level result type references.

    Returns:
        Tuple (core_params, core_results) of valtype string lists.
    """
    flat_params = []
    for p in params:
        flat_params.extend(flatten_type(types, p))
    flat_results = []
    for r in results:
        flat_results.extend(flatten_type(types, r))
    if len(flat_params) > MAX_FLAT_PARAMS:
        flat_params = ["i32"]
    if len(flat_results) > MAX_FLAT_RESULTS:
        flat_results = ["i32"]
    return (flat_params, flat_results)


def store_list(types, element_type, values):
    """Serialize component-level values into a contiguous byte buffer
    following canonical ABI list storage layout.

    Args:
        types: Type definitions dict.
        element_type: Type reference for each element.
        values: List of values to store.

    Returns:
        Bytes containing the serialized list data.
    """
    if not values:
        return b''
    elem_size = size_of(types, element_type)
    elem_align = align_of(types, element_type)
    stride = _align_to(elem_size, elem_align)
    buf = bytearray(len(values) * stride)
    for i, val in enumerate(values):
        _lower_into(types, element_type, val, buf, i * stride)
    return bytes(buf)


def load_list(types, element_type, buffer, count):
    """Deserialize component-level values from a contiguous byte buffer
    following canonical ABI list storage layout.

    Args:
        types: Type definitions dict.
        element_type: Type reference for each element.
        buffer: Byte buffer to read from.
        count: Number of elements to read.

    Returns:
        List of deserialized values.
    """
    if count == 0:
        return []
    elem_size = size_of(types, element_type)
    elem_align = align_of(types, element_type)
    stride = _align_to(elem_size, elem_align)
    result = []
    for i in range(count):
        val = lift(types, element_type, buffer, i * stride)
        result.append(val)
    return result
