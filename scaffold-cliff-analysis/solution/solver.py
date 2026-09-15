#!/usr/bin/env python3
"""

Solution: SAR landscape analysis pipeline.
Reads project config, cleans multi-source data, and produces all analysis outputs.
"""
import json
import os

import numpy as np
import pandas as pd
import yaml
from rdkit import Chem
from rdkit.Chem import AllChem, DataStructs
from rdkit.Chem.Scaffolds import MurckoScaffold


def load_config(project_dir):
    """Load pipeline configuration."""
    config_path = os.path.join(project_dir, "config", "pipeline.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


def clean_data(project_dir, config):
    """
    Clean and merge raw data following project configuration.
    - Read structures and bioactivity from separate files
    - Remove excluded compounds
    - Filter invalid SMILES
    - Average duplicate bioactivity measurements
    - Inner join to require both structure and activity
    """
    data_dir = os.path.join(project_dir, "data")

    # Read structures
    structures = pd.read_csv(os.path.join(data_dir, "structures.csv"))

    # Read bioactivity (TSV format)
    bioactivity = pd.read_csv(os.path.join(data_dir, "bioactivity.tsv"), sep="\t")

    # Read exclusions
    with open(os.path.join(data_dir, "exclusions.json")) as f:
        exclusions = json.load(f)
    excluded_ids = set(exclusions["excluded_compounds"])

    # Remove excluded compounds
    structures = structures[~structures["compound_id"].isin(excluded_ids)].copy()
    bioactivity = bioactivity[~bioactivity["compound_id"].isin(excluded_ids)].copy()

    # Validate SMILES
    valid_rows = []
    for _, row in structures.iterrows():
        mol = Chem.MolFromSmiles(row["smiles"])
        if mol is not None:
            valid_rows.append(row)
    structures = pd.DataFrame(valid_rows)

    # Average duplicate bioactivity measurements
    bioactivity_agg = (
        bioactivity.groupby("compound_id")["pIC50"].mean().reset_index()
    )

    # Inner join: require both valid structure and bioactivity
    merged = pd.merge(structures, bioactivity_agg, on="compound_id")
    merged = merged.sort_values("compound_id").reset_index(drop=True)

    return merged


def main():
    project_dir = "/app/project"
    results_dir = "/app/results"
    os.makedirs(results_dir, exist_ok=True)

    # Load configuration
    config = load_config(project_dir)

    # Clean and merge data
    df = clean_data(project_dir, config)
    n = len(df)
    print(f"Cleaned dataset: {n} compounds")

    # Parse SMILES and canonicalize
    mols = []
    canonical_smiles = []
    for _, row in df.iterrows():
        mol = Chem.MolFromSmiles(row["smiles"])
        if mol is None:
            raise ValueError(f"Failed to parse SMILES: {row['smiles']}")
        mols.append(mol)
        canonical_smiles.append(Chem.MolToSmiles(mol))

    # Compute fingerprints from config
    fp_cfg = config["molecular_representation"]
    radius = fp_cfg["radius"]
    n_bits = fp_cfg["num_bits"]
    fps = [
        AllChem.GetMorganFingerprintAsBitVect(m, radius, nBits=n_bits)
        for m in mols
    ]

    # Build pairwise Tanimoto similarity matrix
    sim_matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            sim_matrix[i][j] = DataStructs.TanimotoSimilarity(fps[i], fps[j])

    # Get output precision from config
    prec = config["output"]["precision"]

    # Write tanimoto_matrix.csv
    ids = df["compound_id"].tolist()
    sim_df = pd.DataFrame(
        np.round(sim_matrix, prec["similarity_matrix"]),
        index=ids,
        columns=ids,
    )
    sim_df.to_csv(os.path.join(results_dir, "tanimoto_matrix.csv"))

    # Identify activity cliffs, compute SALI and cliff scores
    cliff_cfg = config["pairwise_analysis"]["cliff_detection"]
    min_sim = cliff_cfg["min_similarity"]
    min_delta = cliff_cfg["min_activity_difference"]

    cliff_data = []
    cliff_scores = {row["compound_id"]: 0.0 for _, row in df.iterrows()}
    max_sali = 0.0

    for i in range(n):
        for j in range(i + 1, n):
            sim = sim_matrix[i][j]
            delta = abs(df.iloc[i]["pIC50"] - df.iloc[j]["pIC50"])
            if sim >= min_sim and delta >= min_delta:
                if sim < 1.0:
                    sali = delta / (1.0 - sim)
                else:
                    sali = None

                cpd1 = df.iloc[i]["compound_id"]
                cpd2 = df.iloc[j]["compound_id"]
                if cpd1 > cpd2:
                    cpd1, cpd2 = cpd2, cpd1

                cliff_prec = prec["cliff_report"]
                cliff_data.append(
                    {
                        "cpd1": cpd1,
                        "cpd2": cpd2,
                        "similarity": round(sim, cliff_prec),
                        "delta_pIC50": round(delta, cliff_prec),
                        "sali_score": (
                            round(sali, cliff_prec) if sali is not None else None
                        ),
                    }
                )

                if sali is not None:
                    cliff_scores[df.iloc[i]["compound_id"]] += sali
                    cliff_scores[df.iloc[j]["compound_id"]] += sali
                    max_sali = max(max_sali, sali)

    # Write activity_cliffs.csv
    cliffs_df = pd.DataFrame(cliff_data)
    if len(cliffs_df) > 0:
        cliffs_df.to_csv(
            os.path.join(results_dir, "activity_cliffs.csv"), index=False
        )
    else:
        pd.DataFrame(
            columns=["cpd1", "cpd2", "similarity", "delta_pIC50", "sali_score"]
        ).to_csv(os.path.join(results_dir, "activity_cliffs.csv"), index=False)

    # Compute Murcko scaffolds
    scaffold_rows = []
    scaffold_map = {}
    for i, mol in enumerate(mols):
        scaf_mol = MurckoScaffold.GetScaffoldForMol(mol)
        if scaf_mol.GetNumAtoms() > 0:
            scaf_smiles = Chem.MolToSmiles(scaf_mol)
        else:
            scaf_smiles = ""
        cpd_id = df.iloc[i]["compound_id"]
        scaffold_rows.append(
            {
                "compound_id": cpd_id,
                "canonical_smiles": canonical_smiles[i],
                "murcko_scaffold": scaf_smiles,
            }
        )
        scaffold_map[cpd_id] = scaf_smiles

    scaffolds_df = pd.DataFrame(scaffold_rows)
    scaffolds_df.to_csv(os.path.join(results_dir, "scaffolds.csv"), index=False)

    # Scaffold statistics
    scaffold_groups = {}
    for cpd_id, scaf in scaffold_map.items():
        if scaf not in scaffold_groups:
            scaffold_groups[scaf] = []
        scaffold_groups[scaf].append(cpd_id)

    scaffold_stats = []
    stats_prec = prec["scaffold_statistics"]
    for scaf, cpd_ids in scaffold_groups.items():
        pIC50s = [
            df[df["compound_id"] == cid]["pIC50"].values[0] for cid in cpd_ids
        ]
        std_val = float(np.std(pIC50s, ddof=1)) if len(pIC50s) > 1 else 0.0
        scaffold_stats.append(
            {
                "scaffold": scaf,
                "n_compounds": len(cpd_ids),
                "mean_pIC50": round(float(np.mean(pIC50s)), stats_prec),
                "std_pIC50": round(std_val, stats_prec),
            }
        )

    stats_df = pd.DataFrame(scaffold_stats)
    stats_df.to_csv(os.path.join(results_dir, "scaffold_stats.csv"), index=False)

    # Summary statistics
    median_cliff_score = float(np.median(list(cliff_scores.values())))
    n_generators = sum(1 for v in cliff_scores.values() if v > median_cliff_score)

    summary_prec = prec["summary_statistics"]
    summary = {
        "n_compounds": n,
        "n_unique_scaffolds": len(scaffold_groups),
        "n_activity_cliffs": len(cliff_data),
        "n_cliff_generators": n_generators,
        "max_sali": round(float(max_sali), summary_prec),
        "median_cliff_score": round(median_cliff_score, summary_prec),
    }

    with open(os.path.join(results_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Analysis complete.")
    print(f"  Compounds: {n}")
    print(f"  Unique scaffolds: {len(scaffold_groups)}")
    print(f"  Activity cliffs: {len(cliff_data)}")
    print(f"  Cliff generators: {n_generators}")
    print(f"  Max SALI: {max_sali:.4f}")
    print(f"  Median cliff score: {median_cliff_score:.4f}")


if __name__ == "__main__":
    main()
