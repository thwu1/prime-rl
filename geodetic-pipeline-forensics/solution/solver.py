#!/usr/bin/env python3
"""

Solution for geodetic pipeline evaluation and projection identification task.
Derives reference pipelines from CRS definitions, evaluates candidates,
and identifies an unknown projection from control observations.
"""
import json
import subprocess
import os
import math
import csv


# ---------------------------------------------------------------------------
# Domain knowledge: EPSG method/parameter/ellipsoid mappings
# ---------------------------------------------------------------------------

METHOD_TO_PROJ = {
    9809: "sterea",   # Oblique Stereographic Alternative
    9820: "laea",     # Lambert Azimuthal Equal Area
    9602: "cart",     # Geographic/geocentric conversions
    9801: "lcc",      # Lambert Conic Conformal (1SP)
    9802: "lcc",      # Lambert Conic Conformal (2SP)
    9822: "aea",      # Albers Equal Area
}

PARAM_TO_PROJ = {
    "Latitude of natural origin": "lat_0",
    "Longitude of natural origin": "lon_0",
    "Scale factor at natural origin": "k_0",
    "False easting": "x_0",
    "False northing": "y_0",
    "Latitude of 1st standard parallel": "lat_1",
    "Latitude of 2nd standard parallel": "lat_2",
    "Latitude of false origin": "lat_0",
    "Longitude of false origin": "lon_0",
    "Easting at false origin": "x_0",
    "Northing at false origin": "y_0",
}

ELLIPSOID_TO_PROJ = {
    "Bessel 1841": "bessel",
    "GRS 1980": "GRS80",
    "WGS 84": "WGS84",
    "International 1924": "intl",
}


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def run_cct(proj_string, lon, lat, z=0.0):
    """Transform coordinates using PROJ cct CLI tool."""
    input_str = f"{lon} {lat} {z} 0\n"
    cmd = ['cct', '-d', '10'] + proj_string.split()
    try:
        result = subprocess.run(
            cmd, input=input_str, capture_output=True, text=True, timeout=30
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    output = result.stdout.strip()
    if '*' in output:
        return None
    try:
        return [float(v) for v in output.split()]
    except ValueError:
        return None


def positional_error(a, b, dims=3):
    """Euclidean distance between first `dims` components."""
    n = min(dims, len(a), len(b))
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(n)))


def build_reference_pipeline(ref_def):
    """Construct a PROJ pipeline string from a reference_definition block."""
    method_code = ref_def['epsg_method_code']
    proj_type = METHOD_TO_PROJ.get(method_code)
    if proj_type is None:
        raise ValueError(f"Unknown EPSG method code: {method_code}")

    parts = [f"+proj={proj_type}"]

    for param_name, param_value in ref_def['parameters'].items():
        proj_param = PARAM_TO_PROJ.get(param_name)
        if proj_param is None:
            print(f"  WARNING: unmapped parameter '{param_name}', skipping")
            continue
        if isinstance(param_value, float) and param_value == int(param_value):
            parts.append(f"+{proj_param}={int(param_value)}")
        else:
            parts.append(f"+{proj_param}={param_value}")

    ellps_name = ref_def['ellipsoid']['name']
    ellps_code = ELLIPSOID_TO_PROJ.get(ellps_name)
    if ellps_code:
        parts.append(f"+ellps={ellps_code}")
    else:
        a = ref_def['ellipsoid']['semi_major_axis_m']
        rf = ref_def['ellipsoid']['inverse_flattening']
        parts.append(f"+a={a}")
        parts.append(f"+rf={rf}")

    if proj_type != "cart":
        parts.append("+units=m")

    return ' '.join(parts)


def compute_reference_coordinates(ref_pipeline, input_points):
    """Generate reference output coordinates using cct."""
    coords = []
    for pt in input_points:
        z = pt[2] if len(pt) > 2 else 0.0
        result = run_cct(ref_pipeline, pt[0], pt[1], z)
        if result is None:
            raise RuntimeError(
                f"Reference pipeline failed for input {pt}: {ref_pipeline}"
            )
        coords.append(result)
    return coords


def compute_metrics(proj_string, input_points, ref_coords):
    """Compute RMSE and max positional error for a pipeline."""
    errors = []
    for pt, ref in zip(input_points, ref_coords):
        z = pt[2] if len(pt) > 2 else 0.0
        res = run_cct(proj_string, pt[0], pt[1], z)
        if res is None:
            return {'rmse_m': float('inf'), 'max_error_m': float('inf')}
        errors.append(positional_error(res, ref))

    rmse = math.sqrt(sum(e ** 2 for e in errors) / len(errors))
    max_err = max(errors)
    return {'rmse_m': round(rmse, 6), 'max_error_m': round(max_err, 6)}


