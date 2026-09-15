#!/usr/bin/env python3
"""RNA 3D structure quality assessment pipeline — complete implementation.

Creates the full assessment pipeline from the mathematical specification:
- PDB parsing with modified nucleotide and legacy atom name normalization
- Kabsch SVD optimal superposition for RMSD computation
- Gumbel extreme-value P-value
- Per-residue RMSD from superposed coordinates
- Pairwise all-vs-all RMSD matrix
- Quality evaluation report with model classification
"""

import json
import math
import os
import numpy as np

# Modified nucleotide mappings — discovered by inspecting PDB data files
# and cross-referencing with RNA modification databases
MODIFIED_RESIDUE_MAP = {
    "1MA": "A", "MIA": "A", "6MA": "A", "A2M": "A", "MA6": "A",
    "PSU": "U", "5MU": "U", "H2U": "U", "4SU": "U", "UR3": "U",
    "OMC": "C", "5MC": "C", "CBR": "C",
    "OMG": "G", "2MG": "G", "7MG": "G", "M2G": "G", "1MG": "G", "YG": "G",
}

# Legacy asterisk notation -> IUPAC prime notation
ATOM_NAME_NORM = {
    "O2*": "O2'", "O3*": "O3'", "O4*": "O4'", "O5*": "O5'",
    "C1*": "C1'", "C2*": "C2'", "C3*": "C3'", "C4*": "C4'", "C5*": "C5'",
}

STANDARD_BASES = {"A", "G", "C", "U"}


def parse_pdb(filepath):
    """Parse PDB ATOM records with RNA-specific normalization.

    Returns (coords_dict, sequence_dict) where:
    - coords_dict: {(resnum, norm_atom_name): np.array([x,y,z])}
    - sequence_dict: {resnum: standard_base}
    """
    coords = {}
    sequence = {}
    with open(filepath) as f:
        for line in f:
            if not line.startswith("ATOM"):
                continue
            if len(line) < 54:
                continue
            atom_name = line[12:16].strip()
            resname = line[17:20].strip()
            resnum = int(line[22:26])
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])

            norm_atom = ATOM_NAME_NORM.get(atom_name, atom_name)
            norm_res = MODIFIED_RESIDUE_MAP.get(resname, resname)
            if norm_res not in STANDARD_BASES:
                continue

            sequence[resnum] = norm_res
            coords[(resnum, norm_atom)] = np.array([x, y, z])

    return coords, sequence


def kabsch_superpose(P, Q):
    """Kabsch SVD optimal superposition with reflection correction.

    Minimizes RMSD over all rotations and translations.
    P = model coords (Nx3), Q = reference coords (Nx3).
    Returns (rmsd, R, model_centroid, ref_centroid).
    """
    pc = P.mean(axis=0)
    qc = Q.mean(axis=0)
    Pc = P - pc
    Qc = Q - qc

    H = Pc.T @ Qc
    U, S, Vt = np.linalg.svd(H)

    d = np.linalg.det(Vt.T @ U.T)
    D = np.diag([1.0, 1.0, 1.0 if d > 0 else -1.0])
    R = Vt.T @ D @ U.T

    Pc_rot = (R @ Pc.T).T
    diff = Qc - Pc_rot
    rmsd = float(np.sqrt(np.mean(np.sum(diff ** 2, axis=1))))
    return rmsd, R, pc, qc


def compute_p_value(rmsd, L):
    """Gumbel extreme-value distribution P-value."""
    mu = 3.38 * (L ** 0.44)
    beta = 0.49 * (L ** 0.24)
    z = (rmsd - mu) / beta
    try:
        inner = math.exp(-z)
        return math.exp(-inner)
    except OverflowError:
        return 0.0


def compute_per_residue_rmsd(model_coords, ref_coords, matched_keys,
                              R, pc, qc, ref_resnums):
    """Per-residue RMSD using superposed coordinates."""
    by_res = {}
    for key in matched_keys:
        by_res.setdefault(key[0], []).append(key)

    result = []
    for rn in ref_resnums:
        if rn not in by_res:
            result.append(0.0)
            continue
        sq = []
        for key in by_res[rn]:
            p_rot = R @ (model_coords[key] - pc)
            q_cen = ref_coords[key] - qc
            d = q_cen - p_rot
            sq.append(float(np.dot(d, d)))
        result.append(math.sqrt(sum(sq) / len(sq)))
    return result


