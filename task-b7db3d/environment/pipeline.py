"""Main pipeline orchestrator.

Steps:
1. Build the C shared library (make)
2. Run convergence analysis -> convergence_report.json
3. Generate multi-model DFG LUT -> dfg_lut.json

Usage: python3 /app/pipeline.py
"""
import subprocess
import json
import os
import sys

LUT_SIZE = 16


def build_library():
    """Build libbrdf.so by running make in /app."""
    subprocess.run(['make', '-C', '/app', 'clean'], capture_output=True)
    result = subprocess.run(['make', '-C', '/app'], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Build failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    if not os.path.isfile('/app/libbrdf.so'):
        print("ERROR: libbrdf.so not produced", file=sys.stderr)
        sys.exit(1)
    print("Library built successfully.")


def generate_lut():
    """Generate 16x16 multi-model DFG LUT.

    Output format:
    {
        "size": 16,
        "standard": [[dfg_x, dfg_y], ...],  // 16x16 array of [x,y] pairs
        "cloth": [[value, ...], ...]         // 16x16 array of floats
    }

    NoV = (i + 0.5) / size, roughness = (j + 0.5) / size
    Clamp NoV and roughness to minimum 0.01.
    Use adequate samples per entry for standard and cloth DFG.
    """
    raise NotImplementedError


if __name__ == '__main__':
    build_library()

    sys.path.insert(0, '/app')
    from convergence import generate_report

    # Convergence analysis
    report = generate_report()
    with open('/app/convergence_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print("Convergence report written.")

    # LUT generation
    generate_lut()
    print("DFG LUT written.")
    print("Pipeline complete.")
