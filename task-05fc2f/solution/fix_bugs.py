#!/usr/bin/env python3
"""Reverse the 3 bugs introduced into chibicc's codegen.c."""
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
fixed = 0

# Fix 1: Restore correct struct byte-copy loop bound in store()
bug1 = 'i < ty->size - 1; i++) {\n      println("  mov %d(%%rax), %%r8b"'
fix1 = 'i < ty->size; i++) {\n      println("  mov %d(%%rax), %%r8b"'
if bug1 in content:
    content = content.replace(bug1, fix1, 1)
    fixed += 1
    print("Fixed bug 1: struct store off-by-one")

# Fix 2: Restore correct sign-bit shift for double negation
bug2 = 'shl $31, %%rax");\n      println("  movq %%rax, %%xmm1");\n      println("  xorpd'
fix2 = 'shl $63, %%rax");\n      println("  movq %%rax, %%xmm1");\n      println("  xorpd'
if bug2 in content:
    content = content.replace(bug2, fix2, 1)
    fixed += 1
    print("Fixed bug 2: double negation sign-bit shift")

# Fix 3: Restore modulo to return remainder from %rdx
bug3 = 'if (node->kind == ND_MOD)\n      println("  mov %%rax, %%rax");'
fix3 = 'if (node->kind == ND_MOD)\n      println("  mov %%rdx, %%rax");'
if bug3 in content:
    content = content.replace(bug3, fix3, 1)
    fixed += 1
    print("Fixed bug 3: modulo returns remainder")

if content != original:
    with open(filename, 'w') as f:
        f.write(content)
    print(f"Applied {fixed} fix(es) to {filename}")
else:
    print("WARNING: No bugs found to fix - file may already be correct")