def pairwise_rmsd_val(coords_a, coords_b):
    """Compute Kabsch RMSD between two coordinate dicts."""
    matched = sorted(k for k in coords_a if k in coords_b)
    if len(matched) < 3:
        return 0.0
    P = np.array([coords_a[k] for k in matched])
    Q = np.array([coords_b[k] for k in matched])
    rmsd, _, _, _ = kabsch_superpose(P, Q)
    return rmsd


def main():
    data_dir = '/app/data'

    # Parse reference structure
    ref_coords, ref_seq = parse_pdb(os.path.join(data_dir, 'reference.pdb'))
    ref_resnums = sorted(ref_seq.keys())
    L = len(ref_resnums)

    # Parse all structures
    all_structures = {'reference': ref_coords}
    model_files = sorted(f for f in os.listdir(data_dir)
                         if f.startswith('model_') and f.endswith('.pdb'))

    for mf in model_files:
        name = mf.replace('.pdb', '')
        coords, _ = parse_pdb(os.path.join(data_dir, mf))
        all_structures[name] = coords

    # === results.json: per-model assessment vs reference ===
    assessments = []
    for mf in model_files:
        name = mf.replace('.pdb', '')
        model_coords = all_structures[name]
        matched = sorted(k for k in ref_coords if k in model_coords)
        n = len(matched)
        if n < 3:
            continue

        P = np.array([model_coords[k] for k in matched])
        Q = np.array([ref_coords[k] for k in matched])
        rmsd, R, pc, qc = kabsch_superpose(P, Q)
        pval = compute_p_value(rmsd, L)
        pr = compute_per_residue_rmsd(
            model_coords, ref_coords, matched, R, pc, qc, ref_resnums)

        assessments.append({
            "model": name,
            "rmsd": float(rmsd),
            "p_value": float(pval),
            "num_matched_atoms": n,
            "per_residue_rmsd": [float(v) for v in pr],
        })

    assessments.sort(key=lambda x: x['model'])
    ranking = [a['model'] for a in sorted(assessments, key=lambda x: x['rmsd'])]

    with open('/app/results.json', 'w') as f:
        json.dump({"assessments": assessments, "ranking": ranking}, f, indent=2)

    # === pairwise_rmsd.json: all-vs-all distance matrix ===
    all_names = sorted(all_structures.keys())
    n_struct = len(all_names)
    matrix = [[0.0] * n_struct for _ in range(n_struct)]

    for i in range(n_struct):
        for j in range(i + 1, n_struct):
            rmsd = pairwise_rmsd_val(all_structures[all_names[i]],
                                     all_structures[all_names[j]])
            matrix[i][j] = float(rmsd)
            matrix[j][i] = float(rmsd)

    with open('/app/pairwise_rmsd.json', 'w') as f:
        json.dump({"structures": all_names, "matrix": matrix}, f, indent=2)

    # === quality_report.json: evaluation and classification ===
    best_model = ranking[0]
    worst_model = ranking[-1]

    max_atoms = max(a['num_matched_atoms'] for a in assessments)
    full_cov = sorted([a['model'] for a in assessments
                       if a['num_matched_atoms'] == max_atoms])
    partial_cov = sorted([a['model'] for a in assessments
                          if a['num_matched_atoms'] < max_atoms])

    # Structurally similar model pairs: pairwise RMSD < 5.0 Angstroms
    model_names = sorted([n for n in all_names if n != 'reference'])
    similar_pairs = []
    for ii in range(len(model_names)):
        for jj in range(ii + 1, len(model_names)):
            ni, nj = model_names[ii], model_names[jj]
            idx_i = all_names.index(ni)
            idx_j = all_names.index(nj)
            if matrix[idx_i][idx_j] < 5.0:
                similar_pairs.append([ni, nj])

    quality_report = {
        "best_model": best_model,
        "worst_model": worst_model,
        "structurally_similar_pairs": similar_pairs,
        "coverage_analysis": {
            "full_coverage_models": full_cov,
            "partial_coverage_models": partial_cov,
        }
    }

    with open('/app/quality_report.json', 'w') as f:
        json.dump(quality_report, f, indent=2)

    print("Assessment complete.")
    print(f"Output: /app/results.json, /app/pairwise_rmsd.json, /app/quality_report.json")
    for a in assessments:
        print(f"  {a['model']}: RMSD={a['rmsd']:.3f} P={a['p_value']:.4e} "
              f"atoms={a['num_matched_atoms']}")


if __name__ == '__main__':
    main()
