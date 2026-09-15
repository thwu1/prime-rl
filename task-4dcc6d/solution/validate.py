#!/usr/bin/env python3
"""
Post-processing validation pipeline for backward-facing step CFD simulation.
Parses OpenFOAM mesh topology and velocity field data to compute the flow
reattachment length, verify mass conservation, and evaluate accuracy against
the experimental benchmark of Armaly et al. (1983).

"""

import os
import re
import json
import math
import sys

CASE_DIR = "/app/backwardStep"
LOG_FILE = os.path.join(CASE_DIR, "log.solver")
STEP_HEIGHT = 0.1  # metres (from blockMeshDict geometry)
EXPERIMENTAL_XR_OVER_H = 7.0


# ------------------------------------------------------------------ utilities


def find_latest_time(case_dir):
    """Return the name of the latest numerical time directory."""
    time_dirs = []
    for d in os.listdir(case_dir):
        full = os.path.join(case_dir, d)
        if os.path.isdir(full) and d != "0":
            try:
                time_dirs.append((float(d), d))
            except ValueError:
                pass
    if not time_dirs:
        raise RuntimeError("No result time directories found")
    time_dirs.sort()
    return time_dirs[-1][1]


def skip_foam_header(content):
    """Skip the FoamFile { ... } header and return remaining text."""
    idx = content.find("FoamFile")
    if idx == -1:
        return content
    brace = content.find("{", idx)
    if brace == -1:
        return content
    depth, i = 1, brace + 1
    while depth > 0 and i < len(content):
        ch = content[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    return content[i:]


# --------------------------------------------------------- OpenFOAM parsers


def parse_vector_list(text):
    """Parse  N ( (x y z) ... )  into a list of 3-tuples."""
    m = re.search(r"(\d+)\s*\(", text)
    if not m:
        return []
    n = int(m.group(1))
    pat = re.compile(
        r"\(\s*([0-9eE.+\-]+)\s+([0-9eE.+\-]+)\s+([0-9eE.+\-]+)\s*\)"
    )
    vectors = []
    for vm in pat.finditer(text, m.end()):
        vectors.append(
            (float(vm.group(1)), float(vm.group(2)), float(vm.group(3)))
        )
        if len(vectors) >= n:
            break
    return vectors


def parse_label_list(text):
    """Parse  N ( v0 v1 ... )  into a list of ints."""
    m = re.search(r"(\d+)\s*\(", text)
    if not m:
        return []
    n = int(m.group(1))
    close = text.find(")", m.end())
    tokens = text[m.end() : close].split()
    return [int(t) for t in tokens[:n]]


def parse_face_list(text):
    """Parse  N ( K(v0 v1 ...) ... )  into list of int-lists."""
    m = re.search(r"(\d+)\s*\(", text)
    if not m:
        return []
    n = int(m.group(1))
    # Use compiled pattern so .finditer() accepts a pos argument
    # (re.finditer at module level takes flags as 3rd arg, not pos)
    pat = re.compile(r"(\d+)\(([^)]+)\)")
    faces = []
    for fm in pat.finditer(text, m.end()):
        verts = [int(v) for v in fm.group(2).split()]
        faces.append(verts)
        if len(faces) >= n:
            break
    return faces


def parse_boundary(case_dir):
    """Return {patch_name: {nFaces, startFace}}."""
    path = os.path.join(case_dir, "constant", "polyMesh", "boundary")
    with open(path) as f:
        body = skip_foam_header(f.read())
    result = {}
    for bm in re.finditer(r"(\w+)\s*\{([^}]*)\}", body):
        block = bm.group(2)
        nf = re.search(r"nFaces\s+(\d+)", block)
        sf = re.search(r"startFace\s+(\d+)", block)
        if nf and sf:
            result[bm.group(1)] = {
                "nFaces": int(nf.group(1)),
                "startFace": int(sf.group(1)),
            }
    return result


def read_mesh_file(case_dir, filename, parser):
    path = os.path.join(case_dir, "constant", "polyMesh", filename)
    with open(path) as f:
        return parser(skip_foam_header(f.read()))


def read_velocity_field(filepath):
    """Parse U field; returns list of (ux, uy, uz) for the internal field."""
    with open(filepath) as f:
        content = f.read()
    m = re.search(r"internalField\s+nonuniform\s+List<vector>", content)
    if m:
        return parse_vector_list(content[m.end() :])
    m = re.search(
        r"internalField\s+uniform\s+\(\s*"
        r"([0-9eE.+\-]+)\s+([0-9eE.+\-]+)\s+([0-9eE.+\-]+)\s*\)",
        content,
    )
    if m:
        return [(float(m.group(1)), float(m.group(2)), float(m.group(3)))]
    return []


# ------------------------------------------------------- geometry helpers


def face_center(points, verts):
    n = len(verts)
    return tuple(sum(points[v][k] for v in verts) / n for k in range(3))


def face_area_magnitude(points, verts):
    """Area of a planar quad via diagonal cross-product."""
    if len(verts) == 4:
        p0, p1, p2, p3 = (points[v] for v in verts)
        d1 = tuple(p2[k] - p0[k] for k in range(3))
        d2 = tuple(p3[k] - p1[k] for k in range(3))
        cx = d1[1] * d2[2] - d1[2] * d2[1]
        cy = d1[2] * d2[0] - d1[0] * d2[2]
        cz = d1[0] * d2[1] - d1[1] * d2[0]
        return 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)
    if len(verts) >= 3:
        p0, p1, p2 = (points[v] for v in verts[:3])
        e1 = tuple(p1[k] - p0[k] for k in range(3))
        e2 = tuple(p2[k] - p0[k] for k in range(3))
        cx = e1[1] * e2[2] - e1[2] * e2[1]
        cy = e1[2] * e2[0] - e1[0] * e2[2]
        cz = e1[0] * e2[1] - e1[1] * e2[0]
        return 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)
    return 0.0