def classify_tier(rmse, tiers):
    """Classify RMSE into the highest accuracy tier it meets."""
    if rmse < tiers['survey']['max_rmse_m']:
        return 'survey'
    elif rmse < tiers['mapping']['max_rmse_m']:
        return 'mapping'
    elif rmse < tiers['navigation']['max_rmse_m']:
        return 'navigation'
    return 'none'


# ---------------------------------------------------------------------------
# Design scenario: unknown projection identification
# ---------------------------------------------------------------------------

def analyze_design_scenario(csv_path):
    """
    Identify unknown projection and construct a PROJ pipeline from
    surveyed control observations.
    """
    # Load control points
    control_points = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            control_points.append({
                'geographic': [float(row['longitude_deg']),
                               float(row['latitude_deg'])],
                'projected': [float(row['easting_m']),
                              float(row['northing_m'])],
            })

    print("\n--- Analyzing design scenario control points ---")

    # Step 1: Identify central meridian — longitude where easting is constant
    lon_groups = {}
    for pt in control_points:
        lon = pt['geographic'][0]
        lon_groups.setdefault(lon, []).append(pt)

    central_meridian = None
    for lon, pts in sorted(lon_groups.items(),
                           key=lambda x: len(x[1]), reverse=True):
        if len(pts) >= 2:
            eastings = [p['projected'][0] for p in pts]
            if all(abs(e - eastings[0]) < 1.0 for e in eastings):
                central_meridian = lon
                break

    print(f"  Central meridian identified: {central_meridian}")

    # Step 2: Determine false easting, false northing, latitude of origin
    fe, fn, lat_origin = 0.0, 0.0, 0.0
    for pt in control_points:
        if pt['geographic'][0] == central_meridian:
            if abs(pt['projected'][0]) < 1.0 and abs(pt['projected'][1]) < 1.0:
                lat_origin = pt['geographic'][1]
                fe = pt['projected'][0]
                fn = pt['projected'][1]
                break

    print(f"  Latitude of origin: {lat_origin}")
    print(f"  False easting: {fe}, False northing: {fn}")

    # Step 3: Determine projection class (conic vs cylindrical vs azimuthal)
    off_cm_at_origin = [
        p for p in control_points
        if abs(p['geographic'][1] - lat_origin) < 0.01
        and abs(p['geographic'][0] - central_meridian) > 1.0
    ]

    is_conic = any(
        abs(pt['projected'][1] - fn) > 100 for pt in off_cm_at_origin
    )

    if is_conic:
        print("  Projection class: conic "
              "(N departs from FN at origin for off-CM points)")

    # Step 4: Systematic search for standard parallels
    print("  Searching for best-fit standard parallels...")

    sp_candidates = [
        (-18, -36), (-10, -40), (-15, -33), (-20, -35),
        (-18, -34), (-16, -36), (-17, -35), (-19, -37),
        (-12, -38), (-14, -32), (-22, -38),
        (29.5, 45.5), (20, 60),
    ]

    best_rmse = float('inf')
    best_pipeline = None
    best_sp = None
    best_ellps = None
    best_proj_type = None

    # Try Albers Equal Area Conic first (description says "equal-area")
    for ellps in ['GRS80', 'WGS84']:
        for sp1, sp2 in sp_candidates:
            proj_str = (
                f"+proj=aea +lat_0={lat_origin} +lon_0={central_meridian} "
                f"+lat_1={sp1} +lat_2={sp2} "
                f"+x_0={int(fe)} +y_0={int(fn)} +ellps={ellps} +units=m"
            )

            total_sq = 0
            n_pts = 0
            valid = True
            for pt in control_points:
                res = run_cct(
                    proj_str, pt['geographic'][0], pt['geographic'][1]
                )
                if res is None:
                    valid = False
                    break
                err = math.sqrt(
                    (res[0] - pt['projected'][0]) ** 2 +
                    (res[1] - pt['projected'][1]) ** 2
                )
                total_sq += err ** 2
                n_pts += 1

            if valid and n_pts > 0:
                rmse = math.sqrt(total_sq / n_pts)
                if rmse < 1.0:
                    print(f"    aea sp=({sp1},{sp2}) ellps={ellps}: "
                          f"RMSE={rmse:.6f}m")
                if rmse < best_rmse:
                    best_rmse = rmse
                    best_pipeline = proj_str
                    best_sp = (sp1, sp2)
                    best_ellps = ellps
                    best_proj_type = "Albers Equal Area"

    if best_pipeline and best_rmse < 0.05:
        print(f"\n  Best fit: {best_proj_type}")
        print(f"  Standard parallels: {best_sp}")
        print(f"  Ellipsoid: {best_ellps}")
        print(f"  RMSE: {best_rmse:.6f}m")
        return best_pipeline, best_proj_type

    # Fallback: try Lambert Conformal Conic
    print("  AEA did not converge; trying Lambert Conformal Conic...")
    for ellps in ['GRS80', 'WGS84']:
        for sp1, sp2 in sp_candidates:
            proj_str = (
                f"+proj=lcc +lat_0={lat_origin} +lon_0={central_meridian} "
                f"+lat_1={sp1} +lat_2={sp2} "
                f"+x_0={int(fe)} +y_0={int(fn)} +ellps={ellps} +units=m"
            )
            total_sq = 0
            n_pts = 0
            valid = True
            for pt in control_points:
                res = run_cct(
                    proj_str, pt['geographic'][0], pt['geographic'][1]
                )
                if res is None:
                    valid = False
                    break
                err = math.sqrt(
                    (res[0] - pt['projected'][0]) ** 2 +
                    (res[1] - pt['projected'][1]) ** 2
                )
                total_sq += err ** 2
                n_pts += 1

            if valid and n_pts > 0:
                rmse = math.sqrt(total_sq / n_pts)
                if rmse < best_rmse:
                    best_rmse = rmse
                    best_pipeline = proj_str
                    best_proj_type = "Lambert Conformal Conic"

    if best_pipeline and best_rmse < 0.05:
        print(f"  Best fit: {best_proj_type}, RMSE={best_rmse:.6f}m")
        return best_pipeline, best_proj_type

    print(f"  WARNING: no acceptable fit (best RMSE={best_rmse:.2f}m)")
    return best_pipeline or "", "Unknown"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("GEODETIC PIPELINE EVALUATION AND PROJECTION IDENTIFICATION")
    print("=" * 60)

    with open('/app/scenarios.json') as f:
        data = json.load(f)

    tiers = data['accuracy_tiers']
    eval_scenarios = data['evaluation_scenarios']

    # ---------------------------------------------------------------
    # Phase 1: Build reference pipelines and evaluate candidates
    # ---------------------------------------------------------------
    accuracy_report = {}
    tier_classification = {}
    rankings = {}

    for sname, scenario in eval_scenarios.items():
        print(f"\n{'='*60}")
        print(f"Scenario: {sname}")
        print(f"  {scenario['description']}")
        print(f"{'='*60}")

        # Build authoritative reference pipeline from definition
        ref_def = scenario['reference_definition']
        ref_pipeline = build_reference_pipeline(ref_def)
        print(f"  Reference pipeline: {ref_pipeline}")

        # Generate reference coordinates
        input_points = scenario['input_points']
        ref_coords = compute_reference_coordinates(ref_pipeline, input_points)
        print(f"  Generated {len(ref_coords)} reference coordinates")

        # Evaluate each candidate against reference
        candidates = scenario['candidates']
        metrics = {}
        for cname, proj_str in candidates.items():
            m = compute_metrics(proj_str, input_points, ref_coords)
            metrics[cname] = m
            print(f"  {cname:>8s}: RMSE={m['rmse_m']:.6f}m  "
                  f"MaxErr={m['max_error_m']:.6f}m")

        accuracy_report[sname] = metrics

        # Tier classification
        tiers_map = {}
        for cname, m in metrics.items():
            t = classify_tier(m['rmse_m'], tiers)
            tiers_map[cname] = t
            print(f"  {cname:>8s}: tier = {t}")
        tier_classification[sname] = tiers_map

        # Ranking
        ranked = sorted(metrics, key=lambda c: metrics[c]['rmse_m'])
        survey_rec = next((c for c in ranked if tiers_map[c] == 'survey'), None)
        rankings[sname] = {
            'ranking': ranked,
            'survey_recommendation': survey_rec,
        }
        print(f"  Ranking: {ranked}")
        print(f"  Survey recommendation: {survey_rec}")

    # ---------------------------------------------------------------
    # Phase 2: Design pipeline for unknown projection
    # ---------------------------------------------------------------
    print(f"\n{'='*60}")
    print("Design Scenario: Unknown Projection Identification")
    print(f"{'='*60}")

    design_data = data['design_scenario']
    proj_string, proj_type = analyze_design_scenario(design_data['data_file'])

    designed = {
        'proj_string': proj_string,
        'projection_type': proj_type,
    }

    # ---------------------------------------------------------------
    # Phase 3: Write results
    # ---------------------------------------------------------------
    os.makedirs('/app/results', exist_ok=True)

    with open('/app/results/accuracy_report.json', 'w') as f:
        json.dump(accuracy_report, f, indent=2)
    print("\nWrote /app/results/accuracy_report.json")

    with open('/app/results/tier_classification.json', 'w') as f:
        json.dump(tier_classification, f, indent=2)
    print("Wrote /app/results/tier_classification.json")

    with open('/app/results/rankings.json', 'w') as f:
        json.dump(rankings, f, indent=2)
    print("Wrote /app/results/rankings.json")

    with open('/app/results/designed_pipeline.json', 'w') as f:
        json.dump(designed, f, indent=2)
    print("Wrote /app/results/designed_pipeline.json")

    print(f"\n{'='*60}")
    print("ALL RESULTS WRITTEN SUCCESSFULLY")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
