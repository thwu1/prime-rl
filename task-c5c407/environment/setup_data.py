#!/usr/bin/env python3
"""Generate RNA PDB structure files for the assessment task.

Creates a reference RNA structure and five predicted model structures
with varying levels of noise, rotation/translation, modified residue
names, and missing atoms.
"""
import math
import os
import random

SEQ = "GCUAAGCUUGCAGCUAAUGC"  # 20 nucleotides
PURINES = {'G', 'A'}
OUTPUT_DIR = '/app/data'

# Helical parameters: (radius, angular_offset, z_offset)
# These approximate an A-form RNA backbone
ATOM_PARAMS = {
    "P":    (9.40,  0.000,  0.00),
    "OP1":  (10.20, 0.030,  0.30),
    "OP2":  (10.00,-0.030, -0.30),
    "O5'":  (8.90,  0.050,  0.40),
    "C5'":  (8.20,  0.100,  0.80),
    "C4'":  (7.80,  0.150,  1.20),
    "O4'":  (7.50,  0.130,  1.10),
    "C3'":  (8.00,  0.200,  1.80),
    "O3'":  (8.50,  0.250,  2.40),
    "C2'":  (7.40,  0.180,  1.50),
    "O2'":  (6.80,  0.220,  1.70),
    "C1'":  (7.20,  0.120,  1.00),
    "N9":   (6.00,  0.140,  0.90),
    "N1":   (6.00,  0.140,  0.90),
}

ELEMENT_MAP = {
    "P": "P", "OP1": "O", "OP2": "O",
    "O5'": "O", "C5'": "C", "C4'": "C", "O4'": "O",
    "C3'": "C", "O3'": "O", "C2'": "C", "O2'": "O", "C1'": "C",
    "N9": "N", "N1": "N", "O2*": "O",
}


def atoms_for_residue(base, is_first):
    atoms = []
    if not is_first:
        atoms.extend(["P", "OP1", "OP2"])
    atoms.extend(["O5'", "C5'", "C4'", "O4'", "C3'", "O3'", "C2'", "O2'", "C1'"])
    atoms.append("N9" if base in PURINES else "N1")
    return atoms


def ref_coord(res_idx, atom_name):
    theta = res_idx * 0.5707  # ~32.7 deg per residue
    z_base = res_idx * 2.81
    r, dtheta, dz = ATOM_PARAMS[atom_name]
    x = r * math.cos(theta + dtheta)
    y = r * math.sin(theta + dtheta)
    z = z_base + dz
    return (x, y, z)


def fmt_aname(name):
    if len(name) == 1:
        return " %s  " % name
    elif len(name) == 2:
        return " %s " % name
    elif len(name) == 3:
        return " %s" % name
    return name[:4]


def fmt_rname(name):
    if len(name) == 1:
        return "  %s" % name
    elif len(name) == 2:
        return " %s" % name
    return name[:3]


def write_pdb(filepath, seq, coords, chain='A',
              rname_overrides=None, aname_overrides=None, skip_atoms=None):
    with open(filepath, 'w') as f:
        serial = 1
        for i, base in enumerate(seq):
            resnum = i + 1
            is_first = (i == 0)
            atom_list = atoms_for_residue(base, is_first)

            rn = fmt_rname(rname_overrides.get(i, base) if rname_overrides else base)

            for atom in atom_list:
                if skip_atoms and i in skip_atoms and atom in skip_atoms[i]:
                    continue
                key = (i, atom)
                if key not in coords:
                    continue

                x, y, z = coords[key]
                display = atom
                if aname_overrides and key in aname_overrides:
                    display = aname_overrides[key]

                an = fmt_aname(display)
                elem = ELEMENT_MAP.get(display, display[0])

                line = (
                    "ATOM  %5d %s %s %s%4d    %8.3f%8.3f%8.3f  1.00  0.00          %2s  \n"
                    % (serial, an, rn, chain, resnum, x, y, z, elem)
                )
                f.write(line)
                serial += 1

        f.write("TER\nEND\n")


def gen_ref_coords(seq):
    coords = {}
    for i, base in enumerate(seq):
        for atom in atoms_for_residue(base, i == 0):
            coords[(i, atom)] = ref_coord(i, atom)
    return coords


def perturb(coords, sigma, seed):
    rng = random.Random(seed)
    out = {}
    for k, (x, y, z) in coords.items():
        out[k] = (x + rng.gauss(0, sigma),
                   y + rng.gauss(0, sigma),
                   z + rng.gauss(0, sigma))
    return out


def rotate_z_translate(coords, angle_deg, tx, ty, tz):
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    out = {}
    for k, (x, y, z) in coords.items():
        out[k] = (ca * x - sa * y + tx,
                   sa * x + ca * y + ty,
                   z + tz)
    return out


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ref = gen_ref_coords(SEQ)

    # Reference
    write_pdb(os.path.join(OUTPUT_DIR, 'reference.pdb'), SEQ, ref)

    # Model 01: small noise
    write_pdb(os.path.join(OUTPUT_DIR, 'model_01.pdb'), SEQ,
              perturb(ref, 1.0, 1001))

    # Model 02: medium noise
    write_pdb(os.path.join(OUTPUT_DIR, 'model_02.pdb'), SEQ,
              perturb(ref, 4.0, 2002))

    # Model 03: large noise (RMSD near Gumbel mean -> non-trivial P-value)
    write_pdb(os.path.join(OUTPUT_DIR, 'model_03.pdb'), SEQ,
              perturb(ref, 7.5, 3003))

    # Model 04: rotation + translation + small noise (tests superposition)
    m4 = rotate_z_translate(ref, 45.0, 15.0, -10.0, 8.0)
    m4 = perturb(m4, 1.0, 4004)
    write_pdb(os.path.join(OUTPUT_DIR, 'model_04.pdb'), SEQ, m4)

    # Model 05: modified residue names + non-standard atom names + missing atoms
    m5 = perturb(ref, 3.5, 5005)
    rname_ov = {4: "1MA", 14: "PSU"}  # A->1MA, U->PSU
    aname_ov = {}
    for ri in [3, 7, 11, 16]:
        aname_ov[(ri, "O2'")] = "O2*"
    skip = {
        7:  {"OP1", "OP2", "O4'", "C2'", "O2'"},
        11: {"OP1", "OP2", "O4'", "C2'", "O2'"},
    }
    write_pdb(os.path.join(OUTPUT_DIR, 'model_05.pdb'), SEQ, m5,
              rname_overrides=rname_ov, aname_overrides=aname_ov,
              skip_atoms=skip)

    print("Generated PDB files in", OUTPUT_DIR)


if __name__ == '__main__':
    main()
