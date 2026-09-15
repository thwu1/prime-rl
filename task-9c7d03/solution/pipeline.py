#!/usr/bin/env python3
"""QSAR-driven virtual screening pipeline for lead compound discovery."""

import csv
import json
import math
import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, Descriptors, Crippen, FilterCatalog, DataStructs
from rdkit.Chem.Scaffolds import MurckoScaffold
from rdkit.ML.Cluster import Butina
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import r2_score, mean_squared_error


def load_training_data(path):
    smiles, activities = [], []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            smiles.append(row['smiles'])
            activities.append(float(row['pIC50']))
    return smiles, activities


def load_screening_data(path):
    smiles = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            smiles.append(row['smiles'])
    return smiles


def compute_fp(mol, radius=2, nbits=2048):
    return AllChem.GetMorganFingerprintAsBitVect(mol, radius, nBits=nbits)


def scaffold_split(mols, train_frac=0.8):
    """Generic Murcko scaffold-based split with alphabetical scaffold ordering."""
    scaffold_groups = {}
    for i, mol in enumerate(mols):
        core = MurckoScaffold.GetScaffoldForMol(mol)
        generic = MurckoScaffold.MakeScaffoldGeneric(core)
        smi = Chem.MolToSmiles(generic)
        if smi not in scaffold_groups:
            scaffold_groups[smi] = []
        scaffold_groups[smi].append(i)

    sorted_keys = sorted(scaffold_groups.keys())
    target = int(train_frac * len(mols))

    train_idx, test_idx = [], []
    for key in sorted_keys:
        indices = scaffold_groups[key]
        if len(train_idx) < target:
            train_idx.extend(indices)
        else:
            test_idx.extend(indices)

    # Ensure test set is non-empty
    if not test_idx and len(sorted_keys) > 1:
        last_key = sorted_keys[-1]
        last_indices = set(scaffold_groups[last_key])
        train_idx = [i for i in train_idx if i not in last_indices]
        test_idx = list(last_indices)

    return train_idx, test_idx


def lipinski_ok(mol):
    return (Descriptors.MolWt(mol) <= 500
            and Crippen.MolLogP(mol) <= 5
            and Descriptors.NumHDonors(mol) <= 5
            and Descriptors.NumHAcceptors(mol) <= 10)


def veber_ok(mol):
    return (Descriptors.TPSA(mol) <= 140
            and Descriptors.NumRotatableBonds(mol) <= 10)


def build_filter_catalog(catalog_enum):
    params = FilterCatalog.FilterCatalogParams()
    params.AddCatalog(catalog_enum)
    return FilterCatalog.FilterCatalog(params)


