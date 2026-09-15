#!/usr/bin/env python3
"""MEGADOCK decoy generator.

Reads a MEGADOCK .out file and a ligand PDB, applies the rotation/translation
for a given pose, and writes the transformed ligand PDB.

Usage: decoygen <docking.out> <ligand.pdb> <pose_number> <output.pdb>
"""

import sys
import math


def parse_out(filename, pose_num):
    """Parse a MEGADOCK .out file and return parameters for a given pose."""
    with open(filename) as f:
        lines = f.readlines()

    # Line 1: N spacing
    parts = lines[0].split()
    N = int(parts[0])
    spacing = float(parts[1])

    # Line 2: rand1 rand2 rand3
    parts = lines[1].split()
    rand1, rand2, rand3 = float(parts[0]), float(parts[1]), float(parts[2])

    # Line 3: receptor_file r1 r2 r3
    parts = lines[2].split()
    r1, r2, r3 = float(parts[1]), float(parts[2]), float(parts[3])

    # Line 4: ligand_file l1 l2 l3
    parts = lines[3].split()
    l1, l2, l3 = float(parts[1]), float(parts[2]), float(parts[3])

    # Lines 5+: poses (1-indexed)
    pose_line = lines[3 + pose_num]
    parts = pose_line.split()
    a1, a2, a3 = float(parts[0]), float(parts[1]), float(parts[2])
    t1, t2, t3 = int(float(parts[3])), int(float(parts[4])), int(float(parts[5]))
    score = float(parts[6])

    return {
        "N": N, "spacing": spacing,
        "rand1": rand1, "rand2": rand2, "rand3": rand3,
        "r1": r1, "r2": r2, "r3": r3,
        "l1": l1, "l2": l2, "l3": l3,
        "a1": a1, "a2": a2, "a3": a3,
        "t1": t1, "t2": t2, "t3": t3,
        "score": score,
    }


def euler_rotation_matrix(psi, theta, phi):
    """Compute ZYZ Euler rotation matrix matching MEGADOCK convention."""
    r11 = math.cos(psi)*math.cos(phi) - math.sin(psi)*math.cos(theta)*math.sin(phi)
    r21 = math.sin(psi)*math.cos(phi) + math.cos(psi)*math.cos(theta)*math.sin(phi)
    r31 = math.sin(theta)*math.sin(phi)

    r12 = -math.cos(psi)*math.sin(phi) - math.sin(psi)*math.cos(theta)*math.cos(phi)
    r22 = -math.sin(psi)*math.sin(phi) + math.cos(psi)*math.cos(theta)*math.cos(phi)
    r32 = math.sin(theta)*math.cos(phi)

    r13 = math.sin(psi)*math.sin(theta)
    r23 = -math.cos(psi)*math.sin(theta)
    r33 = math.cos(theta)

    return [[r11, r12, r13], [r21, r22, r23], [r31, r32, r33]]


def rotate_atom(x, y, z, R):
    """Apply rotation matrix to a coordinate."""
    nx = R[0][0]*x + R[0][1]*y + R[0][2]*z
    ny = R[1][0]*x + R[1][1]*y + R[1][2]*z
    nz = R[2][0]*x + R[2][1]*y + R[2][2]*z
    return nx, ny, nz


def generate_decoy(out_file, lig_file, pose_num, output_file):
    """Generate a decoy PDB by applying MEGADOCK transformation."""
    params = parse_out(out_file, pose_num)

    R_rand = euler_rotation_matrix(params["rand1"], params["rand2"], params["rand3"])
    R_pose = euler_rotation_matrix(params["a1"], params["a2"], params["a3"])

    t1, t2, t3 = params["t1"], params["t2"], params["t3"]
    N = params["N"]
    spacing = params["spacing"]

    # Wrap grid translations
    if t1 >= N // 2:
        t1 -= N
    if t2 >= N // 2:
        t2 -= N
    if t3 >= N // 2:
        t3 -= N

    l1, l2, l3 = params["l1"], params["l2"], params["l3"]
    r1, r2, r3 = params["r1"], params["r2"], params["r3"]

    with open(lig_file) as fin, open(output_file, "w") as fout:
        for line in fin:
            if line.startswith("ATOM") or line.startswith("HETATM"):
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])

                # Step 1: Center on ligand
                cx, cy, cz = x - l1, y - l2, z - l3

                # Step 2: Apply random rotation
                tx, ty, tz = rotate_atom(cx, cy, cz, R_rand)

                # Step 3: Apply pose rotation
                fx, fy, fz = rotate_atom(tx, ty, tz, R_pose)

                # Step 4: Apply grid translation and receptor center
                fx = fx - t1 * spacing + r1
                fy = fy - t2 * spacing + r2
                fz = fz - t3 * spacing + r3

                new_line = line[:30] + f"{fx:8.3f}{fy:8.3f}{fz:8.3f}" + line[54:]
                fout.write(new_line)
            elif line.startswith("TER") or line.startswith("END"):
                fout.write(line)


def main():
    if len(sys.argv) != 5:
        print(f"Usage: {sys.argv[0]} <docking.out> <ligand.pdb> <pose_number> <output.pdb>")
        sys.exit(1)

    out_file = sys.argv[1]
    lig_file = sys.argv[2]
    pose_num = int(sys.argv[3])
    output_file = sys.argv[4]

    generate_decoy(out_file, lig_file, pose_num, output_file)


if __name__ == "__main__":
    main()
