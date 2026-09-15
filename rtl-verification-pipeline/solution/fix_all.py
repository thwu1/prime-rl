#!/usr/bin/env python3
"""Fix all bugs in the mutation adequacy pipeline.

Bugs fixed:
1. config.py:   Missing --exe and --build Verilator flags
2. compiler.py: Testbench file not passed to Verilator command
3. runner.py:   subprocess.run missing capture_output/text
4. parser.py:   Regex uses {RESULTS} but testbench outputs [RESULTS]
5. scorer.py:   Denominator must exclude equivalent mutants
6. reporter.py: Report missing aggregate statistics object
7. Mutation JSONs: 4 incorrect equivalence classifications
8. tb_alu.cpp:  Missing test vectors to kill non-equivalent mutations
"""
import json
import os

print("=" * 60)
print("Fixing Mutation Adequacy Pipeline")
print("=" * 60)

# --------------------------------------------------------------------------
# Fix 1: config.py — add --exe and --build to Verilator flags
# --------------------------------------------------------------------------
print("\n[1/8] Fixing Verilator flags in config.py...")
with open("/app/harness/config.py", "w") as f:
    f.write('''\
"""Configuration for the mutation adequacy pipeline."""
import os

VERILATOR_CMD = "verilator"
VERILATOR_FLAGS = ["--cc", "--exe", "--build", "-Wall", "--Mdir"]

RTL_SOURCE = "/app/rtl/alu.v"
TESTBENCH = "/app/tb/tb_alu.cpp"
MUTATIONS_DIR = "/app/mutations"
RESULTS_DIR = "/app/results"
BUILD_DIR = "/app/build"
''')
print("  Fixed: /app/harness/config.py")

# --------------------------------------------------------------------------
# Fix 2: compiler.py — include testbench file in Verilator command
# --------------------------------------------------------------------------
print("\n[2/8] Fixing compilation command in compiler.py...")
with open("/app/harness/compiler.py", "w") as f:
    f.write('''\
"""Compiles mutated RTL with Verilator."""
import os
import subprocess
from harness.config import VERILATOR_CMD, VERILATOR_FLAGS, RTL_SOURCE, TESTBENCH, BUILD_DIR


def compile_mutation(mutation_id, mutated_rtl_path):
    """Compile a mutated RTL file with Verilator."""
    obj_dir = os.path.join(BUILD_DIR, mutation_id, "obj_dir")
    os.makedirs(os.path.dirname(obj_dir), exist_ok=True)

    cmd = [VERILATOR_CMD] + VERILATOR_FLAGS + [obj_dir, mutated_rtl_path, TESTBENCH]

    result = subprocess.run(cmd, capture_output=True, text=True)

    binary_path = os.path.join(obj_dir, "Valu")
    return {
        "success": result.returncode == 0,
        "binary": binary_path if os.path.exists(binary_path) else None,
        "stderr": result.stderr,
    }
''')
print("  Fixed: /app/harness/compiler.py")

# --------------------------------------------------------------------------
# Fix 3: runner.py — capture subprocess stdout and stderr
# --------------------------------------------------------------------------
print("\n[3/8] Fixing output capture in runner.py...")
with open("/app/harness/runner.py", "w") as f:
    f.write('''\
"""Runs compiled simulations."""
import subprocess
import os
from harness.config import RESULTS_DIR


def run_simulation(mutation_id, binary_path):
    """Run the compiled simulation binary."""
    log_dir = os.path.join(RESULTS_DIR, mutation_id)
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "simulation.log")

    result = subprocess.run([binary_path], capture_output=True, text=True)

    with open(log_path, "w") as f:
        f.write(getattr(result, "stdout", "") or "")

    return {"returncode": result.returncode, "log_path": log_path}
''')
print("  Fixed: /app/harness/runner.py")

# --------------------------------------------------------------------------
# Fix 4: parser.py — regex pattern: {RESULTS} -> [RESULTS]
# --------------------------------------------------------------------------
print("\n[4/8] Fixing regex pattern in parser.py...")
with open("/app/harness/parser.py", "w") as f:
    f.write('''\
"""Parses simulation output."""
import re


def parse_results(log_path):
    """Parse simulation log for test results."""
    with open(log_path) as f:
        content = f.read()

    match = re.search(r'\\[RESULTS\\]\\s+(\\d+)\\s+pass,\\s+(\\d+)\\s+fail', content)

    if match:
        passed = int(match.group(1))
        failed = int(match.group(2))
        return {"total": passed + failed, "passed": passed, "failed": failed}

    return {"total": 0, "passed": 0, "failed": 0}
''')
print("  Fixed: /app/harness/parser.py")

