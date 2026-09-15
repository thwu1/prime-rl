#!/usr/bin/env python3
"""
Compiler optimization analysis tool.
Compiles target.c at various optimization levels and inspects the
resulting x86-64 assembly to answer each question in schema.json.

"""

import json
import re
import subprocess
import sys


def compile_to_asm(source, flags, output):
    cmd = (
        ["gcc"]
        + flags.split()
        + ["-S", "-masm=intel", "-fno-asynchronous-unwind-tables",
           "-o", output, source]
    )
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"Compilation failed: {r.stderr}", file=sys.stderr)
        sys.exit(1)


def read(path):
    with open(path) as f:
        return f.read()


def extract_function(asm, name):
    lines = asm.split("\n")
    collecting = False
    buf = []
    for line in lines:
        s = line.strip()
        if s == f"{name}:":
            collecting = True
            continue
        if collecting:
            if re.search(rf"\.size\s+{re.escape(name)}\b", line):
                break
            if s.endswith(":") and not s.startswith(".L") and not s.startswith("."):
                break
            buf.append(line)
    return "\n".join(buf)


def extract_loop_body(func_asm):
    lines = func_asm.split("\n")
    labels = {}
    for i, line in enumerate(lines):
        s = line.strip()
        m = re.match(r"(\.L\w+):$", s)
        if m:
            labels[m.group(1)] = i

    for i in range(len(lines) - 1, -1, -1):
        s = lines[i].strip()
        m = re.match(r"j\w+\s+(\.L\w+)", s)
        if m:
            target = m.group(1)
            if target in labels and labels[target] < i:
                return "\n".join(lines[labels[target] + 1 : i])
    return func_asm


def main():
    src = "/app/target.c"

    # Compile at the three relevant optimization levels
    compile_to_asm(src, "-O2", "/tmp/target_O2.s")
    compile_to_asm(src, "-O3 -mavx2", "/tmp/target_O3.s")
    compile_to_asm(src, "-O3 -mavx2 -ffast-math", "/tmp/target_fast.s")

    asm_O2 = read("/tmp/target_O2.s")
    asm_O3 = read("/tmp/target_O3.s")
    asm_fast = read("/tmp/target_fast.s")

    report = {}

    # --- divide_by_7 ---
    div7 = extract_function(asm_O2, "divide_by_7")
    report["divide_by_7"] = {
        "has_div_instruction": bool(re.search(r"\b[i]?div\b", div7, re.I)),
        "has_mul_instruction": bool(re.search(r"\bi?mul\b", div7, re.I)),
    }

    # --- modulo_13 ---
    mod13 = extract_function(asm_O2, "modulo_13")
    report["modulo_13"] = {
        "has_div_instruction": bool(re.search(r"\b[i]?div\b", mod13, re.I)),
        "has_mul_instruction": bool(re.search(r"\bi?mul\b", mod13, re.I)),
    }

    # --- accumulate ---
    acc = extract_function(asm_O2, "accumulate")
    acc_loop = extract_loop_body(acc)
    report["accumulate"] = {
        "has_memory_write_in_loop_body": bool(
            re.search(r"mov\s+DWORD\s+PTR\s+\[", acc_loop, re.I)
        ),
        "optimization_blocker": (
            "Type-based pointer aliasing: the parameter int *total and the "
            "elements accessed through const int *data share the same base "
            "type (int). Under C's strict aliasing rules, an int* is "
            "permitted to alias another int*, so the compiler must assume "
            "that writing through *total could affect a later read of "
            "data[i]. This forces a store-reload of *total every iteration, "
            "preventing the compiler from keeping the accumulator in a "
            "register across loop iterations."
        ),
    }

    # --- fill_multiples ---
    fm = extract_function(asm_O2, "fill_multiples")
    fm_loop = extract_loop_body(fm)
    report["fill_multiples"] = {
        "has_imul_in_loop_body": bool(re.search(r"\bimul\b", fm_loop, re.I)),
        "has_compiler_introduced_add": bool(re.search(r"\badd\b", fm_loop, re.I)),
    }

    # --- sum_floats ---
    sf_O3 = extract_function(asm_O3, "sum_floats")
    sf_fast = extract_function(asm_fast, "sum_floats")
    report["sum_floats"] = {
        "vectorized_at_O3_avx2": bool(
            re.search(r"\bv?addps\b", sf_O3, re.I)
        ),
        "vectorized_at_O3_avx2_ffast_math": bool(
            re.search(r"\bv?addps\b", sf_fast, re.I)
        ),
        "vectorization_blocker": (
            "Floating-point addition is not associative under IEEE 754: "
            "(a + b) + c can differ from a + (b + c) due to intermediate "
            "rounding. SIMD vectorization of a reduction loop requires "
            "splitting the single accumulator into multiple independent "
            "partial sums that are combined at the end, which reorders the "
            "additions. Without -ffast-math (which enables "
            "-fassociative-math), the compiler must preserve the strict "
            "left-to-right evaluation order mandated by the C standard and "
            "cannot legally apply this transformation."
        ),
    }

    # --- categorize ---
    cat = extract_function(asm_O2, "categorize")
    has_indirect_jmp = bool(
        re.search(r"jmp\s+.*PTR\s*\[", cat, re.I)
    ) or bool(
        re.search(r"jmp\s+r[a-d]x\b", cat, re.I)
    )
    report["categorize"] = {
        "uses_jump_table": has_indirect_jmp,
        "uses_data_lookup_table": bool(re.search(r"CSWTCH", cat, re.I)),
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("Analysis complete — /app/report.json written.")


if __name__ == "__main__":
    main()
