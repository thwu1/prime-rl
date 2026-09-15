#!/usr/bin/env python3
"""Generate optimization report as JSON array."""

import json
import os
import re
import subprocess


def count_target_instructions(tac_text):
    """Count instructions in the target function."""
    lines = tac_text.strip().split("\n")
    in_target = False
    count = 0
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        func_match = re.match(r"function\s+(\w+)\s*\(", stripped)
        if func_match:
            in_target = func_match.group(1) == "target"
            continue
        if not in_target:
            continue
        if re.match(r"^\w+\s*:\s*$", stripped):
            continue
        count += 1
    return count


def main():
    results = []
    output_dir = "output"
    for fn in sorted(os.listdir(output_dir)):
        if not fn.endswith(".tac"):
            continue
        name = fn[:-4]
        orig_path = os.path.join("programs", fn)
        opt_path = os.path.join(output_dir, fn)

        r1 = subprocess.run(
            ["python3", "interpreter.py", orig_path, "target"],
            capture_output=True, text=True, timeout=30,
        )
        original_ret = int(r1.stdout.strip()) if r1.returncode == 0 else None

        r2 = subprocess.run(
            ["python3", "interpreter.py", opt_path, "target"],
            capture_output=True, text=True, timeout=30,
        )
        optimized_ret = int(r2.stdout.strip()) if r2.returncode == 0 else None

        r3 = subprocess.run(
            ["python3", "tac_check.py", opt_path],
            capture_output=True, text=True, timeout=30,
        )
        valid = r3.returncode == 0

        with open(opt_path) as f:
            tac_text = f.read()
        instr_count = count_target_instructions(tac_text)

        results.append({
            "program": name,
            "original_ret": original_ret,
            "optimized_ret": optimized_ret,
            "match": original_ret == optimized_ret,
            "instruction_count": instr_count,
            "valid": valid,
        })

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
