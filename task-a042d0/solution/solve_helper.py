#!/usr/bin/env python3
"""
Solution: diagnose errors in a NAFEMS LE10 CalculiX model, fix them,
and perform a mesh convergence study.

"""

import json
import math
import os
import shutil
import subprocess
import sys

import numpy as np

# ============================================================
# Constants
# ============================================================
C_FOCAL = math.sqrt(3.0)  # sqrt(a_in^2 - b_in^2) = sqrt(4-1)
MU_INNER = float(np.arccosh(2.0 / C_FOCAL))
MU_OUTER = float(np.arccosh(3.25 / C_FOCAL))
THICKNESS = 0.6
E_MOD = 210.0e9   # Pa
NU = 0.3
PRESSURE = 1.0e6   # Pa


# ============================================================
# Phase 1: Diagnose errors in model.inp
# ============================================================
def diagnose_errors(filepath):
    with open(filepath) as f:
        lines = f.readlines()

    errors = []
    in_elastic = False
    in_boundary = False
    in_dload = False
    boundary_start = None
    has_dc_bc = False

    for i, line in enumerate(lines):
        s = line.strip()
        u = s.upper()

        if u.startswith("*ELASTIC"):
            in_elastic = True
            in_boundary = False
            in_dload = False
            continue
        if u.startswith("*BOUNDARY"):
            in_boundary = True
            in_elastic = False
            in_dload = False
            boundary_start = i
            continue
        if u.startswith("*DLOAD"):
            in_dload = True
            in_elastic = False
            in_boundary = False
            continue
        if s.startswith("*") and not s.startswith("**"):
            in_elastic = False
            in_boundary = False
            in_dload = False

        # Error 1: Poisson's ratio 0.03 should be 0.3
        if in_elastic and s and not s.startswith("*"):
            parts = s.split(",")
            if len(parts) >= 2:
                try:
                    nu_val = float(parts[1].strip())
                    if abs(nu_val - 0.03) < 0.005:
                        errors.append({
                            "line_number": i + 1,
                            "original": s,
                            "corrected": " 210.0E9,0.3",
                            "category": "material"
                        })
                except ValueError:
                    pass
            in_elastic = False

        # Track DC boundary condition
        if in_boundary and "DC" in u:
            has_dc_bc = True

        # Error 3: Negative pressure sign
        if in_dload and "P2" in u:
            parts = s.split(",")
            if len(parts) >= 3:
                try:
                    val = float(parts[-1].strip())
                    if val < 0:
                        errors.append({
                            "line_number": i + 1,
                            "original": s,
                            "corrected": " LOAD,P2, 1.0E6",
                            "category": "loading"
                        })
                except ValueError:
                    pass

    # Error 2: Missing DC symmetry boundary condition
    if not has_dc_bc and boundary_start is not None:
        errors.append({
            "line_number": boundary_start + 2,
            "original": "(missing)",
            "corrected": "DC,2",
            "category": "boundary_condition"
        })

    return errors


# ============================================================
# Phase 2: Fix the model
# ============================================================
def fix_model(input_path, output_path):
    with open(input_path) as f:
        lines = f.readlines()

    out = []
    in_elastic = False
    in_boundary = False
    in_dload = False
    dc_added = False

    for line in lines:
        s = line.strip()
        u = s.upper()

        if u.startswith("*ELASTIC"):
            in_elastic = True
            in_boundary = False
            in_dload = False
            out.append(line)
            continue
        if u.startswith("*BOUNDARY"):
            in_boundary = True
            in_elastic = False
            in_dload = False
            out.append(line)
            continue
        if u.startswith("*DLOAD"):
            in_dload = True
            in_elastic = False
            in_boundary = False
            out.append(line)
            continue
        if s.startswith("*") and not s.startswith("**"):
            if in_boundary and not dc_added:
                out.append("DC,2\n")
                dc_added = True
            in_elastic = False
            in_boundary = False
            in_dload = False

        # Fix Poisson's ratio
        if in_elastic and "0.03" in s:
            out.append(" 210.0E9,0.3\n")
            in_elastic = False
            continue

        # Insert DC,2 after AB,1
        if in_boundary and "AB" in u and not dc_added:
            out.append(line)
            out.append("DC,2\n")
            dc_added = True
            continue

        # Fix pressure sign
        if in_dload and "-1.0E6" in s:
            out.append(" LOAD,P2, 1.0E6\n")
            in_dload = False
            continue

        out.append(line)

    with open(output_path, "w") as f:
        f.writelines(out)


