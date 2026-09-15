#!/usr/bin/env python3
"""Protein design scoring pipeline — reference solution.


Reads PDB structures, PAE matrices and a config file, computes structural
bioinformatics metrics (Kabsch RMSD, lDDT, TM-score, interface analysis),
and writes a ranked results JSON.
"""
import json
import os
import sys

import numpy as np


# -----------------------------------------------------------------------
# PDB parsing
# -----------------------------------------------------------------------

def parse_pdb_ca(filepath):
    """Extract Ca coordinates and B-factors from a PDB file, grouped by chain.

    Returns dict: chain_id -> {"coords": ndarray(N,3), "bfactors": ndarray(N,)}
    """
    chains = {}
    with open(filepath) as fh:
        for line in fh:
            if not line.startswith("ATOM"):
                continue
            # PDB columns 13-16 hold the atom name (1-indexed)
            atom_name = line[12:16].strip()
            if atom_name != "CA":
                continue
            chain = line[21]
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])
            bfac = float(line[60:66])
            chains.setdefault(chain, {"coords": [], "bfactors": []})
            chains[chain]["coords"].append([x, y, z])
            chains[chain]["bfactors"].append(bfac)
    for c in chains:
        chains[c]["coords"] = np.array(chains[c]["coords"], dtype=np.float64)
        chains[c]["bfactors"] = np.array(chains[c]["bfactors"], dtype=np.float64)
    return chains


# -----------------------------------------------------------------------
# Kabsch alignment and RMSD
# -----------------------------------------------------------------------

def kabsch_align(model, reference):
    """Kabsch superposition of *model* onto *reference* (both Nx3).

    Returns (aligned_model, R, t) where aligned = R @ model_centred + ref_mean.
    """
    p_mean = model.mean(axis=0)
    q_mean = reference.mean(axis=0)
    Pc = model - p_mean
    Qc = reference - q_mean

    H = Pc.T @ Qc                       # 3x3 cross-covariance
    U, _S, Vt = np.linalg.svd(H)

    # Correct for reflection (ensure proper rotation)
    d = np.linalg.det(Vt.T @ U.T)
    D = np.diag([1.0, 1.0, float(np.sign(d))])
    R = Vt.T @ D @ U.T

    aligned = (R @ Pc.T).T + q_mean
    return aligned, R, q_mean - R @ p_mean


def kabsch_rmsd(model, reference):
    """RMSD after optimal Kabsch superposition."""
    aligned, _, _ = kabsch_align(model, reference)
    return float(np.sqrt(np.mean(np.sum((reference - aligned) ** 2, axis=1))))


# -----------------------------------------------------------------------
# lDDT (Local Distance Difference Test)
# -----------------------------------------------------------------------

def compute_lddt(model, reference, inclusion_radius=15.0, thresholds=None):
    """Compute lDDT (Ca-only) between model and reference coordinates.

    For every residue pair whose reference distance is < inclusion_radius,
    check whether |d_model - d_ref| < t for each threshold t.
    Return global fraction of preserved distances.
    """
    if thresholds is None:
        thresholds = [0.5, 1.0, 2.0, 4.0]
    n = len(model)

    # All-pairs distance matrices
    ref_d = np.linalg.norm(reference[:, None] - reference[None, :], axis=2)
    mod_d = np.linalg.norm(model[:, None] - model[None, :], axis=2)

    # Mask: within inclusion radius, exclude self-pairs
    mask = (ref_d < inclusion_radius) & (~np.eye(n, dtype=bool))
    diff = np.abs(mod_d - ref_d)

    n_pairs = int(mask.sum())
    if n_pairs == 0:
        return 0.0

    total = n_pairs * len(thresholds)
    preserved = 0
    for t in thresholds:
        preserved += int((diff[mask] < t).sum())

    return preserved / total


# -----------------------------------------------------------------------
# TM-score
# -----------------------------------------------------------------------

def compute_tm_score(model, reference):
    """TM-score after Kabsch alignment of model onto reference.

    d0 = 1.24 * (L - 15)^(1/3) - 1.8, clamped to >= 0.5.
    """
    L = len(reference)
    d0 = 1.24 * max(L - 15, 1) ** (1.0 / 3.0) - 1.8
    if d0 < 0.5:
        d0 = 0.5

    aligned, _, _ = kabsch_align(model, reference)
    dists = np.linalg.norm(aligned - reference, axis=1)
    return float(np.mean(1.0 / (1.0 + (dists / d0) ** 2)))


# -----------------------------------------------------------------------
# Interface analysis
# -----------------------------------------------------------------------

