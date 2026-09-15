#!/usr/bin/env python3
"""
Solver for the geodetic pipeline task.

Uses PROJ CLI tools (projinfo, gie, cs2cs) to identify correct CRS parameters,
fix broken gie test files, and compute a chained coordinate transformation.
"""

import subprocess
import os
import csv
import re
import sys


def run_cmd(cmd, input_text=None):
    """Run a command and return (stdout, stderr, returncode)."""
    result = subprocess.run(
        cmd, capture_output=True, text=True, input=input_text, timeout=60
    )
    return result.stdout, result.stderr, result.returncode


def get_proj_string(epsg_code):
    """Get the PROJ string for an EPSG code via projinfo."""
    stdout, _, _ = run_cmd(["projinfo", f"EPSG:{epsg_code}", "-o", "PROJ"])
    for line in stdout.split("\n"):
        line = line.strip()
        if line.startswith("+proj="):
            line = re.sub(r"\+type=crs\b", "", line)
            line = re.sub(r"\+no_defs\b", "", line)
            return line.strip()
    return None


def extract_param(proj_string, name):
    """Extract a named parameter value from a PROJ string."""
    match = re.search(rf"\+{name}=([^\s+]+)", proj_string)
    return match.group(1) if match else None


# ── Scenario A: Oblique Stereographic (Netherlands) ──────────────────────────

def fix_scenario_a():
    print("=== Scenario A: Oblique Stereographic ===")

    # Look up the correct EPSG:28992 (Amersfoort / RD New) definition
    proj_str = get_proj_string(28992)
    print(f"  EPSG:28992 -> {proj_str}")

    # The correct scale factor for RD New
    correct_k = extract_param(proj_str, "k") or extract_param(proj_str, "k_0")
    print(f"  Correct scale factor: {correct_k}")

    with open("/app/scenario_a.gie") as f:
        content = f.read()

    # Replace the wrong scale factor with the correct one
    content = re.sub(r"\+k=[\d.]+", f"+k={correct_k}", content)

    with open("/app/results/scenario_a_fixed.gie", "w") as f:
        f.write(content)

    _, stderr, rc = run_cmd(["gie", "/app/results/scenario_a_fixed.gie"])
    print(f"  gie exit code: {rc}")
    if rc != 0:
        print(f"  FAILED: {stderr}")
    return rc == 0


# ── Scenario B: Albers Equal Area (Australia) ────────────────────────────────

def fix_scenario_b():
    print("\n=== Scenario B: Albers Equal Area ===")

    # Look up EPSG:3577 (GDA94 / Australian Albers)
    proj_str = get_proj_string(3577)
    print(f"  EPSG:3577 -> {proj_str}")

    correct_lon_0 = extract_param(proj_str, "lon_0")
    correct_lat_1 = extract_param(proj_str, "lat_1")
    correct_lat_2 = extract_param(proj_str, "lat_2")
    print(f"  Correct lon_0={correct_lon_0}, lat_1={correct_lat_1}, lat_2={correct_lat_2}")

    with open("/app/scenario_b.gie") as f:
        content = f.read()

    content = re.sub(r"\+lon_0=[\d.-]+", f"+lon_0={correct_lon_0}", content)
    content = re.sub(r"\+lat_1=[\d.-]+", f"+lat_1={correct_lat_1}", content)
    content = re.sub(r"\+lat_2=[\d.-]+", f"+lat_2={correct_lat_2}", content)

    with open("/app/results/scenario_b_fixed.gie", "w") as f:
        f.write(content)

    _, stderr, rc = run_cmd(["gie", "/app/results/scenario_b_fixed.gie"])
    print(f"  gie exit code: {rc}")
    if rc != 0:
        print(f"  FAILED: {stderr}")
    return rc == 0


# ── Scenario C: LAEA Europe ──────────────────────────────────────────────────

def fix_scenario_c():
    print("\n=== Scenario C: LAEA Europe ===")

    # Look up EPSG:3035 (ETRS89-extended / LAEA Europe)
    proj_str = get_proj_string(3035)
    print(f"  EPSG:3035 -> {proj_str}")

    correct_ellps = extract_param(proj_str, "ellps")
    correct_y_0 = extract_param(proj_str, "y_0")
    print(f"  Correct ellps={correct_ellps}, y_0={correct_y_0}")

    with open("/app/scenario_c.gie") as f:
        content = f.read()

    content = re.sub(r"\+ellps=\w+", f"+ellps={correct_ellps}", content)
    content = re.sub(r"\+y_0=[\d.]+", f"+y_0={correct_y_0}", content)

    with open("/app/results/scenario_c_fixed.gie", "w") as f:
        f.write(content)

    _, stderr, rc = run_cmd(["gie", "/app/results/scenario_c_fixed.gie"])
    print(f"  gie exit code: {rc}")
    if rc != 0:
        print(f"  FAILED: {stderr}")
    return rc == 0


# ── Scenario D: Helmert 7-parameter (DHDN) ───────────────────────────────────

