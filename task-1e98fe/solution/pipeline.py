#!/usr/bin/env python3

"""
Virtual screening pipeline with QSAR-guided reranking.
Reads molecular datasets, applies cascade filtering, trains a QSAR model,
performs applicability domain analysis, clusters candidates, and selects
representative molecules with composite scoring.
"""

import csv
import json
import os
import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, Descriptors, Crippen, FilterCatalog, DataStructs
from rdkit.Chem.Scaffolds import MurckoScaffold
from rdkit.ML.Cluster import Butina
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import r2_score, mean_squared_error


TRAINING_CSV = "/app/data/training_set.csv"
LIBRARY_CSV = "/app/data/screening_library.csv"
OUTPUT_PATH = "/app/output/report.json"

FP_RADIUS = 2
FP_NBITS = 2048


def get_fp(mol):
    return AllChem.GetMorganFingerprintAsBitVect(mol, FP_RADIUS, nBits=FP_NBITS)


def load_training_data():
    total = 0
    smiles_list = []
    mols = []
    activities = []
    with open(TRAINING_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            smi = row["smiles"].strip()
            if not smi:
                continue
            mol = Chem.MolFromSmiles(smi)
            if mol is not None:
                smiles_list.append(Chem.MolToSmiles(mol))
                mols.append(mol)
                activities.append(float(row["pIC50"]))
    return total, smiles_list, mols, activities


def load_screening_library():
    total = 0
    valid_count = 0
    unique_mols = {}  # canonical SMILES -> mol
    with open(LIBRARY_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            smi = row["smiles"].strip()
            if not smi:
                continue
            mol = Chem.MolFromSmiles(smi)
            if mol is not None:
                valid_count += 1
                can = Chem.MolToSmiles(mol)
                if can not in unique_mols:
                    unique_mols[can] = mol
    return total, valid_count, unique_mols


def cascade_filter(mols_dict):
    items = list(mols_dict.items())  # (canonical_smi, mol)

    # Lipinski's Rule of Five
    lipinski = [(s, m) for s, m in items if
                Descriptors.MolWt(m) <= 500 and
                Crippen.MolLogP(m) <= 5 and
                Descriptors.NumHDonors(m) <= 5 and
                Descriptors.NumHAcceptors(m) <= 10]

    # Veber rules
    veber = [(s, m) for s, m in lipinski if
             Descriptors.TPSA(m) <= 140 and
             Descriptors.NumRotatableBonds(m) <= 10]

    # PAINS filter
    pp = FilterCatalog.FilterCatalogParams()
    pp.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS)
    pc = FilterCatalog.FilterCatalog(pp)
    pains = [(s, m) for s, m in veber if pc.GetFirstMatch(m) is None]

    # Brenk filter
    bp = FilterCatalog.FilterCatalogParams()
    bp.AddCatalog(FilterCatalog.FilterCatalogParams.FilterCatalogs.BRENK)
    bc = FilterCatalog.FilterCatalog(bp)
    brenk = [(s, m) for s, m in pains if bc.GetFirstMatch(m) is None]

    counts = {
        "input": len(items),
        "after_lipinski": len(lipinski),
        "after_veber": len(veber),
        "after_pains": len(pains),
        "after_brenk": len(brenk),
    }
    return brenk, counts


def build_qsar(mols, activities):
    fps = [get_fp(m) for m in mols]
    X = np.array([list(fp) for fp in fps])
    y = np.array(activities)

    # Murcko generic scaffold grouping
    scaffold_map = {}
    groups = np.zeros(len(mols), dtype=int)
    for i, mol in enumerate(mols):
        try:
            core = MurckoScaffold.GetScaffoldForMol(mol)
            generic = MurckoScaffold.MakeScaffoldGeneric(core)
            sca_smi = Chem.MolToSmiles(generic)
        except Exception:
            sca_smi = f"_no_scaffold_{i}"
        if sca_smi not in scaffold_map:
            scaffold_map[sca_smi] = len(scaffold_map)
        groups[i] = scaffold_map[sca_smi]

    # Scaffold-based split
    gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=42)
    train_idx, test_idx = next(gss.split(X, y, groups))

    # Train Random Forest
    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X[train_idx], y[train_idx])

    # Evaluate
    y_pred_test = model.predict(X[test_idx])
    r2 = float(r2_score(y[test_idx], y_pred_test))
    rmse = float(np.sqrt(mean_squared_error(y[test_idx], y_pred_test)))

    info = {
        "n_train": int(len(train_idx)),
        "n_test": int(len(test_idx)),
        "r2_test": round(r2, 4),
        "rmse_test": round(rmse, 4),
    }
    return model, fps, info


