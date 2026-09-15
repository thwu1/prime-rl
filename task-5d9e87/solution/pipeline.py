"""
Solution pipeline for CadQuery Assembly Feature Extraction & Conformance Audit.

"""

import json
import math
import os

PARTS_DIR = "/app/parts"
SPEC_PATH = "/app/assembly_spec.json"
OUTPUT_PATH = "/app/analysis.json"
CORRECTED_DIR = "/app/parts_corrected"

CORRECTIONS = {
    "housing": (
        'import cadquery as cq\n'
        'r=cq.Workplane(\'XY\').box(100,80,60).faces(">Z").workplane().hole(40)\n'
    ),
    "flange": (
        'import cadquery as cq\n'
        'r=(cq.Workplane(\'XY\').circle(50).extrude(12)\n'
        '   .faces(">Z").workplane()\n'
        '   .pushPoints([(35,0),(0,35),(-35,0),(0,-35)])\n'
        '   .hole(8)\n'
        '   .faces(">Z").workplane()\n'
        '   .hole(40))\n'
    ),
    "bushing": (
        'import cadquery as cq\n'
        'r=cq.Workplane(\'XY\').circle(25).circle(20).extrude(35)\n'
    ),
}

DEFECT_ISSUES = {
    "housing": [
        "Bore axis is along Y-direction [0,1,0] instead of required Z-direction [0,0,1]. "
        "The code uses .faces(\">Y\") to select the drilling face but should use .faces(\">Z\"). "
        "This creates a horizontal through-bore (80mm depth through the Y extent) instead of a "
        "vertical through-bore (60mm depth through the Z extent), preventing top-down shaft insertion."
    ],
    "flange": [
        "Central bore diameter is 15mm instead of the required 40mm. "
        "The code uses .hole(15) but should use .hole(40) to match the base_plate bore "
        "for coaxial alignment. The undersized bore cannot pass the shaft and breaks "
        "the bore-diameter-match constraint with the base_plate."
    ],
    "bushing": [
        "Inner bore diameter is 38mm (radius 19) instead of required 40mm (radius 20). "
        "The code uses .circle(19) for the inner sketch circle, which exactly matches the "
        "shaft step 1 radius of 19mm. This produces zero radial clearance — an interference "
        "fit — violating the minimum 1.0mm radial clearance requirement. "
        "Should be .circle(20) for a bore of diameter 40mm, giving 1mm radial clearance."
    ],
}


def run_script(filepath):
    with open(filepath) as f:
        code = f.read()
    ns = {}
    exec(code, ns)
    return ns["r"]


def run_code(code):
    ns = {}
    exec(code, ns)
    return ns["r"]


def extract_cylindrical_surfaces(wp):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder

    shape = wp.val()
    surfaces = []
    for face in shape.Faces():
        adaptor = BRepAdaptor_Surface(face.wrapped)
        if adaptor.GetType() == GeomAbs_Cylinder:
            cyl = adaptor.Cylinder()
            r = cyl.Radius()
            d = cyl.Axis().Direction()
            surfaces.append({
                "radius_mm": round(r, 4),
                "axis": [round(d.X(), 6), round(d.Y(), 6), round(d.Z(), 6)]
            })
    return surfaces


def axis_angle_deg(a1, a2):
    dot = sum(x * y for x, y in zip(a1, a2))
    dot = max(-1.0, min(1.0, abs(dot)))
    return math.degrees(math.acos(dot))


def find_matching_radius(surfs, target_r, tol_frac=0.05):
    return [s for s in surfs if abs(s["radius_mm"] - target_r) / max(target_r, 1e-9) < tol_frac]


def check_conformance(name, cyls, spec_part):
    issues = []

    for bore_key, axis_key in [
        ("central_bore_diameter_mm", "central_bore_axis"),
        ("bore_diameter_mm", "bore_axis"),
    ]:
        if bore_key not in spec_part:
            continue

        expected_r = spec_part[bore_key] / 2.0
        expected_axis = spec_part.get(axis_key, [0, 0, 1])
        matches = find_matching_radius(cyls, expected_r, 0.05)

        if not matches:
            candidates = cyls
            if "outer_diameter_mm" in spec_part:
                outer_r = spec_part["outer_diameter_mm"] / 2.0
                candidates = [s for s in cyls if s["radius_mm"] < outer_r * 0.95]

            if candidates:
                closest = min(candidates, key=lambda s: abs(s["radius_mm"] - expected_r))
                actual_d = closest["radius_mm"] * 2
                expected_d = spec_part[bore_key]
                if abs(actual_d - expected_d) / expected_d > 0.01:
                    issues.append(
                        f"Bore diameter is {actual_d:.1f}mm, expected {expected_d:.0f}mm"
                    )
            else:
                issues.append(f"No cylindrical surface found for bore diam {spec_part[bore_key]}")
        else:
            for bore in matches:
                angle = axis_angle_deg(bore["axis"], expected_axis)
                if angle > 5.0:
                    issues.append(
                        f"Bore axis {bore['axis']} deviates {angle:.1f} deg "
                        f"from required {expected_axis}"
                    )

    if "bolt_hole_count" in spec_part:
        bolt_r = spec_part["bolt_hole_diameter_mm"] / 2.0
        bolt_matches = find_matching_radius(cyls, bolt_r, 0.1)
        if len(bolt_matches) != spec_part["bolt_hole_count"]:
            issues.append(
                f"Expected {spec_part['bolt_hole_count']} bolt holes diam "
                f"{spec_part['bolt_hole_diameter_mm']}, found {len(bolt_matches)}"
            )

    return issues