def compute_interface_contacts(target_coords, binder_coords, threshold):
    """Count binder residues having at least one target Ca within threshold."""
    # dists shape: (n_target, n_binder)
    dists = np.linalg.norm(
        target_coords[:, None] - binder_coords[None, :], axis=2
    )
    # For each binder residue, check minimum distance to any target residue
    return int(np.sum(dists.min(axis=0) < threshold))


def compute_hotspot_coverage(target_coords, binder_coords, hotspots, threshold):
    """Fraction of hotspot target residues contacted by any binder residue."""
    if not hotspots:
        return 0.0
    contacted = 0
    for hr in hotspots:
        idx = hr - 1  # 1-indexed → 0-indexed
        if idx >= len(target_coords):
            continue
        dists = np.linalg.norm(binder_coords - target_coords[idx], axis=1)
        if dists.min() < threshold:
            contacted += 1
    return contacted / len(hotspots)


# -----------------------------------------------------------------------
# PAE analysis
# -----------------------------------------------------------------------

def compute_interface_pae(pae_matrix, target_len, binder_len):
    """Mean PAE across inter-chain blocks (target→binder and binder→target)."""
    pae = np.asarray(pae_matrix, dtype=np.float64)
    block_tb = pae[:target_len, target_len:target_len + binder_len]
    block_bt = pae[target_len:target_len + binder_len, :target_len]
    return float(np.mean(np.concatenate([block_tb.ravel(), block_bt.ravel()])))


# -----------------------------------------------------------------------
# Main pipeline
# -----------------------------------------------------------------------

def main():
    # Load config
    with open("/app/config.json") as fh:
        config = json.load(fh)

    # Parse reference structure
    ref = parse_pdb_ca(config["reference_structure"])
    ref_binder = ref[config["binder_chain"]]["coords"]

    # Evaluate each design
    design_metrics = {}
    for design_path in config["design_structures"]:
        name = os.path.splitext(os.path.basename(design_path))[0]

        design = parse_pdb_ca(design_path)
        d_binder = design[config["binder_chain"]]["coords"]
        d_target = design[config["target_chain"]]["coords"]
        d_bfactors = design[config["binder_chain"]]["bfactors"]

        # PAE
        pae_path = config["pae_files"][name]
        with open(pae_path) as fh:
            pae_data = json.load(fh)
        pae_matrix = pae_data[0]["predicted_aligned_error"]

        # Compute metrics
        rmsd = kabsch_rmsd(d_binder, ref_binder)
        lddt = compute_lddt(
            d_binder, ref_binder,
            config["lddt_inclusion_radius"],
            config["lddt_thresholds"],
        )
        tm = compute_tm_score(d_binder, ref_binder)
        contacts = compute_interface_contacts(
            d_target, d_binder, config["contact_threshold_ca"]
        )
        hotspot = compute_hotspot_coverage(
            d_target, d_binder,
            config["hotspot_residues"],
            config["contact_threshold_ca"],
        )
        ipae = compute_interface_pae(
            pae_matrix, config["target_length"], config["binder_length"]
        )
        mean_plddt = float(np.mean(d_bfactors))

        # Composite score
        w = config["scoring_weights"]
        composite = (
            w["rmsd"] * rmsd
            + w["lddt"] * lddt
            + w["tm_score"] * tm
            + w["hotspot_coverage"] * hotspot
            + w["mean_plddt_normalized"] * (mean_plddt / 100.0)
            + w["interface_pae_normalized"] * (ipae / 31.75)
            + w["contact_density"] * (contacts / config["binder_length"])
        )

        design_metrics[name] = {
            "rmsd": round(rmsd, 6),
            "lddt": round(lddt, 6),
            "tm_score": round(tm, 6),
            "interface_contacts": contacts,
            "hotspot_coverage": round(hotspot, 6),
            "interface_pae": round(ipae, 6),
            "mean_plddt": round(mean_plddt, 6),
            "composite_score": round(composite, 6),
        }

    # Rank by composite score (descending)
    ranking = sorted(
        design_metrics.keys(),
        key=lambda k: design_metrics[k]["composite_score"],
        reverse=True,
    )

    output = {"designs": design_metrics, "ranking": ranking}
    with open("/app/results.json", "w") as fh:
        json.dump(output, fh, indent=2)

    print("Pipeline complete. Results written to /app/results.json")
    for i, name in enumerate(ranking, 1):
        m = design_metrics[name]
        print(f"  {i}. {name}: composite={m['composite_score']:.4f}  "
              f"rmsd={m['rmsd']:.2f}  lddt={m['lddt']:.3f}  "
              f"tm={m['tm_score']:.3f}  contacts={m['interface_contacts']}")


if __name__ == "__main__":
    main()