def fix_scenario_d():
    print("\n=== Scenario D: Helmert 7-parameter ===")

    # Query available transformations from DHDN (EPSG:4314) to WGS84 (EPSG:4326)
    stdout, _, _ = run_cmd([
        "projinfo", "-s", "EPSG:4314", "-t", "EPSG:4326",
        "--spatial-test", "intersects", "-o", "PROJ",
    ])
    print(f"  Transformation search output (first 1000 chars):\n  {stdout[:1000]}")

    # Extract Helmert parameters from the projinfo pipeline output
    towgs84 = None
    helmert_match = re.search(
        r"\+proj=helmert(.*?)(?:\+step|$)", stdout, re.DOTALL
    )
    if helmert_match:
        section = helmert_match.group(1)
        params = {}
        for p in ["x", "y", "z", "rx", "ry", "rz", "s"]:
            m = re.search(rf"\+{p}=([\d.eE+-]+)", section)
            if m:
                params[p] = m.group(1)
        if len(params) == 7:
            towgs84 = ",".join(params[p] for p in ["x", "y", "z", "rx", "ry", "rz", "s"])

    if not towgs84:
        # Fallback: standard Potsdam datum Helmert (position vector convention)
        towgs84 = "598.1,73.7,418.2,0.202,0.045,-2.455,6.7"

    print(f"  Correct towgs84: {towgs84}")

    with open("/app/scenario_d.gie") as f:
        content = f.read()

    content = re.sub(r"\+towgs84=[\d.,eE+-]+", f"+towgs84={towgs84}", content)

    with open("/app/results/scenario_d_fixed.gie", "w") as f:
        f.write(content)

    _, stderr, rc = run_cmd(["gie", "/app/results/scenario_d_fixed.gie"])
    print(f"  gie exit code: {rc}")
    if rc != 0:
        print(f"  FAILED: {stderr}")
    return rc == 0


# ── Chain: DHDN geographic -> LAEA Europe projected ──────────────────────────

def compute_chain():
    print("\n=== Chain: DHDN -> LAEA Europe ===")

    # Read corrected parameters from the fixed scenario files
    with open("/app/results/scenario_d_fixed.gie") as f:
        d_content = f.read()
    towgs84 = re.search(r"\+towgs84=([\d.,eE+-]+)", d_content).group(1)

    with open("/app/results/scenario_c_fixed.gie") as f:
        c_content = f.read()
    lat_0 = re.search(r"\+lat_0=([\d.-]+)", c_content).group(1)
    lon_0 = re.search(r"\+lon_0=([\d.-]+)", c_content).group(1)
    x_0 = re.search(r"\+x_0=([\d.]+)", c_content).group(1)
    y_0 = re.search(r"\+y_0=([\d.]+)", c_content).group(1)
    ellps = re.search(r"\+ellps=(\w+)", c_content).group(1)

    print(f"  Helmert towgs84: {towgs84}")
    print(f"  LAEA: lat_0={lat_0} lon_0={lon_0} x_0={x_0} y_0={y_0} ellps={ellps}")

    # Read input coordinates
    with open("/app/chain_input.csv") as f:
        reader = csv.DictReader(f)
        inputs = [(row["lon"], row["lat"]) for row in reader]

    results = []
    for lon, lat in inputs:
        stdout, stderr, rc = run_cmd(
            [
                "cs2cs",
                "+proj=longlat", "+ellps=bessel",
                f"+towgs84={towgs84}",
                "+to",
                "+proj=laea",
                f"+lat_0={lat_0}", f"+lon_0={lon_0}",
                f"+x_0={x_0}", f"+y_0={y_0}",
                f"+ellps={ellps}", "+units=m",
            ],
            input_text=f"{lon} {lat}\n",
        )
        assert rc == 0, f"cs2cs failed for ({lon}, {lat}): {stderr}"

        parts = stdout.strip().split()
        easting = float(parts[0])
        northing = float(parts[1])

        results.append({
            "lon_dhdn": lon,
            "lat_dhdn": lat,
            "easting_laea": f"{easting:.2f}",
            "northing_laea": f"{northing:.2f}",
        })
        print(f"  ({lon}, {lat}) -> ({easting:.2f}, {northing:.2f})")

    with open("/app/results/chain_results.csv", "w", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=["lon_dhdn", "lat_dhdn", "easting_laea", "northing_laea"]
        )
        writer.writeheader()
        writer.writerows(results)

    print("  Chain results written to /app/results/chain_results.csv")


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    os.makedirs("/app/results", exist_ok=True)

    passed = True
    passed &= fix_scenario_a()
    passed &= fix_scenario_b()
    passed &= fix_scenario_c()
    passed &= fix_scenario_d()

    if not passed:
        print("\nERROR: Not all scenarios passed gie validation!")
        sys.exit(1)

    compute_chain()
    print("\nAll done — all scenarios fixed and chain computed.")


if __name__ == "__main__":
    main()
