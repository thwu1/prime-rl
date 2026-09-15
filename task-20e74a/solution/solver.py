#!/usr/bin/env python3
"""Solver for phylogenetic tree evaluation and community analysis."""

import os
import re
import warnings

import numpy as np
import pandas as pd
from skbio import TreeNode, DistanceMatrix
from skbio.tree import upgma, nj, bme, rf_dists
from skbio.diversity import beta_diversity
from skbio.stats.distance import permanova


def fix_negative_lengths(tree):
    """Set any negative branch lengths to zero (can occur with NJ on non-additive data)."""
    for node in tree.traverse():
        if node.length is not None and node.length < 0:
            node.length = 0.0
    return tree


def compute_r2(res):
    """Derive R-squared from PERMANOVA results using the pseudo-F statistic.

    R² = SS_between / SS_total = 1 / (1 + (n - g) / ((g - 1) * F))
    """
    f_stat = float(res['test statistic'])
    n = int(res['sample size'])
    g = int(res['number of groups'])
    return 1.0 / (1.0 + (n - g) / ((g - 1) * f_stat))


def main():
    # === Read all data ===
    dm_df = pd.read_csv('/app/data/distance_matrix.tsv', sep='\t', index_col=0)
    otu_df = pd.read_csv('/app/data/otu_table.tsv', sep='\t', index_col=0)
    meta = pd.read_csv('/app/data/metadata.tsv', sep='\t', index_col=0)
    ref_tree = TreeNode.read('/app/data/reference_tree.nwk')

    # === Reconcile OTU naming conventions ===
    # Table: OTU_X  |  DM & tree: otuXXX
    dm_otus = set(dm_df.index)
    name_map = {}
    for col in otu_df.columns:
        m = re.match(r'OTU_(\d+)', col)
        if m:
            dm_name = f'otu{int(m.group(1)):03d}'
            if dm_name in dm_otus:
                name_map[col] = dm_name

    shared = sorted(name_map.values())
    print(f"Shared OTUs: {len(shared)}")

    # Sub-distance-matrix for shared OTUs
    dm_sub = DistanceMatrix(dm_df.loc[shared, shared].values, ids=shared)
    dm_sub_df = dm_df.loc[shared, shared]

    # Rename and filter OTU table to shared OTUs
    otu_renamed = otu_df.rename(columns=name_map)[shared]

    # === Build phylogenetic trees ===
    tree_upgma = fix_negative_lengths(upgma(dm_sub))
    tree_nj = fix_negative_lengths(nj(dm_sub)).root_at_midpoint()
    tree_bme = fix_negative_lengths(bme(dm_sub)).root_at_midpoint()

    # Prune reference tree to shared OTUs (remove outgroups)
    tree_tips = {tip.name for tip in ref_tree.tips()}
    ref_pruned = fix_negative_lengths(
        ref_tree.shear([s for s in shared if s in tree_tips])
    )

    labels = ['reference', 'upgma', 'nj', 'bme']
    trees = [ref_pruned, tree_upgma, tree_nj, tree_bme]

    os.makedirs('/app/results', exist_ok=True)

    # === 1. Robinson-Foulds distances ===
    rf = rf_dists(trees)
    rf_df = pd.DataFrame(rf.data, index=labels, columns=labels)
    rf_df.to_csv('/app/results/tree_rf_distances.tsv', sep='\t')
    print(f"\nRF distances:\n{rf_df}")

    # === 2. Cophenetic correlations ===
    coph_rows = []
    for label, tree in zip(labels, trees):
        coph = tree.cophenet()
        coph_df_inner = coph.to_data_frame()
        common = sorted(set(coph_df_inner.index) & set(shared))
        n = len(common)
        idx = np.triu_indices(n, k=1)
        c_vals = coph_df_inner.loc[common, common].values[idx]
        d_vals = dm_sub_df.loc[common, common].values[idx]
        r = float(np.corrcoef(c_vals, d_vals)[0, 1])
        coph_rows.append({'method': label, 'pearson_r': round(r, 6)})
        print(f"  {label}: cophenetic r = {r:.6f}")

    coph_out = pd.DataFrame(coph_rows).sort_values('pearson_r', ascending=False)
    coph_out.to_csv('/app/results/cophenetic_correlations.tsv', sep='\t', index=False)

    best_method = str(coph_out.iloc[0]['method'])
    best_idx = labels.index(best_method)
    best_tree = trees[best_idx]

    with open('/app/results/best_tree_method.txt', 'w') as f:
        f.write(best_method + '\n')
    best_tree.write('/app/results/best_tree.nwk')
    print(f"\nBest tree method: {best_method}")

    # === 3. Sample QC ===
    depths = otu_renamed.sum(axis=1)
    qc_rows = []
    for sid in sorted(otu_renamed.index):
        d = int(depths[sid])
        qc_rows.append({
            'sample_id': sid,
            'depth': d,
            'status': 'pass' if d >= 1000 else 'fail',
        })
    pd.DataFrame(qc_rows).to_csv('/app/results/sample_qc.tsv', sep='\t', index=False)

    passing = sorted([r['sample_id'] for r in qc_rows if r['status'] == 'pass'])
    failing = [r['sample_id'] for r in qc_rows if r['status'] == 'fail']
    min_depth = int(depths[passing].min())
    with open('/app/results/rarefaction_depth.txt', 'w') as f:
        f.write(str(min_depth) + '\n')
    print(f"QC: {len(passing)} pass, {len(failing)} fail | Rarefy to {min_depth}")

    # === 4. Rarefaction ===
    otu_pass = otu_renamed.loc[passing]
    rng = np.random.default_rng(42)
    rarefied = np.zeros((len(passing), len(shared)), dtype=int)
    for i in range(len(passing)):
        counts = otu_pass.values[i]
        probs = counts / counts.sum()
        rarefied[i] = rng.multinomial(min_depth, probs)

    # === 5. Metric impact: PERMANOVA for treatment with each tree ===
    meta_pass = meta.loc[passing]
    impact_rows = []
    for label, tree in zip(labels, trees):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wuf = beta_diversity('weighted_unifrac', rarefied,
                                 ids=passing, tree=tree, taxa=shared)
        res = permanova(wuf, meta_pass['treatment'], permutations=999, seed=42)
        f_stat = float(res['test statistic'])
        r2 = compute_r2(res)
        impact_rows.append({
            'tree_method': label,
            'pseudo_f': round(f_stat, 6),
            'r_squared': round(r2, 6),
        })
        print(f"  {label}: F={f_stat:.4f}, R²={r2:.4f}")

    pd.DataFrame(impact_rows).to_csv('/app/results/metric_impact.tsv',
                                      sep='\t', index=False)

    # === 6. Variance partitioning (best tree) ===
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        best_wuf = beta_diversity('weighted_unifrac', rarefied,
                                  ids=passing, tree=best_tree, taxa=shared)

    # Marginal PERMANOVA for each variable
    res_t = permanova(best_wuf, meta_pass['treatment'], permutations=999, seed=42)
    r2_t = compute_r2(res_t)

    res_b = permanova(best_wuf, meta_pass['batch'], permutations=999, seed=42)
    r2_b = compute_r2(res_b)

    # Joint PERMANOVA using combined treatment×batch variable
    combined = meta_pass['treatment'] + '_' + meta_pass['batch']
    combined.name = 'group'
    res_c = permanova(best_wuf, combined, permutations=999, seed=42)
    r2_c = compute_r2(res_c)

    # Variance decomposition
    unique_t = r2_c - r2_b
    unique_b = r2_c - r2_t
    shared_var = r2_t + r2_b - r2_c
    residual = 1.0 - r2_c

    vp = pd.DataFrame([
        {'component': 'treatment_total', 'r_squared': round(r2_t, 6)},
        {'component': 'batch_total', 'r_squared': round(r2_b, 6)},
        {'component': 'treatment_unique', 'r_squared': round(unique_t, 6)},
        {'component': 'batch_unique', 'r_squared': round(unique_b, 6)},
        {'component': 'shared', 'r_squared': round(shared_var, 6)},
        {'component': 'residual', 'r_squared': round(residual, 6)},
    ])
    vp.to_csv('/app/results/variance_partitioning.tsv', sep='\t', index=False)

    print(f"\nVariance partitioning:")
    print(f"  Treatment total: {r2_t:.4f} (unique: {unique_t:.4f})")
    print(f"  Batch total:     {r2_b:.4f} (unique: {unique_b:.4f})")
    print(f"  Shared:          {shared_var:.4f}")
    print(f"  Residual:        {residual:.4f}")

    # === 7. Assessment ===
    assessment = 'genuine' if unique_t > unique_b else 'confounded'
    with open('/app/results/assessment.txt', 'w') as f:
        f.write(assessment + '\n')
    print(f"\nAssessment: {assessment}")


if __name__ == '__main__':
    main()
