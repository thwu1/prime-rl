"""
Applies fixes to the WGSL memory layout calculator at /app/wgsl_layout.py.

Reads the specification, identifies the 6 bugs in the implementation, and
writes the corrected version.
"""

CORRECTED_CODE = '''\
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
        # FIX 1: vec3 alignment is 4*AlignOf(T), not 3*AlignOf(T)
        if n == 2:
            return 2 * elem_align
        else:  # n == 3 or n == 4
            return 4 * elem_align

    elif isinstance(wgsl_type, MatrixType):
        # FIX 6: matrix is equivalent to array of column vectors;
        # delegate to array alignment which handles uniform rounding
        col_vec = VectorType(wgsl_type.rows, wgsl_type.elem_type)
        equivalent_array = ArrayType(col_vec, wgsl_type.cols)
        return align_of(equivalent_array, address_space)

    elif isinstance(wgsl_type, ArrayType):
        elem_align = align_of(wgsl_type.elem_type, address_space)
        # FIX 2a: in uniform, array element alignment is rounded up to 16
        if address_space == "uniform":
            elem_align = round_up(16, elem_align)
        return elem_align

    elif isinstance(wgsl_type, StructType):
        # FIX 5a: use effective member alignment (includes uniform rounding)
        # instead of raw type alignment
        max_align = 0
        for member in wgsl_type.members:
            max_align = max(max_align, _effective_member_align(member, address_space))
        return max_align

    raise TypeError(f"Unknown type: {type(wgsl_type)}")


def _effective_member_align(member, address_space):
    """Compute the effective alignment for a struct member."""
    base_align = align_of(member.type, address_space)
    if member.align_attr is not None:
        base_align = max(base_align, member.align_attr)
    # FIX 5b: in uniform, struct/array typed members have alignment rounded up to 16
    if address_space == "uniform" and isinstance(member.type, (StructType, ArrayType)):
        base_align = round_up(16, base_align)
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
        # FIX 4: matrix is equivalent to array of column vectors;
        # delegate to array size which handles stride padding
        col_vec = VectorType(wgsl_type.rows, wgsl_type.elem_type)
        equivalent_array = ArrayType(col_vec, wgsl_type.cols)
        return size_of(equivalent_array, address_space)

    elif isinstance(wgsl_type, ArrayType):
        # FIX 2b: use array alignment (which includes uniform rounding)
        # for stride, not bare element alignment
        arr_align = align_of(wgsl_type, address_space)
        elem_size = size_of(wgsl_type.elem_type, address_space)
        stride = round_up(arr_align, elem_size)
        return wgsl_type.count * stride

    elif isinstance(wgsl_type, StructType):
        offset = 0
        for member in wgsl_type.members:
            m_align = _effective_member_align(member, address_space)
            offset = round_up(m_align, offset)
            m_size = _effective_member_size(member, address_space)
            offset += m_size
        # FIX 3: round up struct size to struct alignment
        return round_up(align_of(wgsl_type, address_space), offset)

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

    raise ValueError(f"Member \\'{member_name}\\' not found in struct \\'{struct_type.name}\\'")
'''

with open("/app/wgsl_layout.py", "w") as f:
    f.write(CORRECTED_CODE)

print("Applied 6 fixes to /app/wgsl_layout.py:")
print("  1. vec3 alignment: 4*AlignOf(T), not N*AlignOf(T)")
print("  2. Uniform array alignment: roundUp(16, elem_align) + use array align for stride")
print("  3. Struct end padding: roundUp(struct_align, total)")
print("  4. Matrix size: delegate to equivalent array of column vectors")
print("  5. Uniform struct/array member alignment: roundUp(16, ...) + use effective align in struct")
print("  6. Matrix alignment: delegate to equivalent array (inherits uniform rounding)")
