#!/usr/bin/env python3
"""
NAFEMS LE10 Benchmark Pipeline
Reads Abaqus .inp with implicit mesh generation cards,
expands to explicit CalculiX input, solves, parses .frd, writes results.json.
"""

import os
import re
import json
import math
import subprocess
import sys


def parse_keyword_line(line):
    """Parse '*KEYWORD,PARAM1=VAL1,PARAM2' into (keyword, {params})."""
    stripped = line.strip()
    tokens = []
    current = ""
    for ch in stripped:
        if ch == ",":
            tokens.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        tokens.append(current.strip())

    keyword = tokens[0].lstrip("*").upper().strip()
    params = {}
    for tok in tokens[1:]:
        tok = tok.strip()
        if "=" in tok:
            k, v = tok.split("=", 1)
            params[k.strip().upper()] = v.strip()
        elif tok:
            params[tok.upper()] = True
    return keyword, params


def parse_abaqus_input(filename):
    """Parse the Abaqus .inp file, expanding *NCOPY, *ELGEN, *NSET GEN."""
    nodes = {}          # node_id -> (x, y, z)
    node_sets = {}      # name -> set of node_ids
    elements = {}       # elem_id -> (type, [node_ids])
    elem_sets = {}      # name -> set of elem_ids
    material_name = None
    material_E = None
    material_nu = None

    with open(filename) as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\n")
        stripped = line.strip()

        # Skip blank lines and comments
        if not stripped or stripped.startswith("**"):
            i += 1
            continue

        if not stripped.startswith("*"):
            i += 1
            continue

        keyword, params = parse_keyword_line(stripped)

        if keyword == "HEADING":
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("*"):
                i += 1
            continue

        elif keyword == "NODE":
            nset_name = params.get("NSET")
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith("*"):
                parts = lines[i].strip().split(",")
                nid = int(parts[0].strip())
                x = float(parts[1].strip())
                y = float(parts[2].strip())
                z = float(parts[3].strip()) if len(parts) > 3 else 0.0
                nodes[nid] = (x, y, z)
                if nset_name:
                    node_sets.setdefault(nset_name, set()).add(nid)
                i += 1
            continue

        elif keyword == "NCOPY":
            old_set = params.get("OLDSET", params.get("OLD SET"))
            new_set = params.get("NEWSET", params.get("NEW SET"))
            change_num = int(params.get("CHANGE NUMBER", "0"))
            i += 1
            # Read shift vector
            shift_line = lines[i].strip()
            shift_parts = shift_line.rstrip(",").split(",")
            dx = float(shift_parts[0].strip())
            dy = float(shift_parts[1].strip())
            dz = float(shift_parts[2].strip()) if len(shift_parts) > 2 else 0.0
            i += 1

            # Expand: copy nodes from old_set with shifted coords and new IDs
            new_ids = set()
            for nid in sorted(node_sets.get(old_set, [])):
                new_nid = nid + change_num
                ox, oy, oz = nodes[nid]
                nodes[new_nid] = (ox + dx, oy + dy, oz + dz)
                new_ids.add(new_nid)
            node_sets[new_set] = new_ids
            continue

        elif keyword == "ELEMENT":
            elem_type = params.get("TYPE", "C3D20")
            elset_name = params.get("ELSET")
            i += 1

            # Accumulate all numeric data for elements
            all_nums = []
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith("*"):
                data = lines[i].strip().rstrip(",")
                parts = [p.strip() for p in data.split(",") if p.strip()]
                all_nums.extend(int(p) for p in parts)
                i += 1

            # Determine nodes per element from type
            type_nodes = {"C3D20": 20, "C3D20R": 20, "C3D10": 10, "C3D8": 8, "C3D4": 4}
            nnodes = type_nodes.get(elem_type, 20)
            chunk_size = 1 + nnodes  # elem_id + nodes

            idx = 0
            while idx + chunk_size <= len(all_nums):
                eid = all_nums[idx]
                enodes = all_nums[idx + 1 : idx + chunk_size]
                elements[eid] = (elem_type, enodes)
                if elset_name:
                    elem_sets.setdefault(elset_name, set()).add(eid)
                idx += chunk_size
            continue

        elif keyword == "ELGEN":
            elset_name = params.get("ELSET")
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith("*"):
                data = lines[i].strip().rstrip(",")
                parts = [p.strip() for p in data.split(",") if p.strip()]
                vals = [int(p) for p in parts]

                seed_id = vals[0]
                nc1 = vals[1] if len(vals) > 1 else 1
                ninc1 = vals[2] if len(vals) > 2 else 0
                einc1 = vals[3] if len(vals) > 3 else 0
                nc2 = vals[4] if len(vals) > 4 else 1
                ninc2 = vals[5] if len(vals) > 5 else 0
                einc2 = vals[6] if len(vals) > 6 else 0
                nc3 = vals[7] if len(vals) > 7 else 1
                ninc3 = vals[8] if len(vals) > 8 else 0
                einc3 = vals[9] if len(vals) > 9 else 0

                seed_type, seed_nodes = elements[seed_id]

                for k in range(nc3):
                    for j in range(nc2):
                        for ii in range(nc1):
                            new_eid = seed_id + ii * einc1 + j * einc2 + k * einc3
                            node_offset = ii * ninc1 + j * ninc2 + k * ninc3
                            new_nodes = [n + node_offset for n in seed_nodes]

                            if new_eid != seed_id or (ii == 0 and j == 0 and k == 0):
                                elements[new_eid] = (seed_type, new_nodes)

                            if elset_name:
                                elem_sets.setdefault(elset_name, set()).add(new_eid)

                i += 1
            continue

        elif keyword == "NSET":
            set_name = params.get("NSET")
            is_gen = "GEN" in params or "GENERATE" in params
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith("*"):
                data = lines[i].strip().rstrip(",")
                parts = [p.strip() for p in data.split(",") if p.strip()]
                if is_gen:
                    start = int(parts[0])
                    end = int(parts[1])
                    step = int(parts[2]) if len(parts) > 2 else 1
                    for nid in range(start, end + 1, step):
                        node_sets.setdefault(set_name, set()).add(nid)
                else:
                    for p in parts:
                        node_sets.setdefault(set_name, set()).add(int(p))
                i += 1
            continue

        elif keyword == "ELSET":
            set_name = params.get("ELSET")
            is_gen = "GEN" in params or "GENERATE" in params
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith("*"):
                data = lines[i].strip().rstrip(",")
                parts = [p.strip() for p in data.split(",") if p.strip()]
                if is_gen:
                    start = int(parts[0])
                    end = int(parts[1])
                    step = int(parts[2]) if len(parts) > 2 else 1
                    for eid in range(start, end + 1, step):
                        elem_sets.setdefault(set_name, set()).add(eid)
                else:
                    for p in parts:
                        elem_sets.setdefault(set_name, set()).add(int(p))
                i += 1
            continue

        elif keyword == "MATERIAL":
            material_name = params.get("NAME", "MATERIAL")
            i += 1
            continue

        elif keyword == "ELASTIC":
            i += 1
            if i < len(lines):
                data = lines[i].strip().rstrip(",")
                parts = [p.strip() for p in data.split(",") if p.strip()]
                material_E = float(parts[0])
                material_nu = float(parts[1])
                i += 1
            continue

        else:
            # Skip other keywords and their data
            i += 1
            while i < len(lines) and lines[i].strip() and not lines[i].strip().startswith("*"):
                i += 1
            continue

    # Filter element sets to only contain existing elements
    for name in list(elem_sets.keys()):
        elem_sets[name] = elem_sets[name] & set(elements.keys())

    return {
        "nodes": nodes,
        "node_sets": node_sets,
        "elements": elements,
        "elem_sets": elem_sets,
        "material_name": material_name,
        "material_E": material_E,
        "material_nu": material_nu,
    }


