#!/usr/bin/env python3

"""
Multi-fingerprint fusion virtual screening pipeline for the BACE dataset.
Reads instance-specific parameters from /app/task_config.json.
"""

import json
import numpy as np
from scipy.stats import rankdata

from skfp.preprocessing import MolFromSmilesTransformer
from skfp.filters import PAINSFilter
from skfp.model_selection import randomized_scaffold_train_test_split
from skfp.fingerprints import (
    ECFPFingerprint,
    AtomPairFingerprint,
    MACCSFingerprint,
)
from skfp.distances import (
    bulk_tanimoto_binary_similarity,
    bulk_tanimoto_count_similarity,
)
from skfp.metrics import bedroc_score, enrichment_factor


def load_config():
    with open("/app/task_config.json") as f:
        return json.load(f)


def load_data():
    with open("/app/data/bace.json") as f:
        data = json.load(f)
    return data["smiles"], np.array(data["labels"])


def preprocess(smiles_list, y, pains_variants):
    n_raw = len(smiles_list)

    mol_transformer = MolFromSmilesTransformer(valid_only=True)
    mols, y = mol_transformer.transform_x_y(smiles_list, y)
    n_valid = len(mols)

    for variant in pains_variants:
        pains = PAINSFilter(variant=variant)
        mols, y = pains.transform_x_y(mols, y)

    n_after_pains = len(mols)
    n_actives = int(y.sum())
    n_inactives = n_after_pains - n_actives

    preprocessing_info = {
        "n_molecules_raw": n_raw,
        "n_molecules_valid": n_valid,
        "n_molecules_after_pains": n_after_pains,
        "n_actives_after_pains": n_actives,
        "n_inactives_after_pains": n_inactives,
    }

    return mols, y, preprocessing_info


def compute_vs_scores(mols_active_train, mols_test, fp, sim_fn):
    X_train = fp.transform(mols_active_train)
    X_test = fp.transform(mols_test)
    sims = sim_fn(X_train, X_test)
    return np.max(sims, axis=0)


def combsum_fusion(all_scores):
    normalized = {}
    for name, scores in all_scores.items():
        s_min, s_max = scores.min(), scores.max()
        if s_max > s_min:
            normalized[name] = (scores - s_min) / (s_max - s_min)
        else:
            normalized[name] = np.zeros_like(scores)
    return np.sum(list(normalized.values()), axis=0)


def rank_fusion(all_scores):
    ranks = []
    for scores in all_scores.values():
        ranks.append(rankdata(-scores, method="average"))
    avg_ranks = np.mean(ranks, axis=0)
    return -avg_ranks


def evaluate(y_test, y_pred_scores, alpha, ef_fraction):
    b = float(bedroc_score(y_test, y_pred_scores, alpha=alpha))
    ef = float(enrichment_factor(y_test, y_pred_scores, fraction=ef_fraction))
    return {"bedroc": b, "ef": ef}


def run_pipeline():
    config = load_config()
    print(f"Config: {json.dumps(config)}")

    alpha = config["bedroc_alpha"]
    ef_fraction = config["ef_percentage"] / 100
    seed_values = config["seed_values"]
    test_size = config["test_size"]
    pains_variants = config["pains_variants"]

    smiles_list, y = load_data()
    mols, y, preprocessing_info = preprocess(smiles_list, y, pains_variants)

    print(f"Preprocessing complete: {preprocessing_info}")

    fp_configs = {
        "ecfp_binary": (ECFPFingerprint(), bulk_tanimoto_binary_similarity),
        "ecfp_count": (ECFPFingerprint(count=True), bulk_tanimoto_count_similarity),
        "atom_pair": (AtomPairFingerprint(), bulk_tanimoto_binary_similarity),
        "maccs": (MACCSFingerprint(), bulk_tanimoto_binary_similarity),
    }

    per_split_results = []

    for seed in seed_values:
        print(f"Processing split seed={seed}...")

        mols_train, mols_test, y_train, y_test = (
            randomized_scaffold_train_test_split(
                mols, y, test_size=test_size, random_state=seed
            )
        )

        active_mask = y_train == 1
        mols_active_train = np.array(mols_train)[active_mask]

        split_result = {
            "seed": seed,
            "n_train": len(mols_train),
            "n_test": len(mols_test),
            "n_train_actives": int(active_mask.sum()),
            "methods": {},
        }

        individual_scores = {}

        for method_name, (fp, sim_fn) in fp_configs.items():
            scores = compute_vs_scores(mols_active_train, mols_test, fp, sim_fn)
            individual_scores[method_name] = scores
            split_result["methods"][method_name] = evaluate(
                y_test, scores, alpha, ef_fraction
            )

        cs_scores = combsum_fusion(individual_scores)
        split_result["methods"]["combsum_fusion"] = evaluate(
            y_test, cs_scores, alpha, ef_fraction
        )

        rf_scores = rank_fusion(individual_scores)
        split_result["methods"]["rank_fusion"] = evaluate(
            y_test, rf_scores, alpha, ef_fraction
        )

        per_split_results.append(split_result)

    method_names = [
        "ecfp_binary", "ecfp_count", "atom_pair",
        "maccs", "combsum_fusion", "rank_fusion",
    ]

    summary = {}
    for method in method_names:
        bedrocs = [s["methods"][method]["bedroc"] for s in per_split_results]
        efs = [s["methods"][method]["ef"] for s in per_split_results]
        summary[method] = {
            "bedroc_mean": float(np.mean(bedrocs)),
            "bedroc_std": float(np.std(bedrocs)),
            "ef_mean": float(np.mean(efs)),
            "ef_std": float(np.std(efs)),
        }

    summary["best_method_bedroc"] = max(
        method_names, key=lambda m: summary[m]["bedroc_mean"]
    )
    summary["best_method_ef"] = max(
        method_names, key=lambda m: summary[m]["ef_mean"]
    )

    output = {
        "config_used": config,
        "preprocessing": preprocessing_info,
        "per_split_results": per_split_results,
        "summary": summary,
    }

    with open("/app/results.json", "w") as f:
        json.dump(output, f, indent=2)

    print("Pipeline complete. Results written to /app/results.json")
    print(f"Best method by BEDROC: {summary['best_method_bedroc']}")
    print(f"Best method by EF: {summary['best_method_ef']}")


if __name__ == "__main__":
    run_pipeline()
