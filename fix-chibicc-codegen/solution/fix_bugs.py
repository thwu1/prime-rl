#!/usr/bin/env python3
"""
Fix three bugs in chibicc's codegen.c and parse.c.

Bug 1 (codegen.c): Register width selection for integer binary operations
is missing the pointer base-type check. When a type has a ->base (meaning
it's a pointer/array), 64-bit registers must be used. The buggy code only
checks for TY_LONG, causing pointer arithmetic to use 32-bit registers
which truncate 64-bit addresses.

Fix: Restore `|| node->lhs->ty->base` to the condition.

Bug 2 (codegen.c): The cmp_zero() function compares an integer value to
zero. For types <= 4 bytes, it uses `cmp $0, %eax` (32-bit). For 8-byte
types (long), it must use `cmp $0, %rax` (64-bit). The bug changed the
threshold from `<= 4` to `<= 8`, making ALL integer types use the 32-bit
comparison, which ignores the upper 32 bits of long values.

Fix: Change `ty->size <= 8` back to `ty->size <= 4`.

Bug 3 (parse.c): In struct_decl(), the condition controlling whether to
apply alignment padding to struct members is inverted. Normal (non-packed)
structs should get alignment padding, but the bug makes packed structs get
padding and normal structs skip it.

Fix: Change `if (ty->is_packed)` back to `if (!ty->is_packed)`.
"""

import sys

def fix_codegen():
    path = "/app/chibicc/codegen.c"
    with open(path) as f:
        content = f.read()

    # Fix Bug 1: Restore pointer base-type check
    old1 = "if (node->lhs->ty->kind == TY_LONG) {"
    new1 = "if (node->lhs->ty->kind == TY_LONG || node->lhs->ty->base) {"
    if old1 not in content:
        print("Bug 1 already fixed or pattern not found")
    else:
        content = content.replace(old1, new1, 1)
        print("Bug 1 fixed: restored pointer base-type check in register selection")

    # Fix Bug 2: Restore correct size threshold in cmp_zero
    old2 = "if (is_integer(ty) && ty->size <= 8)"
    new2 = "if (is_integer(ty) && ty->size <= 4)"
    if old2 not in content:
        print("Bug 2 already fixed or pattern not found")
    else:
        content = content.replace(old2, new2, 1)
        print("Bug 2 fixed: restored ty->size <= 4 threshold in cmp_zero")

    with open(path, "w") as f:
        f.write(content)


def fix_parse():
    path = "/app/chibicc/parse.c"
    with open(path) as f:
        content = f.read()

    # Fix Bug 3: Restore correct is_packed condition
    old3 = """      if (ty->is_packed)
        bits = align_to(bits, mem->align * 8);
      mem->offset = bits / 8;
      bits += mem->ty->size * 8;"""

    new3 = """      if (!ty->is_packed)
        bits = align_to(bits, mem->align * 8);
      mem->offset = bits / 8;
      bits += mem->ty->size * 8;"""

    if old3 not in content:
        print("Bug 3 already fixed or pattern not found")
    else:
        content = content.replace(old3, new3, 1)
        print("Bug 3 fixed: restored !ty->is_packed condition in struct_decl")

    with open(path, "w") as f:
        f.write(content)


if __name__ == "__main__":
    fix_codegen()
    fix_parse()
    print("All bugs fixed.")
