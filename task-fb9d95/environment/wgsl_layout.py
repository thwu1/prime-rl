"""
WGSL Memory Layout Calculator

Computes alignment, size, stride, and member offsets for WGSL types
according to the WebGPU Shading Language specification memory layout rules.

Supports both 'storage' and 'uniform' address space layouts.
"""

import math


def round_up(k, n):
    """Round up n to the next multiple of k."""
    return math.ceil(n / k) * k


class WGSLType:
    """Base class for WGSL types."""
    pass


class ScalarType(WGSLType):
    """Scalar types: f32, i32, u32, f16."""
    def __init__(self, name):
        if name not in ("f32", "i32", "u32", "f16"):
            raise ValueError(f"Unknown scalar type: {name}")
        self.name = name

    def __repr__(self):
        return self.name


class VectorType(WGSLType):
    """Vector types: vec2<T>, vec3<T>, vec4<T>."""
    def __init__(self, n, elem_type):
        if n not in (2, 3, 4):
            raise ValueError(f"Invalid vector size: {n}")
        self.n = n
        self.elem_type = elem_type

    def __repr__(self):
        return f"vec{self.n}<{self.elem_type}>"


class MatrixType(WGSLType):
    """Matrix types: matCxR<T>. C columns of R-element vectors (column-major)."""
    def __init__(self, cols, rows, elem_type):
        if cols not in (2, 3, 4) or rows not in (2, 3, 4):
            raise ValueError(f"Invalid matrix dimensions: {cols}x{rows}")
        self.cols = cols
        self.rows = rows
        self.elem_type = elem_type

    def __repr__(self):
        return f"mat{self.cols}x{self.rows}<{self.elem_type}>"


class ArrayType(WGSLType):
    """Fixed-size array type: array<E, N>."""
    def __init__(self, elem_type, count):
        self.elem_type = elem_type
        self.count = count

    def __repr__(self):
        return f"array<{self.elem_type}, {self.count}>"


class StructMember:
    """A member of a struct type, with optional @align and @size attributes."""
    def __init__(self, name, member_type, align_attr=None, size_attr=None):
        self.name = name
        self.type = member_type
        self.align_attr = align_attr
        self.size_attr = size_attr

    def __repr__(self):
        attrs = ""
        if self.align_attr:
            attrs += f"@align({self.align_attr}) "
        if self.size_attr:
            attrs += f"@size({self.size_attr}) "
        return f"{attrs}{self.name}: {self.type}"


class StructType(WGSLType):
    """Structure type with ordered members."""
    def __init__(self, name, members):
        self.name = name
        self.members = members

    def __repr__(self):
        return f"struct {self.name}"


# ---- Layout computation functions ----

_SCALAR_PROPS = {
    "f32": (4, 4),
    "i32": (4, 4),
    "u32": (4, 4),
    "f16": (2, 2),
}


def align_of(wgsl_type, address_space="storage"):
    """Compute the alignment requirement of a WGSL type in the given address space."""

    if isinstance(wgsl_type, ScalarType):
        return _SCALAR_PROPS[wgsl_type.name][0]

    elif isinstance(wgsl_type, VectorType):
        elem_align = align_of(wgsl_type.elem_type, address_space)
        n = wgsl_type.n
        return n * elem_align

    elif isinstance(wgsl_type, MatrixType):
        col_vec = VectorType(wgsl_type.rows, wgsl_type.elem_type)
        return align_of(col_vec, address_space)

    elif isinstance(wgsl_type, ArrayType):
        elem_align = align_of(wgsl_type.elem_type, address_space)
        return elem_align

    elif isinstance(wgsl_type, StructType):
        max_align = 0
        for member in wgsl_type.members:
            member_align = align_of(member.type, address_space)
            if member.align_attr is not None:
                member_align = max(member_align, member.align_attr)
            max_align = max(max_align, member_align)
        return max_align

    raise TypeError(f"Unknown type: {type(wgsl_type)}")


def _effective_member_align(member, address_space):
    """Compute the effective alignment for a struct member."""
    base_align = align_of(member.type, address_space)
    if member.align_attr is not None:
        base_align = max(base_align, member.align_attr)
    return base_align


def _effective_member_size(member, address_space):
    """Compute the effective size contribution of a struct member."""
    base_size = size_of(member.type, address_space)
    if member.size_attr is not None:
        return member.size_attr
    return base_size


def size_of(wgsl_type, address_space="storage"):
    """Compute the byte size of a WGSL type in the given address space."""

    if isinstance(wgsl_type, ScalarType):
        return _SCALAR_PROPS[wgsl_type.name][1]

    elif isinstance(wgsl_type, VectorType):
        elem_size = size_of(wgsl_type.elem_type, address_space)
        return wgsl_type.n * elem_size

    elif isinstance(wgsl_type, MatrixType):
        elem_size = size_of(wgsl_type.elem_type, address_space)
        return wgsl_type.cols * wgsl_type.rows * elem_size

    elif isinstance(wgsl_type, ArrayType):
        elem_align = align_of(wgsl_type.elem_type, address_space)
        elem_size = size_of(wgsl_type.elem_type, address_space)
        stride = round_up(elem_align, elem_size)
        return wgsl_type.count * stride

    elif isinstance(wgsl_type, StructType):
        offset = 0
        for member in wgsl_type.members:
            m_align = _effective_member_align(member, address_space)
            offset = round_up(m_align, offset)
            m_size = _effective_member_size(member, address_space)
            offset += m_size
        return offset

    raise TypeError(f"Unknown type: {type(wgsl_type)}")


def stride_of(wgsl_type, address_space="storage"):
    """Compute the array stride for a WGSL type."""
    a = align_of(wgsl_type, address_space)
    s = size_of(wgsl_type, address_space)
    return round_up(a, s)


def offset_of(struct_type, member_name, address_space="storage"):
    """Compute the byte offset of a member within a struct."""
    if not isinstance(struct_type, StructType):
        raise TypeError("offset_of requires a StructType")

    offset = 0
    for member in struct_type.members:
        m_align = _effective_member_align(member, address_space)
        offset = round_up(m_align, offset)
        if member.name == member_name:
            return offset
        m_size = _effective_member_size(member, address_space)
        offset += m_size

    raise ValueError(f"Member '{member_name}' not found in struct '{struct_type.name}'")
