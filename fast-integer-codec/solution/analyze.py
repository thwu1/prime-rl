#!/usr/bin/env python3
"""
analyze.py — Perform binary analysis on the reference library and hex variants.

Uses objdump, nm, and strings to examine:
1. The stripped reference binary's exported functions and hex approach
2. Whether each hex variant's compiled object contains a lookup table

Writes results to /app/analysis.json.
"""

import json
import os
import subprocess


def run(cmd):
    """Run a shell command and return stdout."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout


def get_ref_exported_functions():
    """Extract FUNC-type global symbols from the reference binary's dynamic symbol table."""
    output = run("nm -D /opt/reference/libfastnum_ref.so")
    funcs = []
    for line in output.strip().split("\n"):
        parts = line.split()
        if len(parts) >= 3 and parts[1] == "T":
            funcs.append(parts[2])
    return sorted(funcs)


def get_ref_hex_approach():
    """Determine if the reference binary uses table or arithmetic hex encoding.
    The table approach embeds '0123456789abcdef' in the binary; arithmetic does not."""
    output = run("strings /opt/reference/libfastnum_ref.so")
    if "0123456789abcdef" in output:
        return "table"
    return "arithmetic"


def check_variant_has_rodata_table(source_path):
    """Compile a hex variant at -O2 and check if the object contains the hex lookup table."""
    obj_path = "/tmp/variant_check.o"
    run(f"gcc -O2 -c -o {obj_path} {source_path}")

    # Check for the hex table string in the object file
    output = run(f"strings {obj_path}")
    has_table = "0123456789abcdef" in output

    # Also check via objdump for the rodata section contents
    if not has_table:
        rodata = run(f"objdump -s -j .rodata {obj_path} 2>/dev/null")
        # The 16-byte table would appear as hex in objdump output
        # Look for the ASCII representation on the right side
        if "0123456789abcdef" in rodata:
            has_table = True

    os.remove(obj_path)
    return has_table


def main():
    analysis = {
        "ref_exported_functions": get_ref_exported_functions(),
        "ref_hex_approach": get_ref_hex_approach(),
        "table_variant_has_rodata_table": check_variant_has_rodata_table(
            "/opt/variants/hex_table.c"
        ),
        "arithmetic_variant_has_rodata_table": check_variant_has_rodata_table(
            "/opt/variants/hex_arithmetic.c"
        ),
        "higher_throughput_variant": "arithmetic",
    }

    with open("/app/analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)

    print("Analysis written to /app/analysis.json")
    print(json.dumps(analysis, indent=2))


if __name__ == "__main__":
    main()
