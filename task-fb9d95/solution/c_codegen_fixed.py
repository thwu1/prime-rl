"""
WGSL-to-C Memory Layout Bridge — Complete Code Generator

Generates C11 struct definitions with _Alignas, explicit padding, and
static_assert verification that match WGSL memory layouts byte-for-byte.
Handles all WGSL types in both storage and uniform address spaces.
"""

import math
from wgsl_parser import (ScalarType, VectorType, MatrixType, ArrayType,
                          StructRef, StructDef, StructMember)


def round_up(k, n):
    """Round up n to the next multiple of k."""
    return math.ceil(n / k) * k


SCALAR_INFO = {
    "f32": (4, 4, "float"),
    "i32": (4, 4, "int32_t"),
    "u32": (4, 4, "uint32_t"),
    "f16": (2, 2, "uint16_t"),
}


# --------------- WGSL layout computation ---------------

def wgsl_align(type_node, address_space="storage", struct_defs=None):
    """Compute WGSL alignment for a type in the given address space."""
    if isinstance(type_node, ScalarType):
        return SCALAR_INFO[type_node.name][0]

    if isinstance(type_node, VectorType):
        ea = SCALAR_INFO[type_node.elem.name][0]
        if type_node.n == 2:
            return 2 * ea
        # vec3 and vec4 both use 4 * AlignOf(T)
        return 4 * ea

    if isinstance(type_node, MatrixType):
        # matCxR<T> equivalent to array<vecR<T>, C>
        col_vec = VectorType(type_node.rows, type_node.elem)
        equiv_arr = ArrayType(col_vec, type_node.cols)
        return wgsl_align(equiv_arr, address_space, struct_defs)

    if isinstance(type_node, ArrayType):
        ea = wgsl_align(type_node.elem, address_space, struct_defs)
        if address_space == "uniform":
            ea = round_up(16, ea)
        return ea

    if isinstance(type_node, StructRef):
        sd = struct_defs[type_node.name]
        return _struct_align(sd, address_space, struct_defs)

    raise TypeError(f"Unknown WGSL type: {type(type_node)}")


def wgsl_size(type_node, address_space="storage", struct_defs=None):
    """Compute WGSL byte size for a type in the given address space."""
    if isinstance(type_node, ScalarType):
        return SCALAR_INFO[type_node.name][1]

    if isinstance(type_node, VectorType):
        es = SCALAR_INFO[type_node.elem.name][1]
        return type_node.n * es

    if isinstance(type_node, MatrixType):
        col_vec = VectorType(type_node.rows, type_node.elem)
        equiv_arr = ArrayType(col_vec, type_node.cols)
        return wgsl_size(equiv_arr, address_space, struct_defs)

    if isinstance(type_node, ArrayType):
        arr_align = wgsl_align(type_node, address_space, struct_defs)
        es = wgsl_size(type_node.elem, address_space, struct_defs)
        stride = round_up(arr_align, es)
        return type_node.count * stride

    if isinstance(type_node, StructRef):
        sd = struct_defs[type_node.name]
        return _struct_size(sd, address_space, struct_defs)

    raise TypeError(f"Unknown WGSL type: {type(type_node)}")


def effective_member_align(member, address_space, struct_defs):
    """Compute effective alignment for a struct member."""
    base = wgsl_align(member.type, address_space, struct_defs)
    if member.align_attr is not None:
        base = max(base, member.align_attr)
    # In uniform, struct/array typed members get alignment rounded up to 16
    if address_space == "uniform" and isinstance(member.type, (ArrayType, StructRef)):
        base = round_up(16, base)
    return base


def effective_member_size(member, address_space, struct_defs):
    """Compute effective size for a struct member (respects @size attr)."""
    if member.size_attr is not None:
        return member.size_attr
    return wgsl_size(member.type, address_space, struct_defs)


def _struct_align(struct_def, address_space, struct_defs):
    """Compute alignment of a struct from its members' effective alignments."""
    return max(effective_member_align(m, address_space, struct_defs)
               for m in struct_def.members)


def _struct_size(struct_def, address_space, struct_defs):
    """Compute size of a struct (rounded up to alignment)."""
    offset = 0
    for m in struct_def.members:
        ea = effective_member_align(m, address_space, struct_defs)
        offset = round_up(ea, offset)
        offset += effective_member_size(m, address_space, struct_defs)
    return round_up(_struct_align(struct_def, address_space, struct_defs), offset)


def compute_struct_layout(struct_def, address_space, struct_defs):
    """Compute complete layout info for a struct (alignment, size, members)."""
    result = {
        "alignment": _struct_align(struct_def, address_space, struct_defs),
        "size": _struct_size(struct_def, address_space, struct_defs),
        "members": {}
    }
    offset = 0
    for m in struct_def.members:
        ea = effective_member_align(m, address_space, struct_defs)
        offset = round_up(ea, offset)
        result["members"][m.name] = {
            "offset": offset,
            "alignment": ea,
            "size": wgsl_size(m.type, address_space, struct_defs),
        }
        offset += effective_member_size(m, address_space, struct_defs)
    return result


# --------------- C code generation ---------------

def generate_c_struct(struct_def, address_space, struct_defs):
    """Generate complete C11 source for a WGSL struct with static_assert checks."""
    gen = _CGen(struct_defs, address_space)
    return gen.generate(struct_def)


