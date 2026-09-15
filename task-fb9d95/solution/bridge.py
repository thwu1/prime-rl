#!/usr/bin/env python3
"""
WGSL-to-C Bridge Driver

Parses all WGSL shaders, generates C11 struct code, compiles with gcc,
and produces a conformance report comparing reference_layouts.json
against spec-correct values.
"""

import json
import os
import subprocess
import sys

from wgsl_parser import parse_wgsl_file
from c_codegen import generate_c_struct, compute_struct_layout


def main():
    # Parse all shaders
    all_structs = {}
    shader_dir = "/app/shaders"
    for fname in sorted(os.listdir(shader_dir)):
        if fname.endswith(".wgsl"):
            for s in parse_wgsl_file(os.path.join(shader_dir, fname)):
                all_structs[s.name] = s

    # Read reference
    with open("/app/reference_layouts.json") as f:
        reference = json.load(f)

    os.makedirs("/app/generated", exist_ok=True)
    report = {}

    for struct_name, ref_info in reference.items():
        addr = ref_info["address_space"]
        sdef = all_structs[struct_name]

        # Generate C
        c_code = generate_c_struct(sdef, addr, all_structs)
        c_path = f"/app/generated/{struct_name}.c"
        with open(c_path, "w") as f:
            f.write(c_code)

        # Compile
        binary = f"/app/generated/{struct_name}"
        comp = subprocess.run(
            ["gcc", "-std=c11", "-Wall", "-Werror", "-o", binary, c_path],
            capture_output=True, text=True)
        if comp.returncode != 0:
            print(f"COMPILE FAIL: {struct_name}\n{comp.stderr}", file=sys.stderr)
            continue

        # Run
        run = subprocess.run([binary], capture_output=True, text=True)
        if "ALL_LAYOUT_CHECKS_PASSED" in run.stdout:
            print(f"GCC PASS: {struct_name}")
        else:
            print(f"RUN FAIL: {struct_name}\n{run.stdout}", file=sys.stderr)
            continue

        # Compare against spec
        correct = compute_struct_layout(sdef, addr, all_structs)
        discrepancies = []

        if ref_info["alignment"] != correct["alignment"]:
            discrepancies.append({
                "field": "alignment",
                "reference": ref_info["alignment"],
                "correct": correct["alignment"]
            })
        if ref_info["size"] != correct["size"]:
            discrepancies.append({
                "field": "size",
                "reference": ref_info["size"],
                "correct": correct["size"]
            })
        for mname, mref in ref_info["members"].items():
            mc = correct["members"][mname]
            for key in ("offset", "alignment", "size"):
                if mref[key] != mc[key]:
                    discrepancies.append({
                        "field": f"members.{mname}.{key}",
                        "reference": mref[key],
                        "correct": mc[key]
                    })

        status = "FAIL" if discrepancies else "PASS"
        report[struct_name] = {"status": status, "discrepancies": discrepancies}

        # Fix reference in place
        ref_info["alignment"] = correct["alignment"]
        ref_info["size"] = correct["size"]
        for mname in ref_info["members"]:
            mc = correct["members"][mname]
            for key in ("offset", "alignment", "size"):
                ref_info["members"][mname][key] = mc[key]

    # Write corrected reference
    with open("/app/reference_layouts.json", "w") as f:
        json.dump(reference, f, indent=2)
    print("Corrected reference_layouts.json")

    # Write conformance report
    with open("/app/conformance_report.json", "w") as f:
        json.dump(report, f, indent=2)

    print("\nConformance report:")
    for name, info in report.items():
        n = len(info["discrepancies"])
        tag = f" ({n} discrepancies)" if n else ""
        print(f"  {name}: {info['status']}{tag}")


if __name__ == "__main__":
    main()
