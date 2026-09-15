#!/usr/bin/env python3
"""
Solution for geodetic pipeline debugging task.

Diagnoses and fixes 5 broken PROJ transformation definitions in a GIE test
file, computes calibration transforms, and generates required deliverables.

"""

import subprocess
import json


def run_gie(filepath):
    """Run gie on a file and return (returncode, output)."""
    result = subprocess.run(
        ["gie", filepath], capture_output=True, text=True, timeout=120
    )
    return result.returncode, result.stdout + result.stderr


def run_cs2cs(proj_args, lon, lat, height=0):
    """Run cs2cs and return output coordinates as list of floats."""
    inp = f"{lon} {lat} {height}\n"
    result = subprocess.run(
        ["cs2cs", "-f", "%.6f"] + proj_args,
        input=inp, capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"cs2cs failed: {result.stderr}")
    parts = result.stdout.strip().split()
    return [float(x) for x in parts[:3]]


# Correct projection parameters for cs2cs (forward: longlat -> projected)
PROJ_ARGS = {
    1: [
        "+proj=longlat", "+ellps=bessel", "+to",
        "+proj=sterea", "+lat_0=52.15616055555556",
        "+lon_0=5.38763888888889", "+k_0=0.9999079",
        "+x_0=155000", "+y_0=463000", "+ellps=bessel",
    ],
    2: [
        "+proj=longlat", "+ellps=GRS80", "+to",
        "+proj=poly", "+lat_0=0", "+lon_0=-54",
        "+x_0=5000000", "+y_0=10000000", "+ellps=GRS80",
    ],
    3: [
        "+proj=longlat", "+ellps=GRS80", "+to",
        "+proj=aea", "+lat_0=0", "+lon_0=132",
        "+lat_1=-18", "+lat_2=-36",
        "+x_0=0", "+y_0=0", "+ellps=GRS80",
    ],
    4: [
        "+proj=longlat", "+ellps=GRS80", "+to",
        "+proj=omerc", "+no_uoff", "+lat_0=4", "+lonc=115",
        "+alpha=53.31580995", "+gamma=53.1301023611111",
        "+k_0=0.99984", "+x_0=0", "+y_0=0", "+ellps=GRS80",
    ],
    5: [
        "+proj=longlat", "+ellps=WGS84", "+to",
        "+proj=geocent", "+ellps=WGS84",
    ],
}


