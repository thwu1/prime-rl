#!/usr/bin/env python3
"""DockQ protein-protein docking quality assessment tool.

Computes fnat, L-RMSD, I-RMSD, DockQ score, and CAPRI classification
for a docking model compared to a native complex structure.

Usage: dockq <native.pdb> <model.pdb> --rec-chain <R> --lig-chain <L>
"""

import sys
import argparse
import math


def parse_pdb(filename):
    """Parse a PDB file and return a list of atom dicts."""
    atoms = []
    with open(filename) as f:
        for line in f:
            if line.startswith("ATOM") or line.startswith("HETATM"):
                element = line[76:78].strip() if len(line) > 76 else line[12:14].strip()
                if element == "H":
                    continue
                atom = {
                    "x": float(line[30:38]),
                    "y": float(line[38:46]),
                    "z": float(line[46:54]),
                    "chain": line[21],
                    "resnum": int(line[22:26]),
                    "resname": line[17:20].strip(),
                    "atomname": line[12:16].strip(),
                    "line": line,
                }
                atoms.append(atom)
    return atoms


def split_chains(atoms, rec_chain, lig_chain):
    """Split atoms by chain."""
    rec = [a for a in atoms if a["chain"] == rec_chain]
    lig = [a for a in atoms if a["chain"] == lig_chain]
    return rec, lig


def get_backbone(atoms):
    """Filter to backbone atoms (N, CA, C, O)."""
    bb_names = {"N", "CA", "C", "O"}
    return [a for a in atoms if a["atomname"] in bb_names]


def dist2(a, b):
    """Squared distance between two atoms."""
    return (a["x"] - b["x"])**2 + (a["y"] - b["y"])**2 + (a["z"] - b["z"])**2


def get_contacts(rec, lig, cutoff=5.0):
    """Get residue-residue contacts within cutoff (heavy atoms)."""
    cutoff2 = cutoff * cutoff
    contacts = set()
    for r in rec:
        for l in lig:
            if dist2(r, l) < cutoff2:
                contacts.add((r["resnum"], l["resnum"]))
    return contacts


def compute_fnat(native_rec, native_lig, model_rec, model_lig):
    """Compute fraction of native contacts preserved in model."""
    native_contacts = get_contacts(native_rec, native_lig, 5.0)
    if len(native_contacts) == 0:
        return 0.0
    model_contacts = get_contacts(model_rec, model_lig, 5.0)
    preserved = native_contacts & model_contacts
    return len(preserved) / len(native_contacts)


def coords_array(atoms):
    """Extract coordinate array from atoms: list of [x, y, z]."""
    return [[a["x"], a["y"], a["z"]] for a in atoms]


def centroid(coords):
    """Compute centroid of coordinate list."""
    n = len(coords)
    cx = sum(c[0] for c in coords) / n
    cy = sum(c[1] for c in coords) / n
    cz = sum(c[2] for c in coords) / n
    return [cx, cy, cz]


def center_coords(coords):
    """Subtract centroid from coordinates."""
    c = centroid(coords)
    return [[p[0]-c[0], p[1]-c[1], p[2]-c[2]] for p in coords], c


