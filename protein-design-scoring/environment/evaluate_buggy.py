#!/usr/bin/env python3
"""Protein binder design evaluation pipeline.

Evaluates candidate binder designs against a reference structure using
structural quality metrics and outputs a composite-score ranking.
"""
import json
import os

import numpy as np


def parse_pdb_ca(filepath):
    """Extract Ca coordinates and B-factors from a PDB file, grouped by chain."""
    chains = {}
    with open(filepath) as fh:
        for line in fh:
            if not line.startswith("ATOM"):
                continue
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


def kabsch_align(model, reference):
    """Kabsch superposition of model onto reference (Nx3 arrays)."""
    p_mean = model.mean(axis=0)
    q_mean = reference.mean(axis=0)
    Pc = model - p_mean
    Qc = reference - q_mean
    H = Pc.T @ Qc
    U, _S, Vt = np.linalg.svd(H)
    d = np.linalg.det(Vt.T @ U.T)
    D = np.diag([1.0, 1.0, float(np.sign(d))])
    R = Vt.T @ D @ U.T
    aligned = (R @ Pc.T).T + q_mean
    return aligned, R, q_mean - R @ p_mean


def kabsch_rmsd(model, reference):
    """RMSD after optimal Kabsch superposition."""
    aligned, _, _ = kabsch_align(model, reference)
    return float(np.sqrt(np.mean(np.sum((reference - aligned) ** 2, axis=1))))


def compute_lddt(model, reference, inclusion_radius=15.0, thresholds=None):
    """Local Distance Difference Test (Ca-only).
    Evaluates distance preservation between model and reference structures.
    """
    if thresholds is None:
        thresholds = [0.5, 1.0, 2.0, 4.0]
    n = len(model)
    ref_d = np.linalg.norm(reference[:, None] - reference[None, :], axis=2)
    mod_d = np.linalg.norm(model[:, None] - model[None, :], axis=2)
    mask = (mod_d < inclusion_radius) & (~np.eye(n, dtype=bool))
    diff = np.abs(mod_d - ref_d)
    n_pairs = int(mask.sum())
    if n_pairs == 0:
        return 0.0
    total = n_pairs * len(thresholds)
    preserved = 0
    for t in thresholds:
        preserved += int((diff[mask] < t).sum())
    return preserved / total


def compute_tm_score(model, reference):
    """Template Modeling score after Kabsch alignment."""
    L = len(reference)
    d0 = 1.24 * L ** (1.0 / 3.0) - 1.8
    if d0 < 0.5:
        d0 = 0.5
    aligned, _, _ = kabsch_align(model, reference)
    dists = np.linalg.norm(aligned - reference, axis=1)
    return float(np.mean(1.0 / (1.0 + (dists / d0) ** 2)))


def compute_interface_contacts(target_coords, binder_coords, threshold):
    """Count binder residues having at least one target Ca within threshold."""
    dists = np.linalg.norm(
        target_coords[:, None] - binder_coords[None, :], axis=2
    )
    return int(np.sum(dists.min(axis=1) < threshold))


def compute_hotspot_coverage(target_coords, binder_coords, hotspots, threshold):
    """Fraction of hotspot target residues contacted by any binder residue."""
    if not hotspots:
        return 0.0
    contacted = 0
    for hr in hotspots:
        if hr >= len(target_coords):
            continue
        dists = np.linalg.norm(binder_coords - target_coords[hr], axis=1)
        if dists.min() < threshold:
            contacted += 1
    return contacted / len(hotspots)


def compute_interface_pae(pae_matrix, target_len, binder_len):
    """Mean PAE across inter-chain residue pairs."""
    pae = np.asarray(pae_matrix, dtype=np.float64)
    block_tb = pae[:target_len, target_len:target_len + binder_len]
    block_bt = pae[target_len:target_len + binder_len, :target_len]
    return float(np.mean(np.concatenate([block_tb.ravel(), block_bt.ravel()])))


def main():
    with open("/app/config.json") as fh:
        config = json.load(fh)

    ref = parse_pdb_ca(config["reference_structure"])
    ref_binder = ref[config["binder_chain"]]["coords"]

    design_metrics = {}
    for design_path in config["design_structures"]:
        name = os.path.splitext(os.path.basename(design_path))[0]
        design = parse_pdb_ca(design_path)
        d_binder = design[config["binder_chain"]]["coords"]
        d_target = design[config["target_chain"]]["coords"]
        d_bfactors = design[config["binder_chain"]]["bfactors"]

        pae_path = config["pae_files"][name]
        with open(pae_path) as fh:
            pae_data = json.load(fh)
        pae_matrix = pae_data[0]["predicted_aligned_error"]

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

    ranking = sorted(
        design_metrics.keys(),
        key=lambda k: design_metrics[k]["composite_score"],
        reverse=True,
    )

    output = {"designs": design_metrics, "ranking": ranking}
    with open(config.get("output_file", "/app/results.json"), "w") as fh:
        json.dump(output, fh, indent=2)

    print("Pipeline complete. Results written to /app/results.json")


if __name__ == "__main__":
    main()