def main():
    # Read the broken file
    with open("/app/transforms.gie", "r") as f:
        content = f.read()

    # Diagnostic run
    print("=== Initial gie run on broken transforms.gie ===")
    rc, out = run_gie("/app/transforms.gie")
    print("Initial result: " + ("pass" if rc == 0 else "failures detected"))

    # Fix 1: Oblique Stereographic (Netherlands RD New)
    # +proj=stere (polar) must be +proj=sterea (oblique/double stereographic)
    content = content.replace(
        "+proj=stere +lat_0=52",
        "+proj=sterea +lat_0=52"
    )

    # Fix 2: American Polyconic (Brazil / SIRGAS 2000)
    # +ellps=intl (International 1924) must be +ellps=GRS80
    content = content.replace("+ellps=intl", "+ellps=GRS80")

    # Fix 3: Albers Equal Area Conic (Australian Albers)
    # +lon_0=134 must be +lon_0=132 (EPSG:3577 central meridian)
    content = content.replace("+lon_0=134", "+lon_0=132")

    # Fix 4: Hotine Oblique Mercator variant A (East Malaysia BRSO)
    # Missing +no_uoff flag for variant A
    content = content.replace(
        "+k_0=0.99984 +x_0=0 +y_0=0 +ellps=GRS80",
        "+k_0=0.99984 +no_uoff +x_0=0 +y_0=0 +ellps=GRS80"
    )

    # Fix 5: Geocentric to Geographic (WGS 84)
    # +ellps=clrk66 (Clarke 1866) must be +ellps=WGS84
    content = content.replace("+ellps=clrk66", "+ellps=WGS84")

    # Write the fixed file
    with open("/app/transforms.gie", "w") as f:
        f.write(content)
    print("Fixed transforms.gie written.")

    # Verify fixes
    print("\n=== Verification run on fixed transforms.gie ===")
    rc, out = run_gie("/app/transforms.gie")
    print("Verification: " + ("PASS" if rc == 0 else "ISSUES\n" + out))

    # Read calibration data
    with open("/app/calibration_data.json") as f:
        cal_data = json.load(f)
    task_id = cal_data["task_instance_id"]
    print(f"\nTask instance ID: {task_id}")

    # Compute calibration transforms
    cal_results = []
    for coord in cal_data["coordinates"]:
        pid = coord["projection_id"]
        lon = coord["longitude"]
        lat = coord["latitude"]
        height = coord.get("height", 0)

        vals = run_cs2cs(PROJ_ARGS[pid], lon, lat, height)
        print(f"  Projection {pid}: ({lon}, {lat}) -> {vals}")

        entry = {"projection_id": pid, "input_lon": lon, "input_lat": lat}
        if pid <= 4:
            entry["easting"] = vals[0]
            entry["northing"] = vals[1]
        else:
            entry["input_height"] = height
            entry["x"] = vals[0]
            entry["y"] = vals[1]
            entry["z"] = vals[2]
        cal_results.append(entry)

    with open("/app/calibration_results.json", "w") as f:
        json.dump({"task_instance_id": task_id, "results": cal_results}, f, indent=2)
    print("Wrote /app/calibration_results.json")

    # Generate diagnostic report
    report = {
        "task_instance_id": task_id,
        "pipelines": [
            {
                "pipeline_id": 1,
                "projection_type": "sterea",
                "error_description": (
                    "Used +proj=stere (polar stereographic) instead of "
                    "+proj=sterea (oblique/double stereographic). EPSG:28992 "
                    "uses the Gauss-Schreiber double stereographic variant."
                ),
                "fix_description": "Changed +proj=stere to +proj=sterea"
            },
            {
                "pipeline_id": 2,
                "projection_type": "poly",
                "error_description": (
                    "Used +ellps=intl (International 1924) instead of "
                    "+ellps=GRS80. SIRGAS 2000 uses the GRS 1980 ellipsoid."
                ),
                "fix_description": "Changed +ellps=intl to +ellps=GRS80"
            },
            {
                "pipeline_id": 3,
                "projection_type": "aea",
                "error_description": (
                    "Central meridian +lon_0=134 instead of +lon_0=132. "
                    "EPSG:3577 Australian Albers uses 132 degrees E."
                ),
                "fix_description": "Changed +lon_0=134 to +lon_0=132"
            },
            {
                "pipeline_id": 4,
                "projection_type": "omerc",
                "error_description": (
                    "Missing +no_uoff flag. EPSG:3376 Hotine Oblique "
                    "Mercator variant A requires +no_uoff to place the "
                    "false origin at the natural origin."
                ),
                "fix_description": "Added +no_uoff parameter"
            },
            {
                "pipeline_id": 5,
                "projection_type": "geocent",
                "error_description": (
                    "Used +ellps=clrk66 (Clarke 1866) instead of "
                    "+ellps=WGS84 in the geocentric pipeline."
                ),
                "fix_description": (
                    "Changed +ellps=clrk66 to +ellps=WGS84 in both steps"
                )
            }
        ]
    }
    with open("/app/diagnostic_report.json", "w") as f:
        json.dump(report, f, indent=2)
    print("Wrote /app/diagnostic_report.json")

    # Generate roundtrip validation file
    lines = [
        "Roundtrip Stability Validation",
        "",
        "<gie>",
        "",
        "operation +proj=sterea +lat_0=52.15616055555556 "
        "+lon_0=5.38763888888889 +k_0=0.9999079 "
        "+x_0=155000 +y_0=463000 +ellps=bessel",
        "tolerance 0.006 m",
        "accept    5 53",
        "roundtrip 1000",
        "tolerance 0.006 m",
        "accept    5.38763888889 52.1561605556",
        "roundtrip 1000",
        "tolerance 0.006 m",
        "accept    8 53",
        "roundtrip 1000",
        "",
        "operation +proj=poly +lat_0=0 +lon_0=-54 "
        "+x_0=5000000 +y_0=10000000 +ellps=GRS80",
        "tolerance 0.006 m",
        "accept    -54 0",
        "roundtrip 1000",
        "tolerance 0.006 m",
        "accept    -45 6",
        "roundtrip 1000",
        "tolerance 0.006 m",
        "accept    -36 -30",
        "roundtrip 1000",
        "",
        "operation +proj=aea +lat_0=0 +lon_0=132 +lat_1=-18 "
        "+lat_2=-36 +x_0=0 +y_0=0 +ellps=GRS80",
        "tolerance 0.006 m",
        "accept    132 0",
        "roundtrip 1000",
        "tolerance 0.006 m",
        "accept    140 -20",
        "roundtrip 1000",
        "tolerance 0.006 m",
        "accept    140 -60",
        "roundtrip 1000",
        "",
        "operation +proj=omerc +no_uoff +lat_0=4 +lonc=115 "
        "+alpha=53.31580995 +gamma=53.1301023611111 "
        "+k_0=0.99984 +x_0=0 +y_0=0 +ellps=GRS80",
        "tolerance 0.006 m",
        "accept    117 6",
        "roundtrip 1000",
        "tolerance 0.006 m",
        "accept    115 4",
        "roundtrip 1000",
        "tolerance 0.006 m",
        "accept    123 6",
        "roundtrip 1000",
        "",
        "operation +proj=pipeline "
        "+step +proj=geocent +ellps=WGS84 +inv "
        "+step +proj=longlat +ellps=WGS84",
        "tolerance 0.01 m",
        "accept    6378137 0 0",
        "roundtrip 1000",
        "tolerance 0.01 m",
        "accept    2764128.3196 4787610.6883 3170373.7354",
        "roundtrip 1000",
        "tolerance 0.01 m",
        "accept    -962297.0059 555582.4354 6259542.961",
        "roundtrip 1000",
        "",
        "</gie>",
        "",
    ]
    with open("/app/roundtrip_validation.gie", "w") as f:
        f.write("\n".join(lines))
    print("Wrote /app/roundtrip_validation.gie")

    # Verify roundtrip
    print("\n=== Verification run on roundtrip_validation.gie ===")
    rc, out = run_gie("/app/roundtrip_validation.gie")
    print("Roundtrip: " + ("PASS" if rc == 0 else "ISSUES\n" + out))

    print("\n=== Solution complete ===")


if __name__ == "__main__":
    main()
