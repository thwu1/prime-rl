#!/usr/bin/env python3
"""
Convergence analysis for 2D photonic crystal TM band structure.

Determines the minimum Fourier truncation order (resolution) at which the
first TM gap percentage converges to within a target relative error of a
reference value parsed from MPB output files.
"""
import json
import re
import sys

sys.path.insert(0, "/app")

from solve_bands import compute_bands, load_materials_db


def parse_reference_gap(filepath):
    """Parse an MPB reference output file to extract the first TM gap percentage.

    Looks for lines of the form:
      Gap from band 1 (value) to band 2 (value), percentage%
    """
    with open(filepath) as f:
        content = f.read()

    pattern = (
        r'Gap from band (\d+) \(([0-9.]+(?:e[+-]?\d+)?)\) '
        r'to band (\d+) \(([0-9.]+(?:e[+-]?\d+)?)\),\s*'
        r'([0-9.]+(?:e[+-]?\d+)?)%'
    )
    matches = re.findall(pattern, content)

    for match in matches:
        from_band = int(match[0])
        to_band = int(match[2])
        gap_pct = float(match[4])
        if from_band == 1 and to_band == 2:
            return gap_pct

    raise ValueError(f"No band 1->2 gap found in {filepath}")


def run_convergence(config):
    """Run convergence analysis over a range of resolutions."""
    target_accuracy = float(config["target_accuracy"])
    reference_file = config["reference_file"]

    ref_gap = parse_reference_gap(reference_file)

    materials_db = load_materials_db()

    base_config = {
        "lattice_type": config["lattice_type"],
        "rod_material": config["rod_material"],
        "background_material": config["background_material"],
        "radius": float(config["radius"]),
        "num_bands": int(config.get("num_bands", 8)),
        "k_interp": int(config.get("k_interp", 4)),
    }

    resolutions = [4, 8, 12, 16, 20, 24, 28, 32]
    series = []
    min_resolution = None
    converged_gap = None
    converged_error = None

    for res in resolutions:
        cfg = dict(base_config, resolution=res)
        results = compute_bands(cfg, materials_db=materials_db)

        gap_pct = 0.0
        for g in results["gaps"]:
            if g["from_band"] == 1 and g["to_band"] == 2:
                gap_pct = g["gap_percent"]
                break

        error = abs(gap_pct - ref_gap) / ref_gap if ref_gap > 0 else float('inf')

        series.append({
            "resolution": res,
            "gap_percent": gap_pct,
            "error": error,
        })

        if min_resolution is None and error <= target_accuracy:
            min_resolution = res
            converged_gap = gap_pct
            converged_error = error

    if min_resolution is None:
        min_resolution = resolutions[-1]
        converged_gap = series[-1]["gap_percent"]
        converged_error = series[-1]["error"]

    return {
        "min_resolution": min_resolution,
        "converged_gap_percent": converged_gap,
        "reference_gap_percent": ref_gap,
        "relative_error": converged_error,
        "resolution_series": series,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 convergence.py <config.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        config = json.load(f)

    result = run_convergence(config)

    with open("/app/convergence_result.json", "w") as f:
        json.dump(result, f, indent=2)

    print(f"Reference gap: {result['reference_gap_percent']:.4f}%")
    print(f"Min resolution: {result['min_resolution']}")
    print(f"Converged gap: {result['converged_gap_percent']:.4f}%")
    print(f"Relative error: {result['relative_error']:.6f}")
    print("\nResolution series:")
    for e in result["resolution_series"]:
        print(f"  res={e['resolution']:3d}: gap={e['gap_percent']:.4f}%, error={e['error']:.6f}")
