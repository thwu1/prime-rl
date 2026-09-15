#!/usr/bin/env python3
"""Generate synthetic protein design evaluation data and expected results.


Creates PDB structures (Ca-only), AlphaFold2-format PAE matrices in two
different JSON schemas, configuration, and pre-computed correct metric values.
"""
import json
import math
import os
import random

import numpy as np


def write_pdb(filename, chains):
    """Write a PDB file containing only Ca atoms."""
    with open(filename, "w") as fh:
        atom_num = 1
        for chain_id in sorted(chains.keys()):
            residues = chains[chain_id]
            for res_idx, (x, y, z, bfac) in enumerate(residues, 1):
                fh.write(
                    "ATOM  %5d  CA  ALA %s%4d    %8.3f%8.3f%8.3f  1.00%6.2f           C  \n"
                    % (atom_num, chain_id, res_idx, x, y, z, bfac)
                )
                atom_num += 1
            fh.write(
                "TER   %5d      ALA %s%4d\n"
                % (atom_num, chain_id, len(residues))
            )
            atom_num += 1
        fh.write("END\n")


def helix_coords(n, offset_x=0.0, offset_y=0.0, offset_z=0.0, phase=0.0):
    """Alpha-helix Ca coordinates (rise 1.5 A, radius 2.3 A, 100 deg/res)."""
    coords = []
    for i in range(n):
        angle = math.radians(100.0 * i + phase)
        x = 2.3 * math.cos(angle) + offset_x
        y = 2.3 * math.sin(angle) + offset_y
        z = 1.5 * i + offset_z
        coords.append((x, y, z))
    return coords


def perturb(coords, sigma, seed, outlier_indices=None, outlier_sigma=None):
    """Add Gaussian noise; optionally larger noise at specified indices."""
    rng = random.Random(seed)
    result = []
    for i, (x, y, z) in enumerate(coords):
        s = outlier_sigma if (outlier_indices and i in outlier_indices) else sigma
        result.append((
            x + rng.gauss(0, s),
            y + rng.gauss(0, s),
            z + rng.gauss(0, s),
        ))
    return result


def rotate_z(coords, angle_deg):
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    return [(x * ca - y * sa, x * sa + y * ca, z) for x, y, z in coords]


def shift(coords, dx, dy, dz):
    return [(x + dx, y + dy, z + dz) for x, y, z in coords]


# ---- Reference implementations for computing validation values ----

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


def ref_kabsch_align(model, reference):
    p_c = model - model.mean(axis=0)
    q_c = reference - reference.mean(axis=0)
    H = p_c.T @ q_c
    U, _, Vt = np.linalg.svd(H)
    d = np.linalg.det(Vt.T @ U.T)
    D = np.diag([1.0, 1.0, float(np.sign(d))])
    R = Vt.T @ D @ U.T
    aligned = (R @ p_c.T).T + reference.mean(axis=0)
    return aligned


def ref_kabsch_rmsd(model, reference):
    aligned = ref_kabsch_align(model, reference)
    return float(np.sqrt(np.mean(np.sum((reference - aligned) ** 2, axis=1))))


def ref_lddt(model, reference, inclusion_radius, thresholds):
    n = len(model)
    ref_d = np.linalg.norm(reference[:, None] - reference[None, :], axis=2)
    mod_d = np.linalg.norm(model[:, None] - model[None, :], axis=2)
    mask = (ref_d < inclusion_radius) & (~np.eye(n, dtype=bool))
    diff = np.abs(mod_d - ref_d)
    total = int(mask.sum()) * len(thresholds)
    if total == 0:
        return 0.0
    preserved = sum(int((diff[mask] < t).sum()) for t in thresholds)
    return preserved / total


def ref_tm_score(model, reference):
    L = len(reference)
    d0 = 1.24 * max(L - 15, 1) ** (1.0 / 3.0) - 1.8
    if d0 < 0.5:
        d0 = 0.5
    aligned = ref_kabsch_align(model, reference)
    dists = np.linalg.norm(aligned - reference, axis=1)
    return float(np.mean(1.0 / (1.0 + (dists / d0) ** 2)))


def ref_gdt_ts(model, reference):
    aligned = ref_kabsch_align(model, reference)
    dists = np.linalg.norm(aligned - reference, axis=1)
    thresholds = [1.0, 2.0, 4.0, 8.0]
    fractions = [float(np.mean(dists < t)) for t in thresholds]
    return sum(fractions) / len(thresholds)


def ref_interface_contacts(target_coords, binder_coords, threshold):
    dists = np.linalg.norm(
        target_coords[:, None] - binder_coords[None, :], axis=2
    )
    return int(np.sum(dists.min(axis=0) < threshold))


