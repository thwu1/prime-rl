#!/usr/bin/env python3
"""Introduce 3 subtle bugs into chibicc's codegen.c for the benchmark task."""
import glob
import sys

files = glob.glob('/app/chibicc/**/codegen.c', recursive=True)
if not files:
    print("ERROR: codegen.c not found", file=sys.stderr)
    sys.exit(1)
filename = files[0]

with open(filename, 'r') as f:
    content = f.read()

original = content

# Bug 1: Off-by-one in struct/union byte-copy inside store()
# The loop copies bytes from source to dest for struct assignment.
# Changing i < ty->size to i < ty->size - 1 drops the last byte.
bug1_old = 'i < ty->size; i++) {\n      println("  mov %d(%%rax), %%r8b"'
bug1_new = 'i < ty->size - 1; i++) {\n      println("  mov %d(%%rax), %%r8b"'
assert bug1_old in content, "Bug 1 pattern not found in codegen.c"
content = content.replace(bug1_old, bug1_new, 1)

# Bug 2: Wrong sign-bit position for double negation
# IEEE 754 double sign bit is at position 63, not 31.
# This corrupts double negation results.
bug2_old = 'shl $63, %%rax");\n      println("  movq %%rax, %%xmm1");\n      println("  xorpd'
bug2_new = 'shl $31, %%rax");\n      println("  movq %%rax, %%xmm1");\n      println("  xorpd'
assert bug2_old in content, "Bug 2 pattern not found in codegen.c"
content = content.replace(bug2_old, bug2_new, 1)

# Bug 3: Modulo returns quotient instead of remainder
# After x86 idiv, quotient is in %rax and remainder in %rdx.
# The ND_MOD handler must move %rdx to %rax. Replacing with
# a no-op (mov %rax,%rax) leaves the quotient in %rax.
bug3_old = 'if (node->kind == ND_MOD)\n      println("  mov %%rdx, %%rax");'
bug3_new = 'if (node->kind == ND_MOD)\n      println("  mov %%rax, %%rax");'
assert bug3_old in content, "Bug 3 pattern not found in codegen.c"
content = content.replace(bug3_old, bug3_new, 1)

assert content != original, "No changes were made"

with open(filename, 'w') as f:
    f.write(content)

print(f"Successfully introduced 3 bugs into {filename}")
