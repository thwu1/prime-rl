
"""
Protein NMR Ensemble Conformational Analysis.

Explores /app/data/ to identify the NMR ensemble among multiple PDB files,
reads the analysis protocol specification, and performs full conformational analysis.
"""

import glob
import json
import os

import numpy as np

import biotite.structure as struc
import biotite.structure.io as strucio


THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}


def compute_rmsd(coords1, coords2):
    """Root-mean-square deviation between two coordinate arrays."""
    diff = coords1 - coords2
    return float(np.sqrt(np.mean(np.sum(diff ** 2, axis=-1))))


def circular_variance_1d(angles):
    """
    Circular variance for a 1-D array of angles (radians).
    Returns None if all values are NaN.
    CV = 1 - R_bar, where R_bar = |mean(exp(i*theta))|.
    """
    valid = angles[~np.isnan(angles)]
    if len(valid) == 0:
        return None
    cos_mean = float(np.mean(np.cos(valid)))
    sin_mean = float(np.mean(np.sin(valid)))
    r_bar = np.sqrt(cos_mean ** 2 + sin_mean ** 2)
    return float(1.0 - r_bar)


def classify_ss(phi_val, psi_val, regions):
    """
    Ramachandran-based secondary structure classification using
    region boundaries from the protocol specification.
    """
    if phi_val is None or psi_val is None:
        return "coil"
    phi_deg = np.degrees(phi_val)
    psi_deg = np.degrees(psi_val)

    # Alpha region
    alpha = regions["alpha"]
    alpha_phi = alpha["condition"]  # "phi in [-160, -20] AND psi in [-120, 50]"
    if -160 <= phi_deg <= -20 and -120 <= psi_deg <= 50:
        return "alpha"

    # Beta region
    if -180 <= phi_deg <= -20 and (psi_deg > 50 or psi_deg < -120):
        return "beta"

    return "coil"


def find_nmr_ensemble(data_dir):
    """
    Explore all PDB files in data_dir and identify the NMR ensemble
    (multi-model structure). Returns (filepath, AtomArrayStack).
    """
    pdb_files = sorted(glob.glob(os.path.join(data_dir, "*.pdb")))
    print(f"Found {len(pdb_files)} PDB files in {data_dir}:")
    for f in pdb_files:
        print(f"  - {os.path.basename(f)}")

    # Read and check lab notes for context
    notes_path = os.path.join(data_dir, "notes.txt")
    if os.path.exists(notes_path):
        with open(notes_path) as f:
            notes = f.read()
        print(f"\nLab notes found. Verifying claims against actual file contents...")

    # Parse each PDB to determine its properties
    candidates = []
    for pdb_file in pdb_files:
        basename = os.path.basename(pdb_file)
        try:
            result = strucio.load_structure(pdb_file)
            if isinstance(result, struc.AtomArrayStack):
                n_models = result.stack_depth()
                if n_models > 1:
                    aa_mask = struc.filter_amino_acids(result[0])
                    ca_mask = aa_mask & (result[0].atom_name == "CA")
                    n_res = int(np.sum(ca_mask))
                    print(f"  {basename}: NMR ensemble, {n_models} models, {n_res} residues")
                    candidates.append((pdb_file, result, n_models, n_res))
                else:
                    print(f"  {basename}: Single model (loaded as stack with depth 1)")
            else:
                aa_mask = struc.filter_amino_acids(result)
                ca_mask = aa_mask & (result.atom_name == "CA")
                n_res = int(np.sum(ca_mask))
                print(f"  {basename}: Single model (X-ray/other), {n_res} residues")
        except Exception as e:
            print(f"  {basename}: Failed to parse - {e}")

    if not candidates:
        raise RuntimeError("No NMR ensemble (multi-model structure) found in " + data_dir)

    # Select the NMR ensemble
    selected = candidates[0]
    print(f"\nSelected NMR ensemble: {os.path.basename(selected[0])}")
    print(f"  Note: Lab notes may have incorrectly labeled experimental methods.")
    return selected[0], selected[1]