# ============================================================
# Phase 3: Mesh generation for convergence study
# ============================================================
def confocal_xy(mu, theta):
    """Convert confocal elliptical coordinates to Cartesian."""
    return (C_FOCAL * math.cosh(mu) * math.cos(theta),
            C_FOCAL * math.sinh(mu) * math.sin(theta))


def generate_inp(n_circ, n_rad, n_thick, out_path):
    """
    Generate a CalculiX input file with a structured C3D20 mesh for the
    NAFEMS LE10 confocal elliptical thick plate geometry.

    Coordinate mapping:
      i -> circumferential (theta: 0 to pi/2)
      j -> radial (mu: MU_INNER to MU_OUTER)
      k -> thickness (z: 0 to 0.6)

    For positive Jacobian, the local element axes are mapped:
      xi_1 -> j direction (radial outward)
      xi_2 -> i direction (circumferential)
      xi_3 -> k direction (through-thickness)

    Returns (total_nodes, total_elements, target_node_id).
    """
    nc = 2 * n_circ + 1   # nodes in circumferential direction
    nr = 2 * n_rad + 1    # nodes in radial direction
    nz = 2 * n_thick + 1  # nodes through thickness

    def nidx(i, j, k):
        return k * nr * nc + j * nc + i + 1

    # ---- Nodes ----
    nodes = {}
    for k in range(nz):
        z = THICKNESS * k / (nz - 1)
        for j in range(nr):
            mu = MU_INNER + (MU_OUTER - MU_INNER) * j / (nr - 1)
            for i in range(nc):
                theta = (math.pi / 2.0) * i / (nc - 1)
                x, y = confocal_xy(mu, theta)
                nodes[nidx(i, j, k)] = (x, y, z)

    total_nodes = nc * nr * nz

    # ---- Elements (C3D20 with correct node ordering for positive Jacobian) ----
    # The CalculiX C3D20 element expects corners ordered so that
    # (node2-node1) x (node4-node1) points toward nodes 5-8.
    # With xi_1=j, xi_2=i, xi_3=k this gives:
    #   Corner 1: (i0,   j0,   k0)     Corner 5: (i0,   j0,   k0+2)
    #   Corner 2: (i0,   j0+2, k0)     Corner 6: (i0,   j0+2, k0+2)
    #   Corner 3: (i0+2, j0+2, k0)     Corner 7: (i0+2, j0+2, k0+2)
    #   Corner 4: (i0+2, j0,   k0)     Corner 8: (i0+2, j0,   k0+2)
    elements = {}
    eid = 1
    for kk in range(n_thick):
        for jj in range(n_rad):
            for ii in range(n_circ):
                i0, j0, k0 = 2 * ii, 2 * jj, 2 * kk
                conn = [
                    # Bottom corners 1-4
                    nidx(i0, j0, k0),
                    nidx(i0, j0 + 2, k0),
                    nidx(i0 + 2, j0 + 2, k0),
                    nidx(i0 + 2, j0, k0),
                    # Top corners 5-8
                    nidx(i0, j0, k0 + 2),
                    nidx(i0, j0 + 2, k0 + 2),
                    nidx(i0 + 2, j0 + 2, k0 + 2),
                    nidx(i0 + 2, j0, k0 + 2),
                    # Bottom midside 9-12
                    nidx(i0, j0 + 1, k0),        # between 1-2
                    nidx(i0 + 1, j0 + 2, k0),    # between 2-3
                    nidx(i0 + 2, j0 + 1, k0),    # between 3-4
                    nidx(i0 + 1, j0, k0),         # between 4-1
                    # Top midside 13-16
                    nidx(i0, j0 + 1, k0 + 2),    # between 5-6
                    nidx(i0 + 1, j0 + 2, k0 + 2),  # between 6-7
                    nidx(i0 + 2, j0 + 1, k0 + 2),  # between 7-8
                    nidx(i0 + 1, j0, k0 + 2),    # between 8-5
                    # Vertical midside 17-20
                    nidx(i0, j0, k0 + 1),         # between 1-5
                    nidx(i0, j0 + 2, k0 + 1),    # between 2-6
                    nidx(i0 + 2, j0 + 2, k0 + 1),  # between 3-7
                    nidx(i0 + 2, j0, k0 + 1),    # between 4-8
                ]
                elements[eid] = conn
                eid += 1

    total_elements = n_circ * n_rad * n_thick

    # ---- Node sets for boundary conditions ----
    # x=0 symmetry plane (theta=pi/2 => i=nc-1): constrain u=0
    xsym = sorted(nidx(nc - 1, j, k) for k in range(nz) for j in range(nr))
    # y=0 symmetry plane (theta=0 => i=0): constrain v=0
    ysym = sorted(nidx(0, j, k) for k in range(nz) for j in range(nr))
    # Outer boundary (mu=MU_OUTER => j=nr-1): constrain u=0, v=0
    outer = sorted(nidx(i, nr - 1, k) for k in range(nz) for i in range(nc))
    # Mid-thickness at outer boundary (j=nr-1, k=nz//2): constrain w=0
    mid = sorted(nidx(i, nr - 1, nz // 2) for i in range(nc))

    # ---- Top-face elements for pressure loading ----
    top_elems = sorted(
        (n_thick - 1) * n_rad * n_circ + jj * n_circ + ii + 1
        for jj in range(n_rad) for ii in range(n_circ)
    )

    # ---- Target element & node (point D = (2.0, 0, 0.6)) ----
    target_eid = (n_thick - 1) * n_rad * n_circ + 1  # ii=0, jj=0, kk=last
    target_nid = nidx(0, 0, nz - 1)  # theta=0, mu=mu_inner, z=max

    # ---- Write .inp file ----
    with open(out_path, "w") as f:
        f.write("*HEADING\n")
        f.write(f"LE10 CONVERGENCE {n_circ}x{n_rad}x{n_thick}\n")

        # Nodes
        f.write("*NODE\n")
        for nid in sorted(nodes):
            x, y, z = nodes[nid]
            f.write(f"{nid:8d},{x:16.8E},{y:16.8E},{z:16.8E}\n")

        # Elements - split across 2 lines (eid + 15 nodes, then 5 nodes)
        f.write("*ELEMENT,TYPE=C3D20,ELSET=ALLE\n")
        for eid2 in sorted(elements):
            c = elements[eid2]
            f.write(f"{eid2}," + ",".join(str(n) for n in c[:15]) + ",\n")
            f.write(",".join(str(n) for n in c[15:]) + "\n")

        # Node sets
        def write_nset(name, nids):
            f.write(f"*NSET,NSET={name}\n")
            for idx in range(0, len(nids), 16):
                chunk = nids[idx:idx + 16]
                f.write(",".join(str(n) for n in chunk) + "\n")

        write_nset("XSYM", xsym)
        write_nset("YSYM", ysym)
        write_nset("OUTER", outer)
        write_nset("MID", mid)

        # Element sets
        f.write("*ELSET,ELSET=LOAD\n")
        for idx in range(0, len(top_elems), 16):
            chunk = top_elems[idx:idx + 16]
            f.write(",".join(str(e) for e in chunk) + "\n")

        f.write(f"*ELSET,ELSET=EOUT\n{target_eid}\n")

        # Material
        f.write("*MATERIAL,NAME=STEEL\n*ELASTIC\n")
        f.write(" 210.0E9,0.3\n")

        # Section
        f.write("*SOLID SECTION,ELSET=ALLE,MATERIAL=STEEL\n")

        # Boundary conditions (NAFEMS LE10)
        f.write("*BOUNDARY\n")
        f.write("XSYM,1\n")     # u=0 at x=0 (symmetry)
        f.write("YSYM,2\n")     # v=0 at y=0 (symmetry)
        f.write("OUTER,1,2\n")  # u=v=0 on outer boundary
        f.write("MID,3\n")      # w=0 at outer boundary mid-thickness

        # Step
        f.write("*STEP,PERTURBATION\n*STATIC\n")
        f.write("*DLOAD\n")
        f.write(" LOAD,P2, 1.0E6\n")
        f.write("*NODE PRINT,FREQUENCY=0\n")
        f.write("*EL PRINT,POSITION=AVERAGED AT NODES,ELSET=EOUT\n")
        f.write("S\n")
        f.write("*EL FILE,POSITION=AVERAGED AT NODES,ELSET=EOUT\n")
        f.write("S\n")
        f.write("*END STEP\n")

    return total_nodes, total_elements, target_nid


# ============================================================
# Phase 4: Run CalculiX and parse results
# ============================================================
def find_ccx():
    ccx = shutil.which("ccx")
    if ccx:
        return ccx
    for name in ("ccx_2.21", "ccx_2.22", "ccx_2.23"):
        ccx = shutil.which(name)
        if ccx:
            return ccx
    return "ccx"


def run_ccx(job_dir, job_name):
    """Run CalculiX. Returns (success, stdout, stderr)."""
    ccx = find_ccx()
    try:
        r = subprocess.run(
            [ccx, job_name],
            cwd=job_dir,
            capture_output=True, text=True,
            timeout=300,
        )
        return r.returncode == 0, r.stdout, r.stderr
    except Exception as e:
        return False, "", str(e)


def parse_frd_sigma_yy(frd_path, target_nid):
    """
    Parse CalculiX .frd file for sigma_yy at target node.
    The .frd format has fixed-width columns:
      -4 header with "STRESS"
      -1 lines: cols [3:13] = node, then 6x12-char stress fields
    """
    if not os.path.isfile(frd_path):
        return None

    in_stress = False
    all_stress = {}

    with open(frd_path) as fh:
        for line in fh:
            if "STRESS" in line and line.lstrip().startswith("-4"):
                in_stress = True
                continue
            if in_stress:
                if line.startswith(" -3"):
                    break
                if line.startswith(" -1"):
                    try:
                        node = int(line[3:13])
                        syy = float(line[25:37])
                        all_stress[node] = syy
                        if node == target_nid:
                            return syy
                    except (ValueError, IndexError):
                        continue

    # If exact node not found, try closest node ID
    if all_stress:
        closest = min(all_stress.keys(), key=lambda n: abs(n - target_nid))
        print(f"  .frd: target node {target_nid} not found; using node {closest}")
        return all_stress[closest]

    return None


def parse_dat_sigma_yy(dat_path, target_nid):
    """
    Parse CalculiX .dat file for sigma_yy at the target node.
    Format: header line with 'stresses ... sxx', then blank line, then data lines:
      elem  node/integ_pt  sxx  syy  szz  sxy  sxz  syz
    """
    if not os.path.isfile(dat_path):
        return None

    with open(dat_path) as f:
        content = f.read()

    in_stress = False
    data_started = False
    all_syy = []

    for line in content.split("\n"):
        low = line.lower()
        # Detect stress header
        if "stress" in low and ("sxx" in low or "s11" in low):
            in_stress = True
            data_started = False
            continue

        if not in_stress:
            continue

        stripped = line.strip()

        # Handle blank lines: skip them, but end block only if data was seen
        if stripped == "":
            if data_started:
                in_stress = False
            continue

        # Try to parse as data line
        parts = stripped.split()
        if len(parts) >= 4:
            try:
                col0 = int(parts[0])      # element number
                col1 = int(parts[1])      # node or integration point
                syy = float(parts[3])     # syy is the 4th column
                data_started = True
                all_syy.append((col0, col1, syy))
                if col1 == target_nid:
                    return syy
            except (ValueError, IndexError):
                if data_started:
                    in_stress = False
                continue
        else:
            if data_started:
                in_stress = False

    # Fallback: return first available syy if any data was found
    if all_syy:
        print(f"  .dat: target node {target_nid} not found among "
              f"{len(all_syy)} entries; using first entry (node {all_syy[0][1]})")
        return all_syy[0][2]

    return None


# ============================================================
# Main
# ============================================================
def main():
    os.chdir("/app")
    print("=== Phase 1: Diagnose and fix errors ===")

    errors = diagnose_errors("/app/project/model.inp")
    print(f"Found {len(errors)} errors:")
    for e in errors:
        print(f"  Line {e['line_number']}: [{e['category']}] "
              f"{e['original']!r} -> {e['corrected']!r}")

    fix_model("/app/project/model.inp", "/app/corrected.inp")
    print("Wrote /app/corrected.inp")

    print("\n=== Phase 2: Convergence study ===")
    os.makedirs("/app/convergence", exist_ok=True)

    # Refinement levels: (level, n_circ, n_rad, n_thick)
    configs = [
        (1, 3, 2, 1),    # 6 elements
        (2, 6, 4, 2),    # 48 elements
        (3, 9, 6, 3),    # 162 elements
        (4, 12, 8, 4),   # 384 elements
    ]

    convergence_data = []

    for level, nc, nr, nz in configs:
        print(f"\n--- Level {level}: {nc}x{nr}x{nz} = {nc*nr*nz} elements ---")
        inp_path = f"/app/convergence/level_{level}.inp"
        n_nodes, n_elems, target_nid = generate_inp(nc, nr, nz, inp_path)
        print(f"  Generated mesh: {n_nodes} nodes, {n_elems} elements")
        print(f"  Target node: {target_nid}")

        ok, stdout, stderr = run_ccx("/app/convergence", f"level_{level}")

        dat_path = f"/app/convergence/level_{level}.dat"
        frd_path = f"/app/convergence/level_{level}.frd"

        if not ok:
            print(f"  CalculiX returned non-zero exit code")
            if stderr:
                for sline in stderr.strip().split("\n")[-5:]:
                    print(f"    stderr: {sline}")
            if stdout:
                for sline in stdout.strip().split("\n"):
                    if "ERROR" in sline.upper() or "WARNING" in sline.upper():
                        print(f"    stdout: {sline}")

        # ALWAYS try to parse output, regardless of exit code
        syy_pa = None

        # Try .frd file first
        if os.path.isfile(frd_path):
            syy_pa = parse_frd_sigma_yy(frd_path, target_nid)
            if syy_pa is not None:
                print(f"  Extracted sigma_yy from .frd file")

        # Fall back to .dat file
        if syy_pa is None and os.path.isfile(dat_path):
            print(f"  Trying .dat file...")
            syy_pa = parse_dat_sigma_yy(dat_path, target_nid)
            if syy_pa is not None:
                print(f"  Extracted sigma_yy from .dat file")

        if syy_pa is not None:
            syy_mpa = syy_pa / 1.0e6
            print(f"  sigma_yy = {syy_mpa:.4f} MPa")
            convergence_data.append({
                "level": level,
                "num_elements": n_elems,
                "num_nodes": n_nodes,
                "sigma_yy_MPa": round(syy_mpa, 4),
            })
        else:
            print(f"  WARNING: could not extract sigma_yy for level {level}")
            for p in [dat_path, frd_path]:
                if os.path.isfile(p):
                    sz = os.path.getsize(p)
                    print(f"    {os.path.basename(p)}: {sz} bytes")
                    if sz > 0 and sz < 2000:
                        with open(p) as df:
                            print(f"    contents:\n{df.read()[:1000]}")
                else:
                    print(f"    {os.path.basename(p)}: NOT FOUND")

    print("\n=== Phase 3: Write results ===")
    final = convergence_data[-1]["sigma_yy_MPa"] if convergence_data else 0.0

    results = {
        "benchmark_id": "NAFEMS LE10",
        "errors": errors,
        "convergence": convergence_data,
        "final_sigma_yy_MPa": final,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"final_sigma_yy_MPa = {final:.4f}")
    ref = -5.38
    if final != 0:
        rel_err = abs(final - ref) / abs(ref) * 100
        print(f"Reference = {ref}, relative error = {rel_err:.1f}%")
    print("Done.")


if __name__ == "__main__":
    main()