# --------------------------------------------------------------------------
# Fix 5: scorer.py — denominator must exclude equivalent mutants
# --------------------------------------------------------------------------
print("\n[5/8] Fixing adequacy score formula in scorer.py...")
with open("/app/harness/scorer.py", "w") as f:
    f.write('''\
"""Computes mutation adequacy score."""


def compute_adequacy(results):
    """Compute the mutation adequacy score.

    Correct formula: killed / (total - equivalent)
    Equivalent mutants must be excluded from the denominator.
    """
    total = len(results)
    killed = sum(1 for r in results if r["status"] == "KILLED")
    equivalent = sum(1 for r in results if r["equivalent"])

    if total == 0 or (total - equivalent) == 0:
        score = 0.0
    else:
        score = killed / (total - equivalent)

    return {
        "total_mutants": total,
        "killed": killed,
        "equivalent": equivalent,
        "adequacy_score": score,
    }
''')
print("  Fixed: /app/harness/scorer.py")

# --------------------------------------------------------------------------
# Fix 6: reporter.py — include aggregate statistics in report
# --------------------------------------------------------------------------
print("\n[6/8] Fixing report generation in reporter.py...")
with open("/app/harness/reporter.py", "w") as f:
    f.write('''\
"""Generates the mutation adequacy report."""
import json
import os
from harness.config import RESULTS_DIR


def generate_report(mutation_results, adequacy):
    """Generate the final report JSON."""
    os.makedirs(RESULTS_DIR, exist_ok=True)

    report = {"mutations": mutation_results, "aggregate": adequacy}

    report_path = os.path.join(RESULTS_DIR, "report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    return report_path
''')
print("  Fixed: /app/harness/reporter.py")

# --------------------------------------------------------------------------
# Fix 7: Correct mutation equivalence classifications
# --------------------------------------------------------------------------
print("\n[7/8] Fixing mutation equivalence classifications...")

equivalence_corrections = {
    # SRA: arithmetic vs logical shift differs for negative values — NOT equivalent
    "mut_001.json": False,
    # SLT: signed vs unsigned comparison differs when signs differ — NOT equivalent
    "mut_002.json": False,
    # ADD: integer addition is commutative (a+b == b+a always) — IS equivalent
    "mut_004.json": True,
    # AND: bitwise AND is commutative (a&b == b&a always) — IS equivalent
    "mut_005.json": True,
}

for fname, correct_equiv in equivalence_corrections.items():
    path = os.path.join("/app/mutations", fname)
    with open(path) as f:
        data = json.load(f)
    old_val = data["equivalent"]
    data["equivalent"] = correct_equiv
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"  Fixed: {path} (equivalent: {old_val} -> {correct_equiv})")

# --------------------------------------------------------------------------
# Fix 8: Add targeted test vectors to kill surviving non-equivalent mutations
# --------------------------------------------------------------------------
print("\n[8/8] Adding mutation-killing test vectors to testbench...")

tb_path = "/app/tb/tb_alu.cpp"
with open(tb_path) as f:
    lines = f.readlines()

new_tests = [
    "\n",
    "    // --- Mutation-killing test vectors ---\n",
    "\n",
    '    // SUB tests (kills mut_003: SUB replaced with ADD)\n',
    '    check(dut, 10, 3, 1, 7, "SUB basic");\n',
    '    check(dut, 0, 1, 1, 0xFFFFFFFF, "SUB underflow");\n',
    "\n",
    '    // SRA with negative value (kills mut_001: arithmetic->logical shift)\n',
    '    check(dut, 0x80000000, 4, 7, 0xF8000000, "SRA negative");\n',
    "\n",
    '    // SLT with negative value (kills mut_002: signed->unsigned compare)\n',
    '    check(dut, 0xFFFFFFFF, 1, 3, 1, "SLT negative");\n',
    "\n",
    '    // SLL with large shift amount (kills mut_006: 5-bit->4-bit truncation)\n',
    '    check(dut, 1, 20, 2, 0x00100000, "SLL large shift");\n',
    "\n",
    '    // SLTU with equal operands (kills mut_007: < replaced with <=)\n',
    '    check(dut, 7, 7, 4, 0, "SLTU equal");\n',
    "\n",
    '    // OR with overlapping bits (kills mut_008: OR replaced with XOR)\n',
    '    check(dut, 0xFF00, 0xFF00, 8, 0xFF00, "OR overlap");\n',
]

output_lines = []
inserted = False
for line in lines:
    if not inserted and "[RESULTS]" in line and "printf" in line:
        output_lines.extend(new_tests)
        output_lines.append("\n")
        inserted = True
    output_lines.append(line)

if not inserted:
    print(f"  WARNING: Could not find RESULTS printf in {tb_path}")
else:
    with open(tb_path, "w") as f:
        f.writelines(output_lines)
    print(f"  Fixed: {tb_path} (added 7 test vectors)")

print("\n" + "=" * 60)
print("All fixes applied.")
print("=" * 60)