def mat_mult_3x3(A, B):
    """Multiply two 3x3 matrices."""
    C = [[0.0]*3 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            for k in range(3):
                C[i][j] += A[i][k] * B[k][j]
    return C


def transpose_3x3(A):
    """Transpose a 3x3 matrix."""
    return [[A[j][i] for j in range(3)] for i in range(3)]


def det_3x3(A):
    """Determinant of 3x3 matrix."""
    return (A[0][0]*(A[1][1]*A[2][2] - A[1][2]*A[2][1])
          - A[0][1]*(A[1][0]*A[2][2] - A[1][2]*A[2][0])
          + A[0][2]*(A[1][0]*A[2][1] - A[1][1]*A[2][0]))


def svd_3x3(H):
    """Compute SVD of 3x3 matrix using eigendecomposition.

    Returns U, S, Vt such that H = U @ diag(S) @ Vt
    """
    # H^T H gives V and singular values squared
    HtH = mat_mult_3x3(transpose_3x3(H), H)

    # Find eigenvalues of HtH using characteristic polynomial
    eigenvalues, eigenvectors = symmetric_eigen_3x3(HtH)

    # Singular values
    S = [math.sqrt(max(ev, 0.0)) for ev in eigenvalues]

    # V = eigenvectors (columns of V are eigenvectors of H^T H)
    V = eigenvectors  # Each row is an eigenvector

    # U = H V S^-1
    Vt = V  # Already in row form
    V_cols = transpose_3x3(Vt)

    U = [[0.0]*3 for _ in range(3)]
    for k in range(3):
        if S[k] > 1e-10:
            # U column k = H * V_col_k / S[k]
            for i in range(3):
                val = 0.0
                for j in range(3):
                    val += H[i][j] * V_cols[j][k]
                U[i][k] = val / S[k]
        else:
            # Degenerate case
            U[0][k] = 1.0 if k == 0 else 0.0
            U[1][k] = 1.0 if k == 1 else 0.0
            U[2][k] = 1.0 if k == 2 else 0.0

    return U, S, Vt


def symmetric_eigen_3x3(A):
    """Eigenvalues and eigenvectors of a 3x3 symmetric matrix.

    Uses the analytical solution via the characteristic polynomial.
    Returns sorted eigenvalues (descending) and corresponding eigenvectors.
    """
    # Coefficients of characteristic polynomial det(A - lambda I) = 0
    # -lambda^3 + tr(A)*lambda^2 - (sum of 2x2 minors)*lambda + det(A) = 0
    p1 = A[0][1]**2 + A[0][2]**2 + A[1][2]**2

    if p1 < 1e-20:
        # A is diagonal
        eigs = [A[0][0], A[1][1], A[2][2]]
        vecs = [[1,0,0], [0,1,0], [0,0,1]]
        # Sort descending
        order = sorted(range(3), key=lambda i: -eigs[i])
        return [eigs[i] for i in order], [vecs[i] for i in order]

    q = (A[0][0] + A[1][1] + A[2][2]) / 3.0
    p2 = (A[0][0]-q)**2 + (A[1][1]-q)**2 + (A[2][2]-q)**2 + 2*p1
    p = math.sqrt(p2 / 6.0)

    B = [[0.0]*3 for _ in range(3)]
    for i in range(3):
        for j in range(3):
            B[i][j] = (A[i][j] - (q if i == j else 0)) / p

    detB = det_3x3(B)
    r = detB / 2.0
    r = max(-1.0, min(1.0, r))

    phi = math.acos(r) / 3.0

    eig1 = q + 2 * p * math.cos(phi)
    eig3 = q + 2 * p * math.cos(phi + 2*math.pi/3)
    eig2 = 3*q - eig1 - eig3

    eigenvalues = sorted([eig1, eig2, eig3], reverse=True)

    # Compute eigenvectors
    eigenvectors = []
    for ev in eigenvalues:
        v = find_eigenvector(A, ev)
        # Gram-Schmidt orthogonalization against previous vectors
        for prev in eigenvectors:
            dot = sum(v[i]*prev[i] for i in range(3))
            v = [v[i] - dot*prev[i] for i in range(3)]
        # Normalize
        norm = math.sqrt(sum(x*x for x in v))
        if norm > 1e-10:
            v = [x/norm for x in v]
        else:
            # Find an orthogonal vector
            v = find_orthogonal(eigenvectors)
        eigenvectors.append(v)

    return eigenvalues, eigenvectors


def find_eigenvector(A, eigenvalue):
    """Find eigenvector of 3x3 matrix for given eigenvalue."""
    # (A - lambda*I) v = 0
    M = [[A[i][j] - (eigenvalue if i == j else 0) for j in range(3)] for i in range(3)]

    # Try cross products of rows to find null space
    rows = [M[0], M[1], M[2]]
    best_v = None
    best_norm = 0

    for i in range(3):
        for j in range(i+1, 3):
            v = cross(rows[i], rows[j])
            norm = math.sqrt(sum(x*x for x in v))
            if norm > best_norm:
                best_norm = norm
                best_v = v

    if best_v and best_norm > 1e-10:
        return [x/best_norm for x in best_v]
    return [1.0, 0.0, 0.0]


def cross(a, b):
    """Cross product of two 3-vectors."""
    return [
        a[1]*b[2] - a[2]*b[1],
        a[2]*b[0] - a[0]*b[2],
        a[0]*b[1] - a[1]*b[0]
    ]


def find_orthogonal(vecs):
    """Find a unit vector orthogonal to all given vectors."""
    if len(vecs) == 0:
        return [1.0, 0.0, 0.0]
    if len(vecs) == 1:
        v = vecs[0]
        if abs(v[0]) < 0.9:
            candidate = [1.0, 0.0, 0.0]
        else:
            candidate = [0.0, 1.0, 0.0]
        c = cross(v, candidate)
        norm = math.sqrt(sum(x*x for x in c))
        return [x/norm for x in c] if norm > 1e-10 else [0.0, 0.0, 1.0]
    # Two vectors
    c = cross(vecs[0], vecs[1])
    norm = math.sqrt(sum(x*x for x in c))
    return [x/norm for x in c] if norm > 1e-10 else [0.0, 0.0, 1.0]


def kabsch(P, Q):
    """Compute optimal rotation matrix to superpose P onto Q.

    Both P and Q should be centered (centroid at origin).
    Returns rotation matrix R such that R @ P ≈ Q.
    """
    n = len(P)
    # H = P^T Q
    H = [[0.0]*3 for _ in range(3)]
    for k in range(n):
        for i in range(3):
            for j in range(3):
                H[i][j] += P[k][i] * Q[k][j]

    U, S, Vt = svd_3x3(H)

    # Check for reflection
    d = det_3x3(mat_mult_3x3(transpose_3x3(Vt), transpose_3x3(U)))

    sign_matrix = [[1,0,0],[0,1,0],[0,0,1.0]]
    if d < 0:
        sign_matrix[2][2] = -1.0

    R = mat_mult_3x3(transpose_3x3(Vt), mat_mult_3x3(sign_matrix, transpose_3x3(U)))

    return R


def apply_rotation(R, coords):
    """Apply rotation matrix R to coordinates."""
    result = []
    for p in coords:
        rp = [0.0, 0.0, 0.0]
        for i in range(3):
            for j in range(3):
                rp[i] += R[i][j] * p[j]
        result.append(rp)
    return result


def rmsd(coords1, coords2):
    """Compute RMSD between two coordinate sets."""
    n = len(coords1)
    if n == 0:
        return 0.0
    total = 0.0
    for i in range(n):
        for j in range(3):
            total += (coords1[i][j] - coords2[i][j])**2
    return math.sqrt(total / n)


def superpose_rmsd(P, Q):
    """Compute RMSD after optimal superposition of P onto Q."""
    if len(P) == 0:
        return 0.0
    P_centered, P_cent = center_coords(P)
    Q_centered, Q_cent = center_coords(Q)

    R = kabsch(P_centered, Q_centered)
    P_rotated = apply_rotation(R, P_centered)

    # Translate to Q centroid
    P_final = [[p[i] + Q_cent[i] for i in range(3)] for p in P_rotated]

    return rmsd(P_final, Q)


def match_backbone_atoms(atoms1, atoms2):
    """Match backbone atoms between two atom sets by (resnum, atomname).

    Returns paired coordinate lists.
    """
    bb_names = {"N", "CA", "C", "O"}

    # Build lookup for atoms2
    lookup = {}
    for a in atoms2:
        if a["atomname"] in bb_names:
            key = (a["resnum"], a["atomname"])
            lookup[key] = a

    coords1 = []
    coords2 = []
    for a in atoms1:
        if a["atomname"] in bb_names:
            key = (a["resnum"], a["atomname"])
            if key in lookup:
                b = lookup[key]
                coords1.append([a["x"], a["y"], a["z"]])
                coords2.append([b["x"], b["y"], b["z"]])

    return coords1, coords2


def compute_lrms(native_rec, native_lig, model_rec, model_lig):
    """Compute L-RMSD: ligand backbone RMSD after receptor superposition."""
    # Match and get backbone coords for receptor
    rec_native_coords, rec_model_coords = match_backbone_atoms(native_rec, model_rec)

    if len(rec_native_coords) == 0:
        return float('inf')

    # Center both on receptor centroid
    rec_native_c, nat_cent = center_coords(rec_native_coords)
    rec_model_c, mod_cent = center_coords(rec_model_coords)

    # Get optimal rotation to superpose model receptor onto native receptor
    R = kabsch(rec_model_c, rec_native_c)

    # Get ligand backbone coords
    lig_native_coords, lig_model_coords = match_backbone_atoms(native_lig, model_lig)

    if len(lig_native_coords) == 0:
        return float('inf')

    # Apply the SAME transformation (rotation + translation) to model ligand
    # Transform: center on model receptor centroid, rotate, translate to native receptor centroid
    lig_model_transformed = []
    for p in lig_model_coords:
        # Center relative to model receptor centroid
        pc = [p[i] - mod_cent[i] for i in range(3)]
        # Rotate
        rp = [0.0, 0.0, 0.0]
        for i in range(3):
            for j in range(3):
                rp[i] += R[i][j] * pc[j]
        # Translate to native receptor centroid
        rp = [rp[i] + nat_cent[i] for i in range(3)]
        lig_model_transformed.append(rp)

    return rmsd(lig_model_transformed, lig_native_coords)


def compute_irms(native_rec, native_lig, model_rec, model_lig):
    """Compute I-RMSD: interface backbone RMSD after interface superposition."""
    # Get interface residues using 10A cutoff on native
    iface_rec_res = set()
    iface_lig_res = set()
    for r in native_rec:
        for l in native_lig:
            if dist2(r, l) < 100.0:  # 10A
                iface_rec_res.add(r["resnum"])
                iface_lig_res.add(l["resnum"])

    if not iface_rec_res or not iface_lig_res:
        return float('inf')

    # Get interface backbone atoms
    bb_names = {"N", "CA", "C", "O"}

    native_iface_atoms = (
        [a for a in native_rec if a["resnum"] in iface_rec_res and a["atomname"] in bb_names] +
        [a for a in native_lig if a["resnum"] in iface_lig_res and a["atomname"] in bb_names]
    )

    model_iface_atoms = (
        [a for a in model_rec if a["resnum"] in iface_rec_res and a["atomname"] in bb_names] +
        [a for a in model_lig if a["resnum"] in iface_lig_res and a["atomname"] in bb_names]
    )

    # Match by (chain, resnum, atomname)
    native_lookup = {}
    for a in native_iface_atoms:
        key = (a["chain"], a["resnum"], a["atomname"])
        native_lookup[key] = a

    native_coords = []
    model_coords = []
    for a in model_iface_atoms:
        key = (a["chain"], a["resnum"], a["atomname"])
        if key in native_lookup:
            b = native_lookup[key]
            native_coords.append([b["x"], b["y"], b["z"]])
            model_coords.append([a["x"], a["y"], a["z"]])

    if len(native_coords) == 0:
        return float('inf')

    return superpose_rmsd(model_coords, native_coords)


def compute_dockq(fnat, lrms, irms):
    """Compute DockQ score from fnat, L-RMSD, and I-RMSD."""
    d1, d2 = 8.5, 1.5
    return (fnat + 1.0/(1.0 + (lrms/d1)**2) + 1.0/(1.0 + (irms/d2)**2)) / 3.0


def classify_capri(fnat, lrms, irms):
    """Classify docking model quality using CAPRI criteria."""
    if fnat >= 0.5 and (lrms <= 1.0 or irms <= 1.0):
        return "High"
    if (fnat >= 0.3 and fnat < 0.5) and (lrms <= 5.0 or irms <= 2.0):
        return "Medium"
    if fnat >= 0.5 and lrms > 1.0 and irms > 1.0:
        return "Medium"
    if (fnat >= 0.1 and fnat < 0.3) and (lrms <= 10.0 or irms <= 4.0):
        return "Acceptable"
    if fnat >= 0.3 and lrms > 5.0 and irms > 2.0:
        return "Acceptable"
    return "Incorrect"


def main():
    parser = argparse.ArgumentParser(description="DockQ protein-protein docking quality assessment")
    parser.add_argument("native", help="Native complex PDB file")
    parser.add_argument("model", help="Model complex PDB file")
    parser.add_argument("--rec-chain", required=True, help="Receptor chain ID")
    parser.add_argument("--lig-chain", required=True, help="Ligand chain ID")
    args = parser.parse_args()

    native_atoms = parse_pdb(args.native)
    model_atoms = parse_pdb(args.model)

    native_rec, native_lig = split_chains(native_atoms, args.rec_chain, args.lig_chain)
    model_rec, model_lig = split_chains(model_atoms, args.rec_chain, args.lig_chain)

    fnat = compute_fnat(native_rec, native_lig, model_rec, model_lig)
    lrms = compute_lrms(native_rec, native_lig, model_rec, model_lig)
    irms = compute_irms(native_rec, native_lig, model_rec, model_lig)
    dockq = compute_dockq(fnat, lrms, irms)
    capri = classify_capri(fnat, lrms, irms)

    print(f"fnat {fnat:.6f}")
    print(f"lrms {lrms:.6f}")
    print(f"irms {irms:.6f}")
    print(f"dockq {dockq:.6f}")
    print(f"capri {capri}")


if __name__ == "__main__":
    main()
