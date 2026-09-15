#!/usr/bin/env python3
"""Apply fixes to the broken lit/FileCheck test suite.

Six bugs across six files:
1. lit.cfg.py: tool path uses ir_opt instead of ir-opt
2. test_cse.test: missing %s argument to ir-opt (reads empty stdin)
3. test_scope.test: FileCheck variable [[V]] leaks across CHECK-LABEL boundaries
4. test_constfold.test: CHECK-NOT pattern too broad (catches unrelated constant)
5. test_dag.test: two CHECK-DAG patterns match same single output line
6. test_canonicalize.test: --implicit-check-not="arith." catches arith.constant lines
"""


import os

TESTS_DIR = '/app/tests'


def fix_file(filename, old, new):
    path = os.path.join(TESTS_DIR, filename)
    with open(path) as f:
        content = f.read()
    if old not in content:
        raise ValueError(f"Pattern not found in {filename}: {old!r}")
    content = content.replace(old, new, 1)
    with open(path, 'w') as f:
        f.write(content)
    print(f"Fixed {filename}: replaced {old!r}")


def main():
    # Fix 1: lit.cfg.py — wrong tool path (underscore vs hyphen)
    fix_file(
        'lit.cfg.py',
        "python3 /app/tools/ir_opt",
        "python3 /app/tools/ir-opt"
    )

    # Fix 2: test_cse.test — missing %s in RUN line
    # Without %s, ir-opt reads from stdin (empty) and produces no output
    fix_file(
        'test_cse.test',
        '%ir-opt --cse |',
        '%ir-opt --cse %s |'
    )

    # Fix 3: test_scope.test — variable [[V]] leaks from func_alpha to func_beta
    # In the second CHECK-LABEL block, [[V]] still holds %x from func_alpha
    # but func_beta's addi uses %arg0, causing a mismatch.
    # Fix: use a regex match instead of the stale variable reference
    fix_file(
        'test_scope.test',
        '// CHECK: arith.addi [[V]], [[C]]',
        '// CHECK: arith.addi {{%.+}}, [[C]]'
    )

    # Fix 4: test_constfold.test — CHECK-NOT: arith.constant is too broad
    # It catches the arith.constant 7 line, which should remain.
    # The intent was to verify the duplicate constant 3 was CSE'd away.
    fix_file(
        'test_constfold.test',
        '// CHECK-NOT: arith.constant\n// CHECK: arith.addi',
        '// CHECK-NOT: arith.constant 3\n// CHECK: arith.addi'
    )

    # Fix 5: test_dag.test — two CHECK-DAG patterns both match the single
    # remaining addi line after CSE. After CSE removes the duplicate,
    # only one addi remains, so the second DAG fails to find a match.
    # Fix: use a single CHECK instead of two CHECK-DAGs
    fix_file(
        'test_dag.test',
        '// CHECK-DAG: [[R:%.+]] = arith.addi %arg0\n'
        '// CHECK-DAG: arith.addi {{.*}}, %arg1\n'
        '// CHECK-NOT: arith.addi',
        '// CHECK: [[R:%.+]] = arith.addi %arg0, %arg1\n'
        '// CHECK-NOT: arith.addi'
    )

    # Fix 6: test_canonicalize.test — implicit-check-not="arith." fires on
    # arith.constant lines that remain after canonicalization (dead constants
    # are not removed without --dce). Fix: also run --dce to remove them.
    fix_file(
        'test_canonicalize.test',
        '%ir-opt --canonicalize %s',
        '%ir-opt --canonicalize --dce %s'
    )

    print("\nAll fixes applied.")


if __name__ == '__main__':
    main()