def write_ccx_input(data, output_file):
    """Write CalculiX-compatible .inp file from expanded data."""
    nodes = data["nodes"]
    node_sets = data["node_sets"]
    elements = data["elements"]
    elem_sets = data["elem_sets"]

    with open(output_file, "w") as f:
        f.write("*HEADING\n")
        f.write("NAFEMS LE10 - Expanded from Abaqus input for CalculiX\n")

        # Nodes
        f.write("*NODE\n")
        for nid in sorted(nodes.keys()):
            x, y, z = nodes[nid]
            f.write(f"  {nid}, {x:.7E}, {y:.7E}, {z:.7E}\n")

        # Elements (grouped by type)
        for etype in sorted(set(t for t, _ in elements.values())):
            f.write(f"*ELEMENT,TYPE={etype}\n")
            for eid in sorted(elements.keys()):
                et, enodes = elements[eid]
                if et != etype:
                    continue
                parts = [str(eid)] + [str(n) for n in enodes]
                # Write first 16 values (eid + 15 nodes), then remaining
                if len(parts) > 16:
                    f.write(",".join(parts[:16]) + ",\n")
                    f.write(",".join(parts[16:]) + "\n")
                else:
                    f.write(",".join(parts) + "\n")

        # Node sets
        for name in sorted(node_sets.keys()):
            f.write(f"*NSET,NSET={name}\n")
            sorted_ids = sorted(node_sets[name])
            for j in range(0, len(sorted_ids), 10):
                chunk = sorted_ids[j : j + 10]
                f.write(",".join(str(n) for n in chunk) + "\n")

        # Element sets
        for name in sorted(elem_sets.keys()):
            if not elem_sets[name]:
                continue
            f.write(f"*ELSET,ELSET={name}\n")
            sorted_ids = sorted(elem_sets[name])
            for j in range(0, len(sorted_ids), 10):
                chunk = sorted_ids[j : j + 10]
                f.write(",".join(str(e) for e in chunk) + "\n")

        # Material
        f.write(f"*MATERIAL,NAME={data['material_name']}\n")
        f.write("*ELASTIC\n")
        f.write(f"  {data['material_E']},{data['material_nu']}\n")

        # Solid section
        f.write("*SOLID SECTION,ELSET=ALLE,MATERIAL=MATPROP\n")

        # Boundary conditions (all under one *BOUNDARY, matching original)
        f.write("*BOUNDARY\n")
        f.write("AB,1\n")
        f.write("DC,2\n")
        f.write("BC,1,2\n")
        f.write("MID,3\n")

        # Step
        f.write("*STEP\n")
        f.write("*STATIC\n")

        # Distributed load
        f.write("*DLOAD\n")
        f.write("LOAD,P2,1.0E6\n")

        # Output requests
        f.write("*EL FILE,ELSET=EOUT\n")
        f.write("S\n")
        f.write("*NODE FILE\n")
        f.write("U\n")

        f.write("*END STEP\n")