class _CGen:
    """Internal C code generator."""

    def __init__(self, struct_defs, address_space):
        self.struct_defs = struct_defs
        self.address_space = address_space
        self._helpers = []
        self._helper_set = set()
        self._emitted_structs = set()

    def generate(self, struct_def):
        lines = [
            "#include <assert.h>",
            "#include <stdint.h>",
            "#include <stdalign.h>",
            "#include <stddef.h>",
            "#include <stdio.h>",
            "",
        ]
        struct_lines, assert_lines = self._emit_struct(struct_def)
        if self._helpers:
            lines.extend(self._helpers)
            lines.append("")
        lines.extend(struct_lines)
        lines.append("")
        lines.extend(assert_lines)
        lines.append("")
        lines.append("int main(void) {")
        lines.append('    printf("ALL_LAYOUT_CHECKS_PASSED\\n");')
        lines.append("    return 0;")
        lines.append("}")
        return "\n".join(lines)

    def _emit_struct(self, struct_def):
        c_name = f"{struct_def.name}_{self.address_space}"
        if c_name in self._emitted_structs:
            return [], []
        self._emitted_structs.add(c_name)

        # Emit dependencies first
        pre_lines, pre_asserts = [], []
        for m in struct_def.members:
            if isinstance(m.type, StructRef):
                dep = self.struct_defs[m.type.name]
                dl, da = self._emit_struct(dep)
                pre_lines.extend(dl)
                pre_asserts.extend(da)

        member_lines = []
        assert_lines = []
        offset = 0
        max_align = 0
        pad_idx = 0

        for m in struct_def.members:
            ea = effective_member_align(m, self.address_space, self.struct_defs)
            es = effective_member_size(m, self.address_space, self.struct_defs)
            ms = wgsl_size(m.type, self.address_space, self.struct_defs)

            aligned = round_up(ea, offset)
            if aligned > offset:
                member_lines.append(f"    char _pad{pad_idx}[{aligned - offset}];")
                pad_idx += 1

            c_decl = self._emit_member_decl(m, ea)
            member_lines.append(f"    {c_decl}")

            if es > ms:
                member_lines.append(f"    char _sizepad{pad_idx}[{es - ms}];")
                pad_idx += 1

            assert_lines.append(
                f'static_assert(offsetof({c_name}, {m.name}) == {aligned}, '
                f'"offset of {m.name}");')
            max_align = max(max_align, ea)
            offset = aligned + es

        final_size = round_up(max_align, offset)
        if final_size > offset:
            member_lines.append(f"    char _endpad[{final_size - offset}];")

        s_lines = (pre_lines +
                    [f"typedef struct {{"] + member_lines +
                    [f"}} {c_name};", ""])
        a_lines = (pre_asserts + assert_lines + [
            f'static_assert(sizeof({c_name}) == {final_size}, '
            f'"size of {c_name}");',
            f'static_assert(alignof({c_name}) == {max_align}, '
            f'"align of {c_name}");',
        ])
        return s_lines, a_lines

    def _emit_member_decl(self, member, eff_align):
        t = member.type
        name = member.name

        if isinstance(t, ScalarType):
            c_type = SCALAR_INFO[t.name][2]
            if eff_align > SCALAR_INFO[t.name][0]:
                return f"_Alignas({eff_align}) {c_type} {name};"
            return f"{c_type} {name};"

        if isinstance(t, VectorType):
            c_elem = SCALAR_INFO[t.elem.name][2]
            return f"_Alignas({eff_align}) {c_elem} {name}[{t.n}];"

        if isinstance(t, MatrixType):
            col_vec = VectorType(t.rows, t.elem)
            equiv_arr = ArrayType(col_vec, t.cols)
            wrapper = self._ensure_wrapper(equiv_arr)
            nat = wgsl_align(t, self.address_space, self.struct_defs)
            if eff_align > nat:
                return f"_Alignas({eff_align}) {wrapper} {name}[{t.cols}];"
            return f"{wrapper} {name}[{t.cols}];"

        if isinstance(t, ArrayType):
            wrapper = self._ensure_wrapper(t)
            nat = wgsl_align(t, self.address_space, self.struct_defs)
            if eff_align > nat:
                return f"_Alignas({eff_align}) {wrapper} {name}[{t.count}];"
            return f"{wrapper} {name}[{t.count}];"

        if isinstance(t, StructRef):
            c_type = f"{t.name}_{self.address_space}"
            nat = wgsl_align(t, self.address_space, self.struct_defs)
            if eff_align > nat:
                return f"_Alignas({eff_align}) {c_type} {name};"
            return f"{c_type} {name};"

        raise TypeError(f"Unknown type: {type(t)}")

    def _ensure_wrapper(self, arr_type):
        """Create wrapper typedef for array elements, return type name."""
        arr_align = wgsl_align(arr_type, self.address_space, self.struct_defs)
        sig = self._type_sig(arr_type.elem)
        w_name = f"_w_{sig}_{self.address_space}_{arr_align}"

        if w_name not in self._helper_set:
            self._helper_set.add(w_name)
            elem_c = self._c_elem_decl(arr_type.elem)
            self._helpers.append(
                f"typedef struct {{ _Alignas({arr_align}) {elem_c}; }} {w_name};")
        return w_name

    def _c_elem_decl(self, type_node):
        """C declaration for an element inside a wrapper struct."""
        if isinstance(type_node, ScalarType):
            return f"{SCALAR_INFO[type_node.name][2]} v"
        if isinstance(type_node, VectorType):
            return f"{SCALAR_INFO[type_node.elem.name][2]} v[{type_node.n}]"
        if isinstance(type_node, StructRef):
            return f"{type_node.name}_{self.address_space} v"
        raise TypeError(f"Cannot create element decl for {type(type_node)}")

    def _type_sig(self, type_node):
        if isinstance(type_node, ScalarType):
            return type_node.name
        if isinstance(type_node, VectorType):
            return f"v{type_node.n}{type_node.elem.name}"
        if isinstance(type_node, StructRef):
            return type_node.name
        return "x"
