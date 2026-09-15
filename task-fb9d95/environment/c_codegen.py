"""
WGSL-to-C Memory Layout Bridge — Code Generator

Generates C11 struct definitions with _Alignas, explicit padding, and
static_assert verification that match WGSL memory layouts byte-for-byte.

INCOMPLETE: Handles only scalar and vec2/vec4 types in storage address space.
See TODO/NotImplementedError markers for unimplemented features.
"""

import math
from wgsl_parser import (ScalarType, VectorType, MatrixType, ArrayType,
                          StructRef, StructDef, StructMember)


def round_up(k, n):
    """Round up n to the next multiple of k."""
    return math.ceil(n / k) * k


SCALAR_INFO = {
    #         (align, size, c_type)
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
        if type_node.n == 4:
            return 4 * ea
        # TODO: vec3 alignment is NOT 3 * AlignOf(T).
        # Consult the spec (/app/spec.md) for the correct vec3 rule.
        raise NotImplementedError("vec3 alignment not implemented — see spec")

    if isinstance(type_node, MatrixType):
        # TODO: matCxR<T> is equivalent to array<vecR<T>, C>.
        # Delegate alignment computation to the equivalent array type.
        raise NotImplementedError("Matrix alignment not implemented")

    if isinstance(type_node, ArrayType):
        ea = wgsl_align(type_node.elem, address_space, struct_defs)
        # TODO: In uniform address space, array element alignment must be
        # rounded up to a multiple of 16. See spec for details.
        if address_space == "uniform":
            raise NotImplementedError("Uniform array alignment not implemented")
        return ea

    if isinstance(type_node, StructRef):
        # TODO: Look up the struct definition in struct_defs and compute
        # its alignment from its members' effective alignments.
        raise NotImplementedError("StructRef alignment not implemented")

    raise TypeError(f"Unknown WGSL type: {type(type_node)}")


def wgsl_size(type_node, address_space="storage", struct_defs=None):
    """Compute WGSL byte size for a type in the given address space."""
    if isinstance(type_node, ScalarType):
        return SCALAR_INFO[type_node.name][1]

    if isinstance(type_node, VectorType):
        es = SCALAR_INFO[type_node.elem.name][1]
        return type_node.n * es  # Correct for all N including vec3

    if isinstance(type_node, MatrixType):
        # TODO: matCxR<T> is equivalent to array<vecR<T>, C>.
        # Delegate size computation to the equivalent array type.
        raise NotImplementedError("Matrix size not implemented")

    if isinstance(type_node, ArrayType):
        arr_align = wgsl_align(type_node, address_space, struct_defs)
        es = wgsl_size(type_node.elem, address_space, struct_defs)
        stride = round_up(arr_align, es)
        return type_node.count * stride

    if isinstance(type_node, StructRef):
        # TODO: Look up struct definition and compute size by iterating
        # members, applying alignment, and rounding up to struct alignment.
        raise NotImplementedError("StructRef size not implemented")

    raise TypeError(f"Unknown WGSL type: {type(type_node)}")


def effective_member_align(member, address_space, struct_defs):
    """Compute effective alignment for a struct member.

    Combines the base type alignment, any @align attribute, and
    uniform address-space rounding for struct/array members.
    """
    base = wgsl_align(member.type, address_space, struct_defs)
    if member.align_attr is not None:
        base = max(base, member.align_attr)
    # TODO: In uniform address space, if the member's type is a struct
    # or array, round alignment up to a multiple of 16.
    return base


def effective_member_size(member, address_space, struct_defs):
    """Compute effective size for a struct member (respects @size attr)."""
    if member.size_attr is not None:
        return member.size_attr
    return wgsl_size(member.type, address_space, struct_defs)


# --------------- C code generation ---------------

def generate_c_struct(struct_def, address_space, struct_defs):
    """Generate complete C11 source for a WGSL struct with static_assert checks.

    The generated code includes:
      - Helper typedefs for wrapper types (arrays, matrices)
      - The struct definition with _Alignas and padding
      - static_assert checks for offsetof, sizeof, alignof
      - A main() that prints ALL_LAYOUT_CHECKS_PASSED

    Args:
        struct_def: StructDef to generate
        address_space: "storage" or "uniform"
        struct_defs: dict name -> StructDef (for resolving nested refs)

    Returns:
        Complete C source code string
    """
    gen = _CGen(struct_defs, address_space)
    return gen.generate(struct_def)


class _CGen:
    """Internal C code generator state."""

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

        # Generate nested struct dependencies first
        pre_lines, pre_asserts = [], []
        for m in struct_def.members:
            if isinstance(m.type, StructRef):
                # TODO: Emit nested struct C definition first
                raise NotImplementedError(
                    f"Nested struct '{m.type.name}' C generation not implemented")

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

        s_lines = pre_lines + [f"typedef struct {{"] + member_lines + [
            f"}} {c_name};", ""]
        a_lines = pre_asserts + assert_lines + [
            f'static_assert(sizeof({c_name}) == {final_size}, '
            f'"size of {c_name}");',
            f'static_assert(alignof({c_name}) == {max_align}, '
            f'"align of {c_name}");',
        ]
        return s_lines, a_lines

    def _emit_member_decl(self, member, eff_align):
        """Generate C declaration for one struct member."""
        t = member.type
        name = member.name

        if isinstance(t, ScalarType):
            c_type = SCALAR_INFO[t.name][2]
            if eff_align > SCALAR_INFO[t.name][0]:
                return f"_Alignas({eff_align}) {c_type} {name};"
            return f"{c_type} {name};"

        if isinstance(t, VectorType):
            if t.n == 3:
                # TODO: vec3 needs correct _Alignas (4*AlignOf(T), not 3*)
                # and inline float[3] declaration.
                raise NotImplementedError("vec3 C generation not implemented")
            c_elem = SCALAR_INFO[t.elem.name][2]
            return f"_Alignas({eff_align}) {c_elem} {name}[{t.n}];"

        if isinstance(t, MatrixType):
            # TODO: Generate column-vector wrapper typedef and emit
            # as wrapper array: wrapper name[cols]
            raise NotImplementedError("Matrix C generation not implemented")

        if isinstance(t, ArrayType):
            # TODO: Generate element wrapper typedef (handles stride padding)
            # and emit as wrapper array: wrapper name[count]
            raise NotImplementedError("Array C generation not implemented")

        if isinstance(t, StructRef):
            # TODO: Use previously emitted nested struct C type
            raise NotImplementedError("StructRef C generation not implemented")

        raise TypeError(f"Unknown type for C emission: {type(t)}")