def parse_frd(frd_file, target_node_id=None, target_coords=None, nodes_dict=None):
    """
    Parse CalculiX .frd file.
    Returns (node_id, stress_dict, frd_nodes_dict).
    stress_dict has keys SXX, SYY, SZZ, SXY, SYZ, SZX.
    """
    with open(frd_file) as f:
        lines = f.readlines()

    # Parse node coordinates from coordinate block
    frd_nodes = {}
    in_coords = False
    for line in lines:
        if line.startswith("    2C"):
            in_coords = True
            continue
        if in_coords and line.startswith(" -3"):
            in_coords = False
            continue
        if in_coords and line.startswith(" -1"):
            # Fixed-width: " -1" (3) + node_id (10) + x (12) + y (12) + z (12)
            try:
                nid = int(line[3:13])
                x = float(line[13:25])
                y = float(line[25:37])
                z = float(line[37:49])
                frd_nodes[nid] = (x, y, z)
            except (ValueError, IndexError):
                continue

    # If no target node specified, find closest to target_coords
    if target_node_id is None and target_coords is not None:
        min_dist = float("inf")
        for nid, (x, y, z) in frd_nodes.items():
            dist = math.sqrt(
                (x - target_coords[0]) ** 2
                + (y - target_coords[1]) ** 2
                + (z - target_coords[2]) ** 2
            )
            if dist < min_dist:
                min_dist = dist
                target_node_id = nid

    # Also try from the provided nodes dict if frd_nodes is empty or insufficient
    if target_node_id is None and nodes_dict is not None and target_coords is not None:
        min_dist = float("inf")
        for nid, (x, y, z) in nodes_dict.items():
            dist = math.sqrt(
                (x - target_coords[0]) ** 2
                + (y - target_coords[1]) ** 2
                + (z - target_coords[2]) ** 2
            )
            if dist < min_dist:
                min_dist = dist
                target_node_id = nid

    # Parse stress data
    stress = None
    in_stress = False
    for line in lines:
        if " -4  STRESS" in line or " -4  STRESS" in line.replace("\t", " "):
            in_stress = True
            continue
        if in_stress and line.startswith(" -3"):
            in_stress = False
            continue
        if in_stress and line.startswith(" -1"):
            # Fixed-width: " -1" (3) + node_id (10) + SXX(12) + SYY(12)
            #              + SZZ(12) + SXY(12) + SYZ(12) + SZX(12)
            try:
                nid = int(line[3:13])
                if nid == target_node_id:
                    sxx = float(line[13:25])
                    syy = float(line[25:37])
                    szz = float(line[37:49])
                    sxy = float(line[49:61])
                    syz = float(line[61:73])
                    szx = float(line[73:85])
                    stress = {
                        "SXX": sxx,
                        "SYY": syy,
                        "SZZ": szz,
                        "SXY": sxy,
                        "SYZ": syz,
                        "SZX": szx,
                    }
                    break
            except (ValueError, IndexError):
                continue

    return target_node_id, stress, frd_nodes


