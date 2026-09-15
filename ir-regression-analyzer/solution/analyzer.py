#!/usr/bin/env python3

"""
LLVM pass pipeline regression analyzer.

Runs opt-18 and llc-18 to measure IR and assembly instruction counts under
baseline and candidate pipelines, incrementally runs candidate pipeline
prefixes to attribute regressions to individual passes, and writes a
structured JSON report.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile


FUNC_DEF_RE = re.compile(
    r'^define\b.*?(@(?:"[^"]+"|[-a-zA-Z$._0-9]+))\s*\('
)
LABEL_RE = re.compile(
    r'^(?:[a-zA-Z$._][-a-zA-Z$._0-9]*|\d+|"[^"]*"):\s*(?:;.*)?$'
)


def find_tool(name):
    """Locate an LLVM-18 tool binary."""
    candidates = [
        f"/usr/lib/llvm-18/bin/{name}",
        f"/usr/bin/{name}-18",
    ]
    w = shutil.which(f"{name}-18")
    if w:
        candidates.append(w)
    w = shutil.which(name)
    if w:
        candidates.append(w)
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    print(f"Error: could not find LLVM tool '{name}'", file=sys.stderr)
    sys.exit(1)


def run_opt(opt_bin, pipeline, input_file, output_file):
    cmd = [opt_bin, f"-passes={pipeline}", "-S", input_file, "-o", output_file]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"opt failed with pipeline '{pipeline}':\n{result.stderr}", file=sys.stderr)
        sys.exit(1)


def run_llc(llc_bin, input_file, output_file, target_triple):
    cmd = [llc_bin, f"-mtriple={target_triple}", "-O2", input_file, "-o", output_file]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        print(f"llc failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)


def strip_ir_comment(line):
    """Remove trailing ; comment, respecting string literals."""
    in_str = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_str = not in_str
        elif ch == ';' and not in_str:
            return line[:i].rstrip()
    return line


def count_ir_per_function(filepath):
    """Count IR instructions per function in an LLVM IR file."""
    counts = {}
    with open(filepath) as f:
        lines = f.readlines()

    idx = 0
    while idx < len(lines):
        line = lines[idx].rstrip("\n")
        m = FUNC_DEF_RE.match(line.strip())
        if m:
            func_name = m.group(1)
            idx += 1
            count = 0
            while idx < len(lines):
                body = lines[idx].strip()
                if body == "}":
                    break
                if not body or body.startswith(";"):
                    idx += 1
                    continue
                code = strip_ir_comment(body)
                if not code:
                    idx += 1
                    continue
                if LABEL_RE.match(code):
                    idx += 1
                    continue
                count += 1
                idx += 1
            counts[func_name] = count
        idx += 1
    return counts


def count_asm_per_function(filepath):
    """Count assembly instructions per function in llc output."""
    counts = {}
    cur_func = None
    count = 0

    with open(filepath) as f:
        for line in f:
            stripped = line.strip()

            if stripped.startswith(".Lfunc_end"):
                if cur_func is not None:
                    counts[cur_func] = count
                cur_func = None
                count = 0
                continue

            if (
                line
                and not line[0].isspace()
                and stripped.endswith(":")
                and not stripped.startswith(".")
                and not stripped.startswith("#")
            ):
                cur_func = stripped.rstrip(":")
                count = 0
                continue

            if cur_func is not None and line and line[0].isspace():
                if (
                    stripped
                    and not stripped.startswith(".")
                    and not stripped.startswith("#")
                    and not stripped.endswith(":")
                ):
                    count += 1

    if cur_func is not None:
        counts[cur_func] = count
    return counts


def main():
    opt_bin = find_tool("opt")
    llc_bin = find_tool("llc")

    with open("/app/config.json") as f:
        config = json.load(f)

    work = tempfile.mkdtemp(prefix="llvm_analyze_")

    baseline_ir_path = os.path.join(work, "baseline.ll")
    candidate_ir_path = os.path.join(work, "candidate.ll")
    baseline_asm_path = os.path.join(work, "baseline.s")
    candidate_asm_path = os.path.join(work, "candidate.s")

    # Run optimization pipelines
    print("Running baseline pipeline...")
    run_opt(opt_bin, config["baseline_pipeline"], "/app/module.ll", baseline_ir_path)
    print("Running candidate pipeline...")
    run_opt(opt_bin, config["candidate_pipeline"], "/app/module.ll", candidate_ir_path)

    # Count IR instructions
    b_ir = count_ir_per_function(baseline_ir_path)
    c_ir = count_ir_per_function(candidate_ir_path)

    # Generate and count assembly
    print("Generating baseline assembly...")
    run_llc(llc_bin, baseline_ir_path, baseline_asm_path, config["target_triple"])
    print("Generating candidate assembly...")
    run_llc(llc_bin, candidate_ir_path, candidate_asm_path, config["target_triple"])

    b_asm = count_asm_per_function(baseline_asm_path)
    c_asm = count_asm_per_function(candidate_asm_path)

    # Build per-function data
    all_funcs = sorted(set(b_ir) | set(c_ir))
    per_function = {}
    for func in all_funcs:
        b_count = b_ir.get(func, 0)
        c_count = c_ir.get(func, 0)
        delta_ir = c_count - b_count

        asm_name = func.lstrip("@")
        b_a = b_asm.get(asm_name, 0)
        c_a = c_asm.get(asm_name, 0)
        delta_asm = c_a - b_a

        if delta_ir > 0:
            status = "regressed"
        elif delta_ir < 0:
            status = "improved"
        else:
            status = "unchanged"

        per_function[func] = {
            "baseline_ir_count": b_count,
            "candidate_ir_count": c_count,
            "ir_delta": delta_ir,
            "status": status,
            "baseline_asm_count": b_a,
            "candidate_asm_count": c_a,
            "asm_delta": delta_asm,
        }

    # Derive pass names and prefixes from candidate pipeline
    pass_names = [p.strip() for p in config["candidate_pipeline"].split(",")]
    prefixes = [",".join(pass_names[:i + 1]) for i in range(len(pass_names))]

    # Attribute regressions to earliest responsible pass
    print("Attributing regressions...")
    bisection = {}
    regressed = {fn for fn in all_funcs if per_function[fn]["status"] == "regressed"}

    for idx, prefix in enumerate(prefixes):
        if not regressed:
            break
        pfx_path = os.path.join(work, f"prefix_{idx}.ll")
        run_opt(opt_bin, prefix, "/app/module.ll", pfx_path)
        pfx_counts = count_ir_per_function(pfx_path)

        resolved = set()
        for fn in regressed:
            baseline_count = per_function[fn]["baseline_ir_count"]
            if pfx_counts.get(fn, 0) > baseline_count:
                bisection[fn] = {
                    "regressing_pass_index": idx,
                    "regressing_pass_name": pass_names[idx],
                }
                resolved.add(fn)
        regressed -= resolved

    # Summary
    num_regressed = sum(1 for d in per_function.values() if d["status"] == "regressed")
    num_improved = sum(1 for d in per_function.values() if d["status"] == "improved")
    num_unchanged = sum(1 for d in per_function.values() if d["status"] == "unchanged")

    summary = {
        "total_functions": len(per_function),
        "num_regressed": num_regressed,
        "num_improved": num_improved,
        "num_unchanged": num_unchanged,
        "total_ir_delta": sum(d["ir_delta"] for d in per_function.values()),
        "total_asm_delta": sum(d["asm_delta"] for d in per_function.values()),
        "unique_regressing_passes": sorted(set(
            b["regressing_pass_name"] for b in bisection.values()
        )),
    }

    report = {
        "per_function": per_function,
        "bisection": bisection,
        "summary": summary,
    }

    with open("/app/report.json", "w") as f:
        json.dump(report, f, indent=2)

    print(f"Report written to /app/report.json")
    print(f"Functions: {len(per_function)}, Regressed: {num_regressed}, "
          f"Improved: {num_improved}, Unchanged: {num_unchanged}")
    if bisection:
        passes = summary["unique_regressing_passes"]
        print(f"Regressing passes: {', '.join(passes)}")

    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
