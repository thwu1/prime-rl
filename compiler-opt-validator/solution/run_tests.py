#!/usr/bin/env python3
"""
Compile and run generated C tests at multiple optimization levels.
Handles single-file tests and separate-compilation calling convention tests.
"""
import os
import subprocess
import json
import glob
import tempfile

TEST_DIR = "/app/tests"
RAW_RESULTS = "/app/raw_results.json"
OPT_LEVELS = ["-O0", "-O1", "-O2", "-O3"]


def run_single_file(c_file, category, opt):
    """Compile a single .c file and run it."""
    with tempfile.NamedTemporaryFile(suffix="", delete=False) as f:
        binary = f.name
    try:
        comp = subprocess.run(
            ["gcc", opt, "-o", binary, c_file, "-lm", "-w"],
            capture_output=True, text=True, timeout=30,
        )
        if comp.returncode != 0:
            return {
                "file": os.path.basename(c_file),
                "category": category,
                "opt_level": opt,
                "compile_ok": False,
                "exit_code": -1,
            }
        run = subprocess.run(
            [binary], capture_output=True, text=True, timeout=10
        )
        return {
            "file": os.path.basename(c_file),
            "category": category,
            "opt_level": opt,
            "compile_ok": True,
            "exit_code": run.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "file": os.path.basename(c_file),
            "category": category,
            "opt_level": opt,
            "compile_ok": True,
            "exit_code": -2,
        }
    finally:
        if os.path.exists(binary):
            os.unlink(binary)


def run_call_conv_pair(prefix, callee_c, caller_c, opt):
    """Compile callee and caller separately, link, and run."""
    with tempfile.NamedTemporaryFile(suffix="", delete=False) as f:
        binary = f.name
    callee_o = binary + "_callee.o"
    caller_o = binary + "_caller.o"
    basename = os.path.basename(prefix)
    try:
        c1 = subprocess.run(
            ["gcc", opt, "-c", callee_c, "-o", callee_o, "-w"],
            capture_output=True, text=True, timeout=30,
        )
        c2 = subprocess.run(
            ["gcc", opt, "-c", caller_c, "-o", caller_o, "-w"],
            capture_output=True, text=True, timeout=30,
        )
        if c1.returncode != 0 or c2.returncode != 0:
            return {
                "file": basename,
                "category": "call_conv",
                "opt_level": opt,
                "compile_ok": False,
                "exit_code": -1,
            }
        link = subprocess.run(
            ["gcc", callee_o, caller_o, "-o", binary, "-lm", "-w"],
            capture_output=True, text=True, timeout=30,
        )
        if link.returncode != 0:
            return {
                "file": basename,
                "category": "call_conv",
                "opt_level": opt,
                "compile_ok": False,
                "exit_code": -1,
            }
        run = subprocess.run(
            [binary], capture_output=True, text=True, timeout=10
        )
        return {
            "file": basename,
            "category": "call_conv",
            "opt_level": opt,
            "compile_ok": True,
            "exit_code": run.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "file": basename,
            "category": "call_conv",
            "opt_level": opt,
            "compile_ok": True,
            "exit_code": -2,
        }
    finally:
        for p in [binary, callee_o, caller_o]:
            if os.path.exists(p):
                os.unlink(p)


def main():
    results = []

    # Single-file categories
    for cat in ["irr_flow", "alias", "volatile_opt", "int_promo"]:
        cat_dir = os.path.join(TEST_DIR, cat)
        if not os.path.isdir(cat_dir):
            continue
        for c_file in sorted(glob.glob(os.path.join(cat_dir, "*.c"))):
            for opt in OPT_LEVELS:
                results.append(run_single_file(c_file, cat, opt))

    # Calling convention: separate compilation
    cc_dir = os.path.join(TEST_DIR, "call_conv")
    if os.path.isdir(cc_dir):
        callers = sorted(glob.glob(os.path.join(cc_dir, "*_caller.c")))
        for caller in callers:
            prefix = caller.replace("_caller.c", "")
            callee = prefix + "_callee.c"
            if not os.path.exists(callee):
                continue
            for opt in OPT_LEVELS:
                results.append(run_call_conv_pair(prefix, callee, caller, opt))

    with open(RAW_RESULTS, "w") as f:
        json.dump(results, f, indent=2)

    total = len(results)
    passed = sum(1 for r in results if r["exit_code"] == 0)
    print(f"Ran {total} compilations/executions, {passed} passed")


if __name__ == "__main__":
    main()