# -------------------------------------------------------- log extraction


def extract_final_residuals(log_path):
    with open(log_path) as f:
        text = f.read()
    res = {}
    for field in ("Ux", "Uy", "p", "k", "epsilon"):
        matches = re.findall(
            rf"Solving for {field},\s*Initial residual = ([0-9.eE+\-]+)", text
        )
        if matches:
            res[field] = float(matches[-1])
    return res


def extract_continuity_error(log_path):
    with open(log_path) as f:
        text = f.read()
    matches = re.findall(
        r"time step continuity errors\s*:"
        r"\s*sum local\s*=\s*[0-9.eE+\-]+,"
        r"\s*global\s*=\s*([0-9.eE+\-]+)",
        text,
    )
    return float(matches[-1]) if matches else None


def count_iterations(log_path):
    with open(log_path) as f:
        text = f.read()
    return len(re.findall(r"^Time = \d+", text, re.MULTILINE))


# -------------------------------------------------- physics computations


def compute_reattachment_length(case_dir, latest_time):
    """Find where near-wall Ux crosses zero on the downstream lower wall.

    The recirculation zone behind the step has reversed (negative) Ux near
    the lower wall.  The reattachment point is the x-coordinate where Ux
    transitions from negative to positive.  We use linear interpolation
    between the two bracketing cell centres for sub-cell accuracy.
    """
    points = read_mesh_file(case_dir, "points", parse_vector_list)
    faces_list = read_mesh_file(case_dir, "faces", parse_face_list)
    owner = read_mesh_file(case_dir, "owner", parse_label_list)
    boundary = parse_boundary(case_dir)

    u_path = os.path.join(case_dir, latest_time, "U")
    u_field = read_velocity_field(u_path)
    if len(u_field) <= 1:
        return None

    lw = boundary.get("lowerWall")
    if lw is None:
        return None

    # Collect (x_centre, Ux_owner) for downstream bottom wall faces
    # Downstream floor is at y ~ -0.1 and x > 0
    wall_data = []
    for fi in range(lw["startFace"], lw["startFace"] + lw["nFaces"]):
        ctr = face_center(points, faces_list[fi])
        if ctr[1] < -0.05 and ctr[0] > 0.005:
            cell = owner[fi]
            if cell < len(u_field):
                wall_data.append((ctr[0], u_field[cell][0]))

    if len(wall_data) < 2:
        return None
    wall_data.sort()

    # First negative-to-positive crossing
    for i in range(len(wall_data) - 1):
        x0, ux0 = wall_data[i]
        x1, ux1 = wall_data[i + 1]
        if ux0 <= 0.0 < ux1:
            denom = ux1 - ux0
            if abs(denom) > 1e-30:
                return x0 + (0.0 - ux0) * (x1 - x0) / denom
            return 0.5 * (x0 + x1)

    # No crossing: all positive means reattachment very near the step
    if all(ux > 0 for _, ux in wall_data):
        return wall_data[0][0]
    return None


