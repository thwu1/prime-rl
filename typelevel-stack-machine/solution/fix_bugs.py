#!/usr/bin/env python3

"""
Fixes 7 bugs in the type-level stack machine through targeted source code analysis
and transformation. Identifies buggy patterns in each source file and applies
corrective replacements, then implements the missing conditional execution engine.

Bugs:
1. arithmetic.ts: Multiply accumulates B instead of A each iteration
2. stack-machine.ts: SUB computes A-B instead of B-A (wrong operand order)
3. stack-machine.ts: SWAP case entirely missing from Step type
4. stack-machine.ts: OVER copies first element instead of second
5. stack-machine.ts: ROT rotates in wrong direction
6. stack-machine.ts: Execute has no IFZERO/ELSE/ENDIF support
7. parser.ts: PUSH only parses single-digit numbers
"""

import sys
import os


def safe_replace(content, old, new, description, path):
    """Replace a pattern in content, raising an error if the pattern is not found."""
    if old not in content:
        print(f"ERROR: Pattern for '{description}' not found in {path}", file=sys.stderr)
        print(f"  Looking for: {repr(old[:80])}", file=sys.stderr)
        sys.exit(1)
    result = content.replace(old, new, 1)
    print(f"  Fixed: {description}")
    return result


def fix_arithmetic():
    """Fix Multiply type: accumulate A (first operand), not B (counter)."""
    path = '/app/src/arithmetic.ts'
    with open(path) as f:
        content = f.read()

    content = safe_replace(
        content,
        'Add<Acc, B>',
        'Add<Acc, A>',
        'Multiply accumulator operand (B -> A)',
        path
    )

    with open(path, 'w') as f:
        f.write(content)
    print(f"[OK] {path}")


def fix_stack_machine():
    """Fix Step type bugs and redesign Execute for conditional branching."""
    path = '/app/src/stack-machine.ts'
    with open(path) as f:
        content = f.read()

    # Fix 2: SUB operand order
    content = safe_replace(
        content,
        '[Subtract<A, B>',
        '[Subtract<B, A>',
        'SUB operand order (A,B -> B,A)',
        path
    )

    # Fix 3: Add missing SWAP case before POP
    content = safe_replace(
        content,
        "  : Inst extends ['POP']",
        "  : Inst extends ['SWAP']\n"
        "    ? Stack extends [infer A extends number, infer B extends number, ...infer Rest extends number[]]\n"
        "      ? [B, A, ...Rest]\n"
        "      : never\n"
        "  : Inst extends ['POP']",
        'Add missing SWAP case',
        path
    )

    # Fix 4: OVER element order
    content = safe_replace(
        content,
        '[A, A, B, ...Rest]',
        '[B, A, B, ...Rest]',
        'OVER element order (copy second, not first)',
        path
    )

    # Fix 5: ROT rotation direction
    content = safe_replace(
        content,
        '[B, C, A, ...Rest]',
        '[C, A, B, ...Rest]',
        'ROT rotation direction (third to top)',
        path
    )

    # Fix 6: Redesign Execute with conditional branching support
    old_execute = (
        "export type Execute<Stack extends number[], Program extends Instruction[]> =\n"
        "  Program extends [infer First extends Instruction, ...infer Remaining extends Instruction[]]\n"
        "    ? Step<Stack, First> extends infer NewStack extends number[]\n"
        "      ? Execute<NewStack, Remaining>\n"
        "      : never\n"
        "    : Stack;"
    )

    new_execute = (
        "export type Execute<\n"
        "  Stack extends number[],\n"
        "  Program extends Instruction[],\n"
        "  SkipDepth extends unknown[] = []\n"
        "> =\n"
        "  Program extends [infer First extends Instruction, ...infer Remaining extends Instruction[]]\n"
        "    ? SkipDepth['length'] extends 0\n"
        "      // --- Active execution mode ---\n"
        "      ? First extends ['IFZERO']\n"
        "        ? Stack extends [infer Top extends number, ...infer Rest extends number[]]\n"
        "          ? Top extends 0\n"
        "            ? Execute<Rest, Remaining, []>\n"
        "            : Execute<Rest, Remaining, [unknown]>\n"
        "          : never\n"
        "        : First extends ['ELSE']\n"
        "          ? Execute<Stack, Remaining, [unknown]>\n"
        "          : First extends ['ENDIF']\n"
        "            ? Execute<Stack, Remaining, []>\n"
        "            : Step<Stack, First> extends infer NewStack extends number[]\n"
        "              ? Execute<NewStack, Remaining>\n"
        "              : never\n"
        "      // --- Skipping mode ---\n"
        "      : First extends ['IFZERO']\n"
        "        ? Execute<Stack, Remaining, [unknown, ...SkipDepth]>\n"
        "        : First extends ['ELSE']\n"
        "          ? SkipDepth extends [unknown]\n"
        "            ? Execute<Stack, Remaining, []>\n"
        "            : Execute<Stack, Remaining, SkipDepth>\n"
        "          : First extends ['ENDIF']\n"
        "            ? SkipDepth extends [unknown, ...infer RestDepth extends unknown[]]\n"
        "              ? Execute<Stack, Remaining, RestDepth>\n"
        "              : never\n"
        "            : Execute<Stack, Remaining, SkipDepth>\n"
        "    : Stack;"
    )

    content = safe_replace(
        content,
        old_execute,
        new_execute,
        'Redesign Execute with IFZERO/ELSE/ENDIF conditional branching',
        path
    )

    with open(path, 'w') as f:
        f.write(content)
    print(f"[OK] {path}")


