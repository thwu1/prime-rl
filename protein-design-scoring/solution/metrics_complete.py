#!/usr/bin/env python3
"""Complete protein binder design structural metrics implementation.

"""
import csv
import json
import os
import sys

import numpy as np


def parse_pdb_ca(filepath):
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


def _kabsch_align(model, reference):
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
    return aligned


def kabsch_rmsd(model, reference):
    aligned = _kabsch_align(model, reference)
    return float(np.sqrt(np.mean(np.sum((reference - aligned) ** 2, axis=1))))


def compute_lddt(model, reference, inclusion_radius=15.0, thresholds=None):
    if thresholds is None:
        thresholds = [0.5, 1.0, 2.0, 4.0]
    n = len(model)
    ref_d = np.linalg.norm(reference[:, None] - reference[None, :], axis=2)
    mod_d = np.linalg.norm(model[:, None] - model[None, :], axis=2)
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


def compute_tm_score(model, reference):
    L = len(reference)
    d0 = 1.24 * max(L - 15, 1) ** (1.0 / 3.0) - 1.8
    if d0 < 0.5:
        d0 = 0.5
    aligned = _kabsch_align(model, reference)
    dists = np.linalg.norm(aligned - reference, axis=1)
    return float(np.mean(1.0 / (1.0 + (dists / d0) ** 2)))


def compute_gdt_ts(model, reference):
    aligned = _kabsch_align(model, reference)
    dists = np.linalg.norm(aligned - reference, axis=1)
    thresholds = [1.0, 2.0, 4.0, 8.0]
    fractions = [float(np.mean(dists < t)) for t in thresholds]
    return sum(fractions) / len(thresholds)


def compute_interface_contacts(target_coords, binder_coords, threshold):
    dists = np.linalg.norm(
        target_coords[:, None] - binder_coords[None, :], axis=2
    )
    return int(np.sum(dists.min(axis=0) < threshold))


def compute_hotspot_coverage(target_coords, binder_coords, hotspots, threshold):
    if not hotspots:
        return 0.0
    contacted = 0
    for hr in hotspots:
        idx = hr - 1
        if idx >= len(target_coords):
            continue
        dists = np.linalg.norm(binder_coords - target_coords[idx], axis=1)
        if dists.min() < threshold:
            contacted += 1
    return contacted / len(hotspots)


def compute_interface_pae(pae_matrix, target_len, binder_len):
    pae = np.asarray(pae_matrix, dtype=np.float64)
    block_tb = pae[:target_len, target_len:target_len + binder_len]
    block_bt = pae[target_len:target_len + binder_len, :target_len]
    return float(np.mean(np.concatenate([block_tb.ravel(), block_bt.ravel()])))


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 metrics.py <config.json>")
        sys.exit(1)

    config_path = sys.argv[1]
    with open(config_path) as fh:
        config = json.load(fh)

    ref = parse_pdb_ca(config["reference_structure"])
    ref_binder = ref[config["binder_chain"]]["coords"]

    output_csv = config.get("metrics_csv", "/app/metrics.csv")
    with open(output_csv, "w", newline="") as csvf:
        writer = csv.writer(csvf)
        writer.writerow([
            "design", "rmsd", "lddt", "tm_score", "gdt_ts",
            "interface_contacts", "hotspot_coverage", "interface_pae",
            "mean_plddt"
        ])

        for design_path in config["design_structures"]:
            name = os.path.splitext(os.path.basename(design_path))[0]
            design = parse_pdb_ca(design_path)
            d_binder = design[config["binder_chain"]]["coords"]
            d_target = design[config["target_chain"]]["coords"]
            d_bfactors = design[config["binder_chain"]]["bfactors"]

            pae_norm_path = os.path.join(
                config["pae_normalized_dir"],
                name + ".json"
            )
            with open(pae_norm_path) as fh:
                pae_matrix = json.load(fh)

            rmsd_val = kabsch_rmsd(d_binder, ref_binder)
            lddt_val = compute_lddt(
                d_binder, ref_binder,
                config["lddt_inclusion_radius"],
                config["lddt_thresholds"],
            )
            tm_val = compute_tm_score(d_binder, ref_binder)
            gdt_val = compute_gdt_ts(d_binder, ref_binder)
            contacts_val = compute_interface_contacts(
                d_target, d_binder, config["contact_threshold_ca"]
            )
            hotspot_val = compute_hotspot_coverage(
                d_target, d_binder,
                config["hotspot_residues"],
                config["contact_threshold_ca"],
            )
            ipae_val = compute_interface_pae(
                pae_matrix, config["target_length"], config["binder_length"]
            )
            mean_plddt_val = float(np.mean(d_bfactors))

            writer.writerow([
                name,
                f"{rmsd_val:.6f}",
                f"{lddt_val:.6f}",
                f"{tm_val:.6f}",
                f"{gdt_val:.6f}",
                contacts_val,
                f"{hotspot_val:.6f}",
                f"{ipae_val:.6f}",
                f"{mean_plddt_val:.6f}",
            ])

    print(f"Metrics written to {output_csv}")


if __name__ == "__main__":
    main()