def main():
    # ── Load data ──
    train_smiles_raw, train_acts_raw = load_training_data('/app/training_data.csv')
    screen_smiles_raw = load_screening_data('/app/screening_library.csv')
    n_screening = len(screen_smiles_raw)

    # ── Parse & featurize training molecules ──
    train_data = []  # (smi, mol, fp, act)
    for smi, act in zip(train_smiles_raw, train_acts_raw):
        mol = Chem.MolFromSmiles(smi)
        if mol is not None:
            train_data.append((smi, mol, compute_fp(mol), act))

    train_mols = [d[1] for d in train_data]
    train_fps = [d[2] for d in train_data]
    train_acts = np.array([d[3] for d in train_data])

    # ── Scaffold split ──
    train_idx, test_idx = scaffold_split(train_mols)
    X_all = np.array([list(fp) for fp in train_fps])

    X_train, y_train = X_all[train_idx], train_acts[train_idx]
    X_test, y_test = X_all[test_idx], train_acts[test_idx]

    # ── Train QSAR model ──
    rf = RandomForestRegressor(n_estimators=100, random_state=42)
    rf.fit(X_train, y_train)

    y_pred_test = rf.predict(X_test)
    r2 = round(float(r2_score(y_test, y_pred_test)), 2)
    rmse = round(float(math.sqrt(mean_squared_error(y_test, y_pred_test))), 2)

    # ── Parse screening molecules ──
    screen_data = []  # (smi, mol, fp)
    for smi in screen_smiles_raw:
        mol = Chem.MolFromSmiles(smi)
        if mol is not None:
            screen_data.append((smi, mol, compute_fp(mol)))
    n_valid = len(screen_data)

    # ── Predict activities ──
    X_screen = np.array([list(d[2]) for d in screen_data])
    pred_acts = rf.predict(X_screen)

    # ── Activity filter (pIC50 >= 5.0) ──
    active = [(smi, mol, fp, pred)
              for (smi, mol, fp), pred in zip(screen_data, pred_acts)
              if pred >= 5.0]
    n_active = len(active)

    # ── Cascade ADMET filters ──
    after_lipinski = [(s, m, f, p) for s, m, f, p in active if lipinski_ok(m)]
    n_after_lipinski = len(after_lipinski)

    after_veber = [(s, m, f, p) for s, m, f, p in after_lipinski if veber_ok(m)]
    n_after_veber = len(after_veber)

    pains_cat = build_filter_catalog(
        FilterCatalog.FilterCatalogParams.FilterCatalogs.PAINS)
    after_pains = [(s, m, f, p) for s, m, f, p in after_veber
                   if pains_cat.GetFirstMatch(m) is None]
    n_after_pains = len(after_pains)

    brenk_cat = build_filter_catalog(
        FilterCatalog.FilterCatalogParams.FilterCatalogs.BRENK)
    after_brenk = [(s, m, f, p) for s, m, f, p in after_pains
                   if brenk_cat.GetFirstMatch(m) is None]
    n_after_brenk = len(after_brenk)

    # ── Applicability domain ──
    # NN distances within full training set
    nn_dists = []
    for i, fp_i in enumerate(train_fps):
        min_d = min(1.0 - DataStructs.TanimotoSimilarity(fp_i, train_fps[j])
                    for j in range(len(train_fps)) if j != i)
        nn_dists.append(min_d)
    ad_threshold = float(np.percentile(nn_dists, 95))

    in_ad = []
    for s, m, f, p in after_brenk:
        d = min(1.0 - DataStructs.TanimotoSimilarity(f, tfp) for tfp in train_fps)
        if d <= ad_threshold:
            in_ad.append((s, m, f, p))
    n_in_ad = len(in_ad)

    # ── Butina clustering ──
    if len(in_ad) == 0:
        clusters = []
    elif len(in_ad) == 1:
        clusters = [(0,)]
    else:
        fps_ad = [x[2] for x in in_ad]
        n = len(fps_ad)
        dists = []
        for i in range(1, n):
            for j in range(i):
                dists.append(
                    1.0 - DataStructs.TanimotoSimilarity(fps_ad[i], fps_ad[j]))
        clusters = Butina.ClusterData(dists, n, 0.4, isDistData=True)

    n_clusters = len(clusters)

    # ── Select best per cluster ──
    selected = []
    for cid, cluster in enumerate(clusters):
        best = max(cluster, key=lambda idx: in_ad[idx][3])
        smi, mol, _, pred = in_ad[best]
        selected.append({
            "smiles": smi,
            "predicted_pIC50": round(float(pred), 4),
            "MW": round(float(Descriptors.MolWt(mol)), 2),
            "LogP": round(float(Crippen.MolLogP(mol)), 4),
            "TPSA": round(float(Descriptors.TPSA(mol)), 2),
            "QED": round(float(Descriptors.qed(mol)), 4),
            "cluster_id": cid,
        })

    # ── Write report ──
    report = {
        "model_performance": {
            "r_squared": r2,
            "rmse": rmse,
            "n_train": len(train_idx),
            "n_test": len(test_idx),
        },
        "pipeline_summary": {
            "n_screening": n_screening,
            "n_valid": n_valid,
            "n_active": n_active,
            "n_after_lipinski": n_after_lipinski,
            "n_after_veber": n_after_veber,
            "n_after_pains": n_after_pains,
            "n_after_brenk": n_after_brenk,
            "n_in_ad": n_in_ad,
            "n_clusters": n_clusters,
            "n_selected": len(selected),
        },
        "selected_leads": selected,
    }

    with open('/app/report.json', 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Pipeline complete. {len(selected)} leads from {n_clusters} clusters.")
    print(f"Model: R²={r2}, RMSE={rmse}")
    print(f"Screening: {n_screening} → {n_valid} valid → {n_active} active")
    print(f"ADMET: Lipinski={n_after_lipinski} → Veber={n_after_veber} "
          f"→ PAINS={n_after_pains} → Brenk={n_after_brenk}")
    print(f"AD: {n_in_ad} in domain, {n_clusters} clusters")


if __name__ == '__main__':
    main()