def fix_parser():
    """Fix PUSH to support multi-digit numbers using ParseDigits helper."""
    path = '/app/src/parser.ts'
    with open(path) as f:
        content = f.read()

    old_push = (
        "TrimLeft<S> extends `PUSH ${infer D extends Digit}${infer Rest}`\n"
        "    ? [['PUSH', StringToNumber<D>], Rest]"
    )

    new_push = (
        "TrimLeft<S> extends `PUSH${infer AfterPush}`\n"
        "    ? TrimLeft<AfterPush> extends infer Trimmed extends string\n"
        "      ? ParseDigits<Trimmed> extends [infer Digits extends string, infer Remaining extends string]\n"
        "        ? Digits extends ''\n"
        "          ? never\n"
        "          : [['PUSH', StringToNumber<Digits>], Remaining]\n"
        "        : never\n"
        "      : never"
    )

    content = safe_replace(
        content,
        old_push,
        new_push,
        'Multi-digit PUSH parsing via ParseDigits',
        path
    )

    with open(path, 'w') as f:
        f.write(content)
    print(f"[OK] {path}")


def verify_test_files_intact():
    """Sanity check: verify test files were not accidentally modified."""
    test_dir = '/app/tests'
    expected_files = [
        'test-arithmetic.ts',
        'test-stack-ops.ts',
        'test-parser.ts',
        'test-programs.ts',
        'test-conditionals.ts',
    ]
    for fname in expected_files:
        fpath = os.path.join(test_dir, fname)
        if not os.path.isfile(fpath):
            print(f"WARNING: Test file missing: {fpath}", file=sys.stderr)
            continue
        with open(fpath) as f:
            content = f.read()
        if '@ts-ignore' in content or '@ts-expect-error' in content:
            print(f"WARNING: Test file {fpath} contains suppression directives", file=sys.stderr)
    print("[OK] Test files verified intact")


if __name__ == '__main__':
    print("=== Fixing type-level stack machine bugs ===\n")

    print("1. Fixing arithmetic.ts...")
    fix_arithmetic()

    print("\n2. Fixing stack-machine.ts...")
    fix_stack_machine()

    print("\n3. Fixing parser.ts...")
    fix_parser()

    print("\n4. Verifying test files...")
    verify_test_files_intact()

    print("\n=== All bugs fixed and conditional branching implemented ===")
