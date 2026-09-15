#!/usr/bin/env python3
"""Analyze benchmark results and compose the optimal rotation library.

This script:
1. Queries the SQLite benchmark database to compute per-function max errors
2. Determines which libraries are correct/flawed for each function
3. Writes evaluation.json with the analysis
4. Writes optimal_lib.py that imports from the best sources
"""

import sqlite3
import json

DB_PATH = "/app/rotations.db"
FUNCTIONS = [
    "quaternion_to_matrix",
    "matrix_to_quaternion",
    "axis_angle_to_matrix",
    "matrix_to_euler_angles",
    "geodesic_distance",
    "slerp",
]
LIBRARIES = ["alpha", "beta", "gamma"]
ERROR_THRESHOLD = 1e-6


def analyze():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    function_analysis = {}
    optimal_sources = {}

    for fn in FUNCTIONS:
        correct = []
        flawed = []
        best_lib = None
        best_max_err = float("inf")

        for lib in LIBRARIES:
            row = c.execute(
                "SELECT MAX(error) FROM benchmark_results WHERE library=? AND func=?",
                (lib, fn)
            ).fetchone()
            max_err = row[0] if row[0] is not None else 999.0

            if max_err < ERROR_THRESHOLD:
                correct.append(lib)
                if max_err < best_max_err:
                    best_max_err = max_err
                    best_lib = lib
            else:
                flawed.append(lib)

        function_analysis[fn] = {
            "correct_libraries": sorted(correct),
            "flawed_libraries": sorted(flawed),
        }
        optimal_sources[fn] = best_lib if best_lib else correct[0] if correct else LIBRARIES[0]

    conn.close()

    evaluation = {
        "function_analysis": function_analysis,
        "optimal_sources": optimal_sources,
    }

    with open("/app/evaluation.json", "w") as f:
        json.dump(evaluation, f, indent=2)
    print("Wrote /app/evaluation.json")

    return optimal_sources


def compose_optimal(optimal_sources):
    """Write optimal_lib.py that imports from the best sources."""

    # Map function -> library module name
    imports = {}
    for fn, lib in optimal_sources.items():
        mod = f"lib_{lib}"
        if mod not in imports:
            imports[mod] = []
        imports[mod].append(fn)

    # Pick a base library for shared utilities (prefer one already used)
    base_mod = f"lib_{optimal_sources['quaternion_to_matrix']}"

    lines = [
        '"""Optimal rotation conversion library composed from best implementations."""',
        "import sys",
        "sys.path.insert(0, '/app')",
        "",
    ]

    # Import the varying functions from their best sources
    for mod in sorted(imports.keys()):
        fns = sorted(imports[mod])
        lines.append(f"from {mod} import {', '.join(fns)}")

    lines.append("")

    # Import shared utilities from the base library
    shared_fns = [
        "standardize_quaternion",
        "axis_angle_to_quaternion",
        "quaternion_to_axis_angle",
        "euler_angles_to_matrix",
        "rotation_6d_to_matrix",
        "matrix_to_rotation_6d",
        "random_rotation_matrix",
    ]
    lines.append(f"from {base_mod} import (")
    for fn in shared_fns:
        lines.append(f"    {fn},")
    lines.append(")")
    lines.append("")

    # Define matrix_to_axis_angle using the correct matrix_to_quaternion
    lines.append("")
    lines.append("def matrix_to_axis_angle(R):")
    lines.append('    """Convert rotation matrix to axis-angle via quaternion."""')
    lines.append("    return quaternion_to_axis_angle(matrix_to_quaternion(R))")
    lines.append("")

    with open("/app/optimal_lib.py", "w") as f:
        f.write("\n".join(lines))
    print("Wrote /app/optimal_lib.py")


if __name__ == "__main__":
    sources = analyze()
    compose_optimal(sources)
    print("\nOptimal sources:")
    for fn, lib in sources.items():
        print(f"  {fn}: {lib}")
