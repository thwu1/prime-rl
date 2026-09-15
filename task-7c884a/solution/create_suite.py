#!/usr/bin/env python3
"""Create a complete lit/FileCheck test suite and pass-behavior analysis for ir-opt.

Designs tests for all four passes (CSE, constfold, DCE, canonicalize) individually
and in multi-pass combinations, using advanced FileCheck features: CHECK-LABEL,
CHECK-DAG, CHECK-NOT, CHECK-SAME, variable capture, --implicit-check-not,
and --split-input-file. Analyzes pass edge cases by running ir-opt on provided
input files.
"""


import os
import json
import subprocess
import re

TESTS_DIR = '/app/tests'


def write_file(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


def run_ir_opt(*args):
    """Run ir-opt and return stdout."""
    result = subprocess.run(
        ['python3', '/app/tools/ir-opt'] + list(args),
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"ir-opt failed with args {args}: {result.stderr}")
    return result.stdout


def create_lit_config():
    write_file(f'{TESTS_DIR}/lit.cfg.py', """\
import lit.formats
import os

config.name = "IR-Opt"
config.test_format = lit.formats.ShTest(True)
config.suffixes = ['.test']
config.test_source_root = os.path.dirname(__file__)

# Tool substitution: %ir-opt expands to the optimizer invocation
config.substitutions.append(('%ir-opt', 'python3 /app/tools/ir-opt'))
""")


def create_test_cse():
    """Test CSE pass: CHECK-LABEL, variable capture, CHECK-NOT."""
    write_file(f'{TESTS_DIR}/test_cse.test', """\
// RUN: %ir-opt --cse %s | FileCheck %s

// Test that CSE eliminates duplicate addi operations
func @cse_addi(%arg0: i32, %arg1: i32) -> i32 {
  %a = arith.addi %arg0, %arg1 : i32
  %b = arith.addi %arg0, %arg1 : i32
  %c = arith.muli %a, %b : i32
  return %c : i32
}

// Test that CSE eliminates duplicate constants
func @cse_constant(%arg0: i32) -> i32 {
  %c1 = arith.constant 42 : i32
  %c2 = arith.constant 42 : i32
  %a = arith.addi %arg0, %c1 : i32
  %b = arith.muli %a, %c2 : i32
  return %b : i32
}

// CHECK-LABEL: func @cse_addi
// CHECK: [[V:%.+]] = arith.addi %arg0, %arg1
// CHECK-NOT: arith.addi
// CHECK: arith.muli [[V]], [[V]]

// CHECK-LABEL: func @cse_constant
// CHECK: [[C:%.+]] = arith.constant 42
// CHECK-NOT: arith.constant 42
// CHECK: arith.addi %arg0, [[C]]
// CHECK: arith.muli {{%.+}}, [[C]]
""")


def create_test_constfold():
    """Test constant folding: CHECK-DAG for unordered constants, variable capture."""
    write_file(f'{TESTS_DIR}/test_constfold.test', """\
// RUN: %ir-opt --constfold %s | FileCheck %s

// Test chained constant folding: 3*7=21, 21+5=26
func @fold_chain() -> i32 {
  %a = arith.constant 3 : i32
  %b = arith.constant 7 : i32
  %c = arith.muli %a, %b : i32
  %d = arith.constant 5 : i32
  %e = arith.addi %c, %d : i32
  return %e : i32
}

// Test remainder folding: 17 % 5 = 2
func @fold_remsi() -> i32 {
  %a = arith.constant 17 : i32
  %b = arith.constant 5 : i32
  %c = arith.remsi %a, %b : i32
  return %c : i32
}

// CHECK-LABEL: func @fold_chain
// CHECK-DAG: arith.constant 3
// CHECK-DAG: arith.constant 7
// CHECK: arith.constant 21
// CHECK: arith.constant 5
// CHECK: [[FINAL:%.+]] = arith.constant 26
// CHECK: return [[FINAL]]

// CHECK-LABEL: func @fold_remsi
// CHECK: arith.constant 17
// CHECK: arith.constant 5
// CHECK: [[REM:%.+]] = arith.constant 2
// CHECK: return [[REM]]
""")


def create_test_dce():
    """Test DCE: --implicit-check-not ensures no unexpected constants."""
    write_file(f'{TESTS_DIR}/test_dce.test', """\
// RUN: %ir-opt --dce %s | FileCheck --implicit-check-not="arith.constant" %s

// Dead constants 42 and 99 should be eliminated; only constant 1 is live
func @remove_dead(%arg0: i32) -> i32 {
  %dead1 = arith.constant 42 : i32
  %dead2 = arith.constant 99 : i32
  %alive = arith.constant 1 : i32
  %r = arith.addi %arg0, %alive : i32
  return %r : i32
}

// CHECK-LABEL: func @remove_dead
// CHECK: arith.constant 1
// CHECK: arith.addi
// CHECK: return
""")


def create_test_canonicalize():
    """Test canonicalization: CHECK-SAME for signature, multiple functions."""
    write_file(f'{TESTS_DIR}/test_canonicalize.test', """\
// RUN: %ir-opt --canonicalize --dce %s | FileCheck %s

// x + 0 => x
func @add_zero(%arg0: i32) -> i32 {
  %z = arith.constant 0 : i32
  %r = arith.addi %arg0, %z : i32
  return %r : i32
}

// x * 1 => x
func @mul_one(%arg0: i32) -> i32 {
  %one = arith.constant 1 : i32
  %r = arith.muli %arg0, %one : i32
  return %r : i32
}

// x - x => 0
func @self_sub(%arg0: i32) -> i32 {
  %a = arith.subi %arg0, %arg0 : i32
  return %a : i32
}

// x * 0 => 0
func @mul_zero(%arg0: i32) -> i32 {
  %z = arith.constant 0 : i32
  %a = arith.muli %arg0, %z : i32
  return %a : i32
}

// CHECK-LABEL: func @add_zero
// CHECK-SAME: (%arg0: i32)
// CHECK-NOT: arith.addi
// CHECK: return %arg0

// CHECK-LABEL: func @mul_one
// CHECK-SAME: -> i32
// CHECK-NOT: arith.muli
// CHECK: return %arg0

// CHECK-LABEL: func @self_sub
// CHECK: arith.constant 0
// CHECK: return

// CHECK-LABEL: func @mul_zero
// CHECK: [[Z:%.+]] = arith.constant 0
// CHECK-NOT: arith.muli
// CHECK: return [[Z]]
""")


def create_test_split():
    """Test --split-input-file with CSE across separate sections."""
    write_file(f'{TESTS_DIR}/test_split.test', """\
// RUN: %ir-opt --cse --split-input-file %s | FileCheck %s

func @first(%arg0: i32, %arg1: i32) -> i32 {
  %a = arith.addi %arg0, %arg1 : i32
  %b = arith.addi %arg0, %arg1 : i32
  %c = arith.muli %a, %b : i32
  return %c : i32
}

// CHECK-LABEL: func @first
// CHECK: [[X:%.+]] = arith.addi
// CHECK-NOT: arith.addi
// CHECK: arith.muli [[X]], [[X]]

// -----

func @second(%arg0: i32) -> i32 {
  %c1 = arith.constant 5 : i32
  %c2 = arith.constant 5 : i32
  %r = arith.addi %arg0, %c1 : i32
  return %r : i32
}

// CHECK-LABEL: func @second
// CHECK: [[K:%.+]] = arith.constant 5
// CHECK-NOT: arith.constant 5
// CHECK: arith.addi %arg0, [[K]]
""")


def create_test_composition():
    """Test all four passes composed: CSE + constfold + canonicalize + DCE."""
    write_file(f'{TESTS_DIR}/test_composition.test', """\
// RUN: %ir-opt --cse --constfold --canonicalize --dce %s | FileCheck %s

// 11 input operations should reduce to just 2 after all four passes:
//   CSE removes duplicate constant 3
//   constfold computes 3*7 = 21
//   canonicalize eliminates add-zero, mul-one, self-sub
//   DCE removes all dead constants
func @pipeline(%arg0: i32) -> i32 {
  %c0 = arith.constant 0 : i32
  %c1 = arith.constant 1 : i32
  %c3 = arith.constant 3 : i32
  %c7 = arith.constant 7 : i32
  %c3b = arith.constant 3 : i32
  %add1 = arith.addi %arg0, %c0 : i32
  %mul1 = arith.muli %add1, %c1 : i32
  %sub1 = arith.subi %mul1, %mul1 : i32
  %prod = arith.muli %c3, %c7 : i32
  %res = arith.addi %prod, %arg0 : i32
  return %res : i32
}

// CHECK-LABEL: func @pipeline
// CHECK-SAME: (%arg0: i32) -> i32
// CHECK: [[P:%.+]] = arith.constant 21
// CHECK-NOT: arith.constant
// CHECK: [[R:%.+]] = arith.addi [[P]], %arg0
// CHECK: return [[R]]
""")


def create_analysis():
    """Run ir-opt on analysis input files and compute answers."""
    answers = {}

    # Q1: What value does --constfold compute for 3*7+5?
    output = run_ir_opt('--constfold', '/app/inputs/fold_chain.ir')
    constants = re.findall(r'arith\.constant\s+(-?\d+)', output)
    answers['q1_fold_chain_result'] = int(constants[-1])

    # Q2: Does --canonicalize (alone) remove unreferenced constants?
    output = run_ir_opt('--canonicalize', '/app/inputs/dead_after_canon.ir')
    lines = output.strip().split('\n')
    const_names = re.findall(r'(%.+?)\s*=\s*arith\.constant', output)
    # Check which constants are actually referenced by non-constant ops or return
    non_const_lines = [l for l in lines
                       if 'return' in l or ('arith.' in l and 'arith.constant' not in l)]
    referenced = set()
    for line in non_const_lines:
        for name in const_names:
            if name in line:
                referenced.add(name)
    dead_constants = [n for n in const_names if n not in referenced]
    answers['q2_canonicalize_removes_dead_code'] = len(dead_constants) == 0

    # Q3: Does CSE treat addi(a,b) and addi(b,a) as equivalent?
    output = run_ir_opt('--cse', '/app/inputs/commutative.ir')
    addi_count = len(re.findall(r'arith\.addi', output))
    answers['q3_cse_commutative_aware'] = addi_count == 1

    # Q4: What opcode replaces muli(x, 0) after canonicalize?
    output = run_ir_opt('--canonicalize', '/app/inputs/mul_zero.ir')
    if 'arith.muli' not in output:
        ops = re.findall(r'=\s*(arith\.\w+)', output)
        answers['q4_mul_zero_replacement_opcode'] = ops[-1] if ops else 'unknown'
    else:
        answers['q4_mul_zero_replacement_opcode'] = 'arith.muli'

    # Q5: Does constfold fold remsi(10, 0)?
    output = run_ir_opt('--constfold', '/app/inputs/remsi_zero.ir')
    answers['q5_constfold_handles_remsi_divzero'] = 'arith.remsi' not in output

    # Q6: How many ops after all four passes on combined.ir?
    output = run_ir_opt('--cse', '--constfold', '--canonicalize', '--dce',
                        '/app/inputs/combined.ir')
    op_count = len(re.findall(r'=\s*arith\.', output))
    answers['q6_combined_ops_remaining'] = op_count

    write_file('/app/analysis.json', json.dumps(answers, indent=2) + '\n')
    print(f"Analysis answers:\n{json.dumps(answers, indent=2)}")


def main():
    print("Creating lit configuration...")
    create_lit_config()

    print("Creating test files...")
    create_test_cse()
    create_test_constfold()
    create_test_dce()
    create_test_canonicalize()
    create_test_split()
    create_test_composition()

    print("Running pass-behavior analysis...")
    create_analysis()

    print("\nTest suite and analysis created successfully.")


if __name__ == '__main__':
    main()