def find_ccx():
    """Find the CalculiX executable."""
    for name in ["ccx", "ccx_2.21", "ccx_2.20", "ccx_2.19"]:
        result = subprocess.run(["which", name], capture_output=True, text=True)
        if result.returncode == 0:
            return name
    # Try glob for any ccx version
    import glob

    for path in glob.glob("/usr/bin/ccx*"):
        return os.path.basename(path)
    return "ccx"


def main():
    os.chdir("/app")

    # Step 1: Parse and expand Abaqus input
    print("=" * 60)
    print("Step 1: Parsing and expanding Abaqus input...")
    data = parse_abaqus_input("/app/le10_abaqus.inp")
    print(f"  Nodes: {len(data['nodes'])}")
    print(f"  Elements: {len(data['elements'])}")
    print(f"  Node sets: {list(data['node_sets'].keys())}")
    print(f"  Element sets: {list(data['elem_sets'].keys())}")
    print(f"  Material: {data['material_name']}, E={data['material_E']}, nu={data['material_nu']}")

    # Step 2: Find point D on the top surface of the plate
    # NAFEMS LE10: point D is at the inner boundary on the top surface.
    # The Abaqus model places the plate from z=0 to z=0.6m,
    # so the top surface is at z=0.6m.
    print("\nStep 2: Finding point D...")
    target_coords = (2.0, 0.0, 0.6)
    min_dist = float("inf")
    point_d_node = None
    for nid, coords in data["nodes"].items():
        dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(coords, target_coords)))
        if dist < min_dist:
            min_dist = dist
            point_d_node = nid
    print(f"  Node {point_d_node} at {data['nodes'][point_d_node]} (distance: {min_dist:.8f} m)")

    # Step 3: Write CalculiX input
    print("\nStep 3: Writing CalculiX input...")
    ccx_input = "/app/le10_ccx.inp"
    write_ccx_input(data, ccx_input)
    print(f"  Written to {ccx_input}")

    # Step 4: Run CalculiX
    print("\nStep 4: Running CalculiX...")
    ccx_cmd = find_ccx()
    print(f"  Using: {ccx_cmd}")
    result = subprocess.run(
        [ccx_cmd, "le10_ccx"],
        capture_output=True,
        text=True,
        cwd="/app",
        timeout=300,
    )
    print(f"  Return code: {result.returncode}")
    if result.stdout:
        # Print last 20 lines of stdout
        stdout_lines = result.stdout.strip().split("\n")
        for line in stdout_lines[-20:]:
            print(f"  [ccx] {line}")
    if result.returncode != 0 and result.stderr:
        print(f"  STDERR: {result.stderr[:500]}")

    # Step 5: Parse FRD output
    print("\nStep 5: Parsing .frd output...")
    frd_file = "/app/le10_ccx.frd"
    if not os.path.isfile(frd_file):
        print(f"  ERROR: {frd_file} not found!")
        # Try to find any .frd file
        import glob as g

        frd_files = g.glob("/app/*.frd")
        if frd_files:
            frd_file = frd_files[0]
            print(f"  Using alternative: {frd_file}")
        else:
            print("  No .frd files found. CalculiX may have failed.")
            sys.exit(1)

    node_id, stress, frd_nodes = parse_frd(
        frd_file, target_node_id=point_d_node, nodes_dict=data["nodes"]
    )

    if stress is None:
        # Try finding by coordinates if specific node didn't have stress data
        print(f"  No stress data for node {point_d_node}, searching by coordinates...")
        node_id, stress, frd_nodes = parse_frd(
            frd_file, target_coords=target_coords, nodes_dict=data["nodes"]
        )

    if stress is None:
        print("  ERROR: Could not extract stress at point D!")
        print("  Attempting to read all stress entries from .frd...")
        # Debug: print all stress entries
        with open(frd_file) as f:
            frd_lines = f.readlines()
        in_stress = False
        for line in frd_lines:
            if " -4  STRESS" in line:
                in_stress = True
                print(f"  Found STRESS block: {line.rstrip()}")
                continue
            if in_stress and line.startswith(" -3"):
                in_stress = False
                continue
            if in_stress and line.startswith(" -1"):
                try:
                    nid = int(line[3:13])
                    syy = float(line[25:37])
                    print(f"    Node {nid}: SYY = {syy:.4e}")
                except:
                    pass
        sys.exit(1)

    sigma_y_Pa = stress["SYY"]
    sigma_y_MPa = sigma_y_Pa / 1e6
    reference = -5.38
    relative_error = abs(sigma_y_MPa - reference) / abs(reference) * 100

    print(f"  Node: {node_id}")
    print(f"  SYY = {sigma_y_Pa:.6e} Pa = {sigma_y_MPa:.4f} MPa")
    print(f"  Reference: {reference} MPa")
    print(f"  Relative error: {relative_error:.2f}%")

    # Step 6: Write results
    print("\nStep 6: Writing results.json...")
    results = {
        "num_nodes": len(data["nodes"]),
        "num_elements": len(data["elements"]),
        "point_D_node_id": node_id,
        "point_D_coords_m": list(data["nodes"][node_id]),
        "sigma_y_Pa": sigma_y_Pa,
        "sigma_y_MPa": sigma_y_MPa,
        "relative_error_pct": relative_error,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"  Written to /app/results.json")
    print("\n" + "=" * 60)
    print(f"RESULT: sigma_y at D = {sigma_y_MPa:.4f} MPa (ref: {reference} MPa, err: {relative_error:.2f}%)")
    print("=" * 60)


if __name__ == "__main__":
    main()