def compute_inlet_mass_flow(case_dir):
    """Q_inlet = U_in * A_inlet  (uniform velocity, incompressible)."""
    points = read_mesh_file(case_dir, "points", parse_vector_list)
    faces_list = read_mesh_file(case_dir, "faces", parse_face_list)
    boundary = parse_boundary(case_dir)
    inlet = boundary.get("inlet")
    if inlet is None:
        return None
    total_area = sum(
        face_area_magnitude(points, faces_list[fi])
        for fi in range(inlet["startFace"], inlet["startFace"] + inlet["nFaces"])
    )
    return 1.0 * total_area  # U_in = 1 m/s


# ------------------------------------------------------------------ main


def main():
    latest_time = find_latest_time(CASE_DIR)

    # Convergence data
    residuals = extract_final_residuals(LOG_FILE)
    continuity = extract_continuity_error(LOG_FILE)
    n_iter = count_iterations(LOG_FILE)
    converged = bool(residuals and all(v < 1e-4 for v in residuals.values()))

    # Reattachment length
    x_r = compute_reattachment_length(CASE_DIR, latest_time)
    xr_over_h = x_r / STEP_HEIGHT if x_r is not None else None
    if xr_over_h is not None:
        accuracy_err = (
            abs(xr_over_h - EXPERIMENTAL_XR_OVER_H)
            / EXPERIMENTAL_XR_OVER_H
            * 100.0
        )
    else:
        accuracy_err = None

    # Mass conservation
    q_in = compute_inlet_mass_flow(CASE_DIR)
    if continuity is not None and q_in and q_in > 0:
        mass_err_pct = abs(continuity) / q_in * 100.0
    else:
        mass_err_pct = None
    mass_ok = mass_err_pct is not None and mass_err_pct < 1.0

    # Verdict
    verdict = (
        "pass"
        if (
            converged
            and xr_over_h is not None
            and 3.0 <= xr_over_h <= 12.0
            and mass_ok
        )
        else "fail"
    )

    report = {
        "reattachment_length_m": x_r,
        "step_height_m": STEP_HEIGHT,
        "xr_over_h": xr_over_h,
        "experimental_xr_over_h": EXPERIMENTAL_XR_OVER_H,
        "accuracy_percent_error": accuracy_err,
        "inlet_mass_flow_m3s": q_in,
        "continuity_error_final": continuity,
        "mass_conservation_ok": mass_ok,
        "final_residuals": residuals,
        "converged": converged,
        "total_iterations": n_iter,
        "validation_verdict": verdict,
    }

    out_path = os.path.join(CASE_DIR, "validation_report.json")
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Validation report written to {out_path}")
    if x_r is not None and xr_over_h is not None:
        print(f"  Reattachment: x_r = {x_r:.4f} m, x_r/h = {xr_over_h:.2f}")
        print(f"  Experimental: x_r/h = {EXPERIMENTAL_XR_OVER_H}")
        print(f"  Accuracy error: {accuracy_err:.1f}%")
    print(f"  Converged: {converged}")
    print(f"  Mass conservation OK: {mass_ok}")
    print(f"  Verdict: {verdict}")


if __name__ == "__main__":
    main()