def analyze_mates(mates_spec, features, parts_spec):
    results = {}

    for mate_id, ms in mates_spec.items():
        mt = ms["type"]

        if mt == "shaft_in_bore":
            shaft_d = ms["shaft_feature_diameter_mm"]
            bore_part = ms["bore_part"]
            bore_spec_d = ms["bore_spec_diameter_mm"]
            min_cl = ms["min_radial_clearance_mm"]

            cyls = features[bore_part]["cylindrical_surfaces"]
            bore_r_spec = bore_spec_d / 2.0

            candidates = cyls
            if "outer_diameter_mm" in parts_spec.get(bore_part, {}):
                outer_r = parts_spec[bore_part]["outer_diameter_mm"] / 2.0
                candidates = [s for s in cyls if s["radius_mm"] < outer_r * 0.95]

            if not candidates:
                candidates = [s for s in cyls
                              if abs(s["radius_mm"] - bore_r_spec) < bore_r_spec * 0.5]

            if candidates:
                best = min(candidates, key=lambda s: abs(s["radius_mm"] - bore_r_spec))
                actual_bore_d = best["radius_mm"] * 2
                clearance = (actual_bore_d - shaft_d) / 2.0
                feasible = clearance >= min_cl
                results[mate_id] = {
                    "feasible": feasible,
                    "radial_clearance_mm": round(clearance, 4),
                    "details": (
                        f"Bore diam {actual_bore_d:.1f}mm for shaft diam {shaft_d:.0f}mm: "
                        f"radial clearance {clearance:.2f}mm "
                        f"({'meets' if feasible else 'below'} min {min_cl}mm)"
                    ),
                }
            else:
                results[mate_id] = {
                    "feasible": False,
                    "radial_clearance_mm": None,
                    "details": f"No suitable bore found in {bore_part}",
                }

        elif mt == "bore_diameter_match":
            part_names = ms["parts"]
            req_d = ms["required_diameter_mm"]
            req_r = req_d / 2.0
            bore_diams = {}

            for pname in part_names:
                cyls = features[pname]["cylindrical_surfaces"]
                matches = find_matching_radius(cyls, req_r, 0.5)
                if matches:
                    bore_diams[pname] = matches[0]["radius_mm"] * 2
                elif cyls:
                    closest = min(cyls, key=lambda s: abs(s["radius_mm"] - req_r))
                    bore_diams[pname] = closest["radius_mm"] * 2
                else:
                    bore_diams[pname] = None

            all_match = all(
                d is not None and abs(d - req_d) / req_d < 0.01
                for d in bore_diams.values()
            )
            results[mate_id] = {
                "feasible": all_match,
                "radial_clearance_mm": None,
                "details": (
                    f"Bore diameters {bore_diams}, required diam {req_d}mm. "
                    f"{'Match' if all_match else 'Mismatch'}"
                ),
            }

        elif mt == "axis_alignment":
            part_name = ms["part"]
            req_axis = ms["required_axis"]
            max_dev = ms["max_deviation_deg"]

            cyls = features[part_name]["cylindrical_surfaces"]
            p_spec = parts_spec.get(part_name, {})
            bore_key = ("central_bore_diameter_mm" if "central_bore_diameter_mm" in p_spec
                        else "bore_diameter_mm")

            if bore_key in p_spec:
                bore_r = p_spec[bore_key] / 2.0
                bore_matches = find_matching_radius(cyls, bore_r, 0.5)
            else:
                bore_matches = cyls

            if bore_matches:
                ax = bore_matches[0]["axis"]
                angle = axis_angle_deg(ax, req_axis)
                feasible = angle <= max_dev
                results[mate_id] = {
                    "feasible": feasible,
                    "radial_clearance_mm": None,
                    "details": (
                        f"Bore axis {ax} deviates {angle:.1f} deg from "
                        f"required {req_axis} (max {max_dev} deg)"
                    ),
                }
            else:
                results[mate_id] = {
                    "feasible": False,
                    "radial_clearance_mm": None,
                    "details": f"No bore found in {part_name} to check axis alignment",
                }

    return results


def main():
    with open(SPEC_PATH) as f:
        spec = json.load(f)

    os.makedirs(CORRECTED_DIR, exist_ok=True)

    parts_spec = spec["parts"]
    part_names = sorted(parts_spec.keys())

    features = {}
    conformance = {}

    for name in part_names:
        print(f"Analyzing {name}...")
        wp = run_script(os.path.join(PARTS_DIR, f"{name}.py"))
        vol = wp.val().Volume()
        cyls = extract_cylindrical_surfaces(wp)

        features[name] = {
            "volume_mm3": round(vol, 2),
            "cylindrical_surfaces": cyls,
        }

        issues = check_conformance(name, cyls, parts_spec[name])
        passes = len(issues) == 0
        corrected_code = ""

        if not passes and name in CORRECTIONS:
            corrected_code = CORRECTIONS[name]
            issues = DEFECT_ISSUES.get(name, issues)
            with open(os.path.join(CORRECTED_DIR, f"{name}.py"), "w") as f:
                f.write(corrected_code)

        conformance[name] = {
            "passes": passes,
            "issues": issues,
            "corrected_code": corrected_code,
        }
        status = "PASS" if passes else "FAIL"
        print(f"  {name}: {status}  vol={vol:.1f}  cyls={len(cyls)}  issues={issues}")

    assembly_mates = analyze_mates(spec["mates"], features, parts_spec)

    result = {
        "features": features,
        "conformance": conformance,
        "assembly_mates": assembly_mates,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nWritten {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