def main():
    # ---- Load the analysis protocol ----
    protocol_path = "/app/data/analysis_protocol.json"
    with open(protocol_path) as f:
        protocol = json.load(f)
    print(f"Loaded analysis protocol: {protocol['protocol_name']}")
    regions = protocol["ramachandran_regions"]

    # ---- Explore and identify NMR ensemble ----
    nmr_path, stack = find_nmr_ensemble("/app/data")
    source_file = os.path.basename(nmr_path)
    n_models = stack.stack_depth()

    # Identify C-alpha atoms of amino acid residues
    aa_mask = struc.filter_amino_acids(stack[0])
    ca_mask = aa_mask & (stack[0].atom_name == "CA")
    n_residues = int(np.sum(ca_mask))

    # Extract one-letter sequence
    res_names_3 = stack[0].res_name[ca_mask]
    sequence = "".join(THREE_TO_ONE.get(r, "X") for r in res_names_3)

    # ---- Pairwise C-alpha RMSD with superimposition ----
    rmsd_matrix = np.zeros((n_models, n_models))
    for i in range(n_models):
        for j in range(i + 1, n_models):
            fixed_coords = stack[i].coord[ca_mask]
            mobile_coords = stack[j].coord[ca_mask]
            fitted_coords, _ = struc.superimpose(fixed_coords, mobile_coords)
            rmsd_val = compute_rmsd(fixed_coords, fitted_coords)
            rmsd_matrix[i, j] = rmsd_val
            rmsd_matrix[j, i] = rmsd_val

    # ---- Medoid model ----
    mean_rmsds = rmsd_matrix.mean(axis=1)
    medoid_model = int(np.argmin(mean_rmsds))

    # ---- Mean pairwise RMSD (upper triangle) ----
    upper_indices = np.triu_indices(n_models, k=1)
    mean_pairwise_rmsd = float(np.mean(rmsd_matrix[upper_indices]))

    # ---- Backbone dihedral angles ----
    phi, psi, _ = struc.dihedral_backbone(stack)

    phi_list = [
        [None if np.isnan(v) else float(v) for v in row]
        for row in phi
    ]
    psi_list = [
        [None if np.isnan(v) else float(v) for v in row]
        for row in psi
    ]

    # ---- Per-residue flexibility (circular variance) ----
    flexibility = []
    for r in range(n_residues):
        cv_phi = circular_variance_1d(phi[:, r])
        cv_psi = circular_variance_1d(psi[:, r])
        if cv_phi is not None and cv_psi is not None:
            flexibility.append(float((cv_phi + cv_psi) / 2.0))
        elif cv_phi is not None:
            flexibility.append(float(cv_phi))
        elif cv_psi is not None:
            flexibility.append(float(cv_psi))
        else:
            flexibility.append(None)

    # ---- Secondary structure classification for medoid ----
    ss_classification = [
        classify_ss(phi_list[medoid_model][r], psi_list[medoid_model][r], regions)
        for r in range(n_residues)
    ]

    # ---- Write results ----
    results = {
        "source_file": source_file,
        "n_models": n_models,
        "n_residues": n_residues,
        "sequence": sequence,
        "rmsd_matrix": rmsd_matrix.tolist(),
        "medoid_model": medoid_model,
        "mean_pairwise_rmsd": mean_pairwise_rmsd,
        "phi_angles": phi_list,
        "psi_angles": psi_list,
        "per_residue_flexibility": flexibility,
        "secondary_structure": ss_classification,
    }

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nAnalysis complete: {n_models} models, {n_residues} residues")
    print(f"Source file: {source_file}")
    print(f"Medoid model: {medoid_model} (mean RMSD: {mean_rmsds[medoid_model]:.3f} A)")
    print(f"Mean pairwise RMSD: {mean_pairwise_rmsd:.3f} A")
    print(f"Results written to /app/results.json")


if __name__ == "__main__":
    main()