def ref_hotspot_coverage(target_coords, binder_coords, hotspots, threshold):
    if not hotspots:
        return 0.0
    contacted = 0
    for hr in hotspots:
        idx = hr - 1
        if idx >= len(target_coords):
            continue
        d = np.linalg.norm(binder_coords - target_coords[idx], axis=1)
        if d.min() < threshold:
            contacted += 1
    return contacted / len(hotspots)


def ref_interface_pae(pae_matrix, tgt_len, bnd_len):
    pae = np.asarray(pae_matrix, dtype=np.float64)
    block1 = pae[:tgt_len, tgt_len:tgt_len + bnd_len]
    block2 = pae[tgt_len:tgt_len + bnd_len, :tgt_len]
    return float(np.mean(np.concatenate([block1.ravel(), block2.ravel()])))


def main():
    os.makedirs("/app/structures", exist_ok=True)
    os.makedirs("/app/pae", exist_ok=True)
    os.makedirs("/app/pae_normalized", exist_ok=True)

    # Target protein: 60-residue alpha helix along the z-axis
    target_coords = helix_coords(60)

    # Reference binder: 40-residue helix parallel to target
    ref_binder_coords = helix_coords(
        40, offset_x=7.0, offset_y=2.0, offset_z=1.5 * 15, phase=60.0
    )

    write_pdb("/app/structures/reference.pdb", {
        "A": [(x, y, z, 95.0) for x, y, z in target_coords],
        "B": [(x, y, z, 92.0) for x, y, z in ref_binder_coords],
    })

    # Five candidate designs with varying quality
    designs = {
        "design_1": {
            "binder_coords": perturb(ref_binder_coords, 0.3, seed=1001),
            "plddt_range": (88.0, 96.0),
            "plddt_seed": 2001,
            "pae_intra": (0.5, 2.5),
            "pae_inter": (1.0, 4.0),
            "pae_seed": 3001,
            "pae_format": "af2_legacy",
        },
        "design_2": {
            "binder_coords": perturb(ref_binder_coords, 1.2, seed=1002),
            "plddt_range": (72.0, 86.0),
            "plddt_seed": 2002,
            "pae_intra": (1.0, 4.0),
            "pae_inter": (4.0, 10.0),
            "pae_seed": 3002,
            "pae_format": "af2_v3",
        },
        "design_3": {
            "binder_coords": rotate_z(
                perturb(ref_binder_coords, 0.5, seed=1003), 25.0
            ),
            "plddt_range": (58.0, 75.0),
            "plddt_seed": 2003,
            "pae_intra": (2.0, 6.0),
            "pae_inter": (8.0, 18.0),
            "pae_seed": 3003,
            "pae_format": "af2_legacy",
        },
        "design_4": {
            "binder_coords": shift(
                perturb(ref_binder_coords, 0.3, seed=1004), 15.0, 15.0, 0.0
            ),
            "plddt_range": (80.0, 93.0),
            "plddt_seed": 2004,
            "pae_intra": (0.8, 3.0),
            "pae_inter": (12.0, 25.0),
            "pae_seed": 3004,
            "pae_format": "af2_v3",
        },
        "design_5": {
            "binder_coords": perturb(
                ref_binder_coords, 0.4, seed=1005,
                outlier_indices={5, 6, 7, 8, 25, 26, 27, 28, 29},
                outlier_sigma=7.0,
            ),
            "plddt_range": (55.0, 72.0),
            "plddt_seed": 2005,
            "pae_intra": (1.5, 5.0),
            "pae_inter": (5.0, 12.0),
            "pae_seed": 3005,
            "pae_format": "af2_legacy",
        },
    }

    target_len = 60
    binder_len = 40
    total_len = target_len + binder_len

    pae_matrices = {}

    for name in sorted(designs):
        cfg = designs[name]

        rng = random.Random(cfg["plddt_seed"])
        plddts = [round(rng.uniform(*cfg["plddt_range"]), 2)
                   for _ in range(binder_len)]

        write_pdb("/app/structures/%s.pdb" % name, {
            "A": [(x, y, z, 95.0) for x, y, z in target_coords],
            "B": [(x, y, z, pl)
                  for (x, y, z), pl in zip(cfg["binder_coords"], plddts)],
        })

        rng_pae = random.Random(cfg["pae_seed"])
        pae = []
        for i in range(total_len):
            row = []
            for j in range(total_len):
                if i == j:
                    row.append(0.0)
                elif (i < target_len and j < target_len) or \
                     (i >= target_len and j >= target_len):
                    row.append(round(rng_pae.uniform(*cfg["pae_intra"]), 2))
                else:
                    row.append(round(rng_pae.uniform(*cfg["pae_inter"]), 2))
            pae.append(row)

        pae_matrices[name] = pae

        # Write PAE in the appropriate format
        if cfg["pae_format"] == "af2_legacy":
            # Array-wrapped format: [{"predicted_aligned_error": [...], ...}]
            with open("/app/pae/%s_pae.json" % name, "w") as fh:
                json.dump(
                    [{"predicted_aligned_error": pae,
                      "max_predicted_aligned_error": 31.75}],
                    fh,
                )
        else:
            # AF2-v3 / ColabFold format: {"pae": [...], "max_pae": ..., ...}
            with open("/app/pae/%s_pae.json" % name, "w") as fh:
                json.dump(
                    {"pae": pae,
                     "max_pae": 31.75,
                     "ptm": round(random.Random(
                         cfg["pae_seed"] + 100).uniform(0.5, 0.95), 3),
                     "model_info": {"model_name": "af2_v3_multimer"}},
                    fh,
                )

    # Configuration
    config = {
        "target_chain": "A",
        "binder_chain": "B",
        "target_length": target_len,
        "binder_length": binder_len,
        "hotspot_residues": [16, 20, 25, 30, 35, 40],
        "contact_threshold_ca": 8.0,
        "lddt_inclusion_radius": 15.0,
        "lddt_thresholds": [0.5, 1.0, 2.0, 4.0],
        "scoring_weights": {
            "rmsd": -0.15,
            "lddt": 0.20,
            "tm_score": 0.15,
            "gdt_ts": 0.15,
            "hotspot_coverage": 0.10,
            "mean_plddt_normalized": 0.10,
            "interface_pae_normalized": -0.10,
            "contact_density": 0.05,
        },
        "filter_thresholds": {
            "max_rmsd": 20.0,
            "min_mean_plddt": 50.0,
        },
        "reference_structure": "/app/structures/reference.pdb",
        "design_structures": [
            "/app/structures/design_%d.pdb" % i for i in range(1, 6)
        ],
        "pae_dir": "/app/pae",
        "pae_normalized_dir": "/app/pae_normalized",
        "metrics_csv": "/app/metrics.csv",
        "database": "/app/designs.db",
        "output_file": "/app/results.json",
    }
    with open("/app/config.json", "w") as fh:
        json.dump(config, fh, indent=2)

    # ---- Compute expected results using correct implementations ----
    ref = parse_pdb_ca(config["reference_structure"])
    ref_binder = ref[config["binder_chain"]]["coords"]

    expected_designs = {}
    for design_path in config["design_structures"]:
        name = os.path.splitext(os.path.basename(design_path))[0]
        design = parse_pdb_ca(design_path)
        d_binder = design[config["binder_chain"]]["coords"]
        d_target = design[config["target_chain"]]["coords"]
        d_bfactors = design[config["binder_chain"]]["bfactors"]

        rmsd = ref_kabsch_rmsd(d_binder, ref_binder)
        lddt = ref_lddt(
            d_binder, ref_binder,
            config["lddt_inclusion_radius"],
            config["lddt_thresholds"],
        )
        tm = ref_tm_score(d_binder, ref_binder)
        gdt = ref_gdt_ts(d_binder, ref_binder)
        contacts = ref_interface_contacts(
            d_target, d_binder, config["contact_threshold_ca"]
        )
        hotspot = ref_hotspot_coverage(
            d_target, d_binder,
            config["hotspot_residues"],
            config["contact_threshold_ca"],
        )
        ipae = ref_interface_pae(
            pae_matrices[name], config["target_length"], config["binder_length"]
        )
        mean_plddt = float(np.mean(d_bfactors))

        w = config["scoring_weights"]
        composite = (
            w["rmsd"] * rmsd
            + w["lddt"] * lddt
            + w["tm_score"] * tm
            + w["gdt_ts"] * gdt
            + w["hotspot_coverage"] * hotspot
            + w["mean_plddt_normalized"] * (mean_plddt / 100.0)
            + w["interface_pae_normalized"] * (ipae / 31.75)
            + w["contact_density"] * (contacts / config["binder_length"])
        )

        expected_designs[name] = {
            "rmsd": round(rmsd, 6),
            "lddt": round(lddt, 6),
            "tm_score": round(tm, 6),
            "gdt_ts": round(gdt, 6),
            "interface_contacts": contacts,
            "hotspot_coverage": round(hotspot, 6),
            "interface_pae": round(ipae, 6),
            "mean_plddt": round(mean_plddt, 6),
            "composite_score": round(composite, 6),
        }

    ranking = sorted(
        expected_designs.keys(),
        key=lambda k: expected_designs[k]["composite_score"],
        reverse=True,
    )

    expected_output = {"designs": expected_designs, "ranking": ranking}
    with open("/app/expected_results.json", "w") as fh:
        json.dump(expected_output, fh, indent=2)

    print("Data generation and validation complete.")


if __name__ == "__main__":
    main()