def compute_ad(train_fps, candidate_fps):
    # Training set internal nearest-neighbor distances
    nn_dists = []
    for i in range(len(train_fps)):
        dists_i = [1.0 - DataStructs.TanimotoSimilarity(train_fps[i], train_fps[j])
                   for j in range(len(train_fps)) if j != i]
        nn_dists.append(min(dists_i))

    threshold = float(np.percentile(nn_dists, 95))

    # Classify candidates
    in_ad = []
    for fp in candidate_fps:
        nn = min(1.0 - DataStructs.TanimotoSimilarity(fp, tfp) for tfp in train_fps)
        in_ad.append(nn <= threshold)

    return threshold, in_ad


def butina_cluster(fps, cutoff=0.4):
    n = len(fps)
    if n == 0:
        return []
    if n == 1:
        return [(0,)]

    # Lower-triangular distance matrix
    dists = []
    for i in range(1, n):
        for j in range(i):
            dists.append(1.0 - DataStructs.TanimotoSimilarity(fps[i], fps[j]))

    return Butina.ClusterData(dists, n, cutoff, isDistData=True)


def main():
    os.makedirs("/app/output", exist_ok=True)

    # === 1. Load and validate data ===
    train_total, train_smiles, train_mols, train_activities = load_training_data()
    lib_total, lib_valid, lib_mols = load_screening_library()

    # === 2. Cascade drug-likeness filtering ===
    filtered, cascade_counts = cascade_filter(lib_mols)

    # === 3. Build QSAR model ===
    model, train_fps, qsar_info = build_qsar(train_mols, train_activities)

    # === 4. Predict pIC50 for filtered candidates ===
    cand_fps = [get_fp(m) for _, m in filtered]
    if cand_fps:
        X_cand = np.array([list(fp) for fp in cand_fps])
        predictions = model.predict(X_cand).tolist()
    else:
        predictions = []

    # === 5. Applicability domain analysis ===
    if cand_fps:
        ad_threshold, in_ad_flags = compute_ad(train_fps, cand_fps)
    else:
        ad_threshold = 0.0
        in_ad_flags = []

    n_in_ad = sum(in_ad_flags)
    n_out_ad = len(in_ad_flags) - n_in_ad

    # === 6. Cluster in-AD candidates ===
    in_ad_indices = [i for i, flag in enumerate(in_ad_flags) if flag]
    in_ad_fps = [cand_fps[i] for i in in_ad_indices]
    clusters = butina_cluster(in_ad_fps, cutoff=0.4)
    cluster_sizes = [len(c) for c in clusters]

    # === 7. Select best per cluster (highest predicted pIC50) ===
    selected = []
    for cluster_id, cluster in enumerate(clusters):
        best_local = max(cluster, key=lambda idx: predictions[in_ad_indices[idx]])
        global_idx = in_ad_indices[best_local]
        smi, mol = filtered[global_idx]
        pred = predictions[global_idx]
        qed_val = Descriptors.qed(mol)
        selected.append({
            "smiles": smi,
            "predicted_pIC50": round(pred, 4),
            "qed": round(qed_val, 4),
            "cluster_id": cluster_id,
            "in_ad": True,
        })

    # === 8. Compute composite scores ===
    if len(selected) > 0:
        preds_sel = [s["predicted_pIC50"] for s in selected]
        min_p, max_p = min(preds_sel), max(preds_sel)
        for s in selected:
            if max_p > min_p:
                norm_p = (s["predicted_pIC50"] - min_p) / (max_p - min_p)
            else:
                norm_p = 1.0
            s["composite_score"] = round(0.6 * norm_p + 0.4 * s["qed"], 4)

    # === 9. Write report ===
    report = {
        "validation": {
            "training_total": train_total,
            "training_valid": len(train_mols),
            "library_total": lib_total,
            "library_valid": lib_valid,
            "library_unique": len(lib_mols),
        },
        "cascade_filter": cascade_counts,
        "qsar_model": qsar_info,
        "applicability_domain": {
            "ad_threshold": round(ad_threshold, 4),
            "n_in_ad": n_in_ad,
            "n_out_ad": n_out_ad,
        },
        "clustering": {
            "n_clusters": len(clusters),
            "cluster_sizes": cluster_sizes,
        },
        "selected_candidates": selected,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(report, f, indent=2)

    print(f"Pipeline complete. Report written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
