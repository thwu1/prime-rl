#!/usr/bin/env python3
"""Pipeline C: Conservative enrichment analysis.

Uses library-size normalization with PCA clustering, then focuses on
downregulated genes for perturbation identification. Suppressed pathways
often provide the clearest signal for identifying treatment effects, as
upregulated genes can include non-specific stress responses.
"""
import json
import sqlite3
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler


def load_data():
    conn = sqlite3.connect('/app/data/experiment.db')
    counts_long = pd.read_sql(
        'SELECT gene_symbol, sample_id, raw_count FROM expression_data', conn)
    counts = counts_long.pivot(
        index='gene_symbol', columns='sample_id', values='raw_count')
    metadata = pd.read_sql(
        'SELECT sample_id, assigned_condition, processing_batch FROM samples', conn)
    conn.close()
    return counts, metadata


def main():
    counts, metadata = load_data()
    samples = sorted(counts.columns.tolist())
    counts = counts[samples]
    meta_dict = dict(zip(metadata['sample_id'], metadata['assigned_condition']))

    # Filter low expression
    gene_means = counts.mean(axis=1)
    counts_filt = counts[gene_means > 10]

    # Log2 transform
    log_counts = np.log2(counts_filt + 1)

    # Library-size normalization: subtract per-sample median
    sample_medians = log_counts.median(axis=0)
    log_norm = log_counts - sample_medians

    # PCA + K-means
    X = StandardScaler().fit_transform(log_norm.T.values)
    pcs = PCA(n_components=5, random_state=42).fit_transform(X)
    clusters = KMeans(n_clusters=2, random_state=42, n_init=20).fit_predict(pcs[:, :2])

    # Map clusters to conditions
    cluster_cond = {}
    for c in [0, 1]:
        members = [samples[i] for i in range(len(samples)) if clusters[i] == c]
        ctrl = sum(1 for s in members if meta_dict[s] == 'Control')
        treat = sum(1 for s in members if meta_dict[s] == 'Treatment')
        cluster_cond[c] = 'Control' if ctrl > treat else 'Treatment'

    mislabeled = []
    true_labels = {}
    for i, s in enumerate(samples):
        inferred = cluster_cond[clusters[i]]
        true_labels[s] = inferred
        if inferred != meta_dict[s]:
            mislabeled.append(s)

    # DEA on corrected labels
    ctrl = [s for s in samples if true_labels[s] == 'Control']
    treat = [s for s in samples if true_labels[s] == 'Treatment']

    # Focus on downregulated genes for more specific pathway identification
    de_down = []
    for gene in counts_filt.index:
        ctrl_vals = log_counts.loc[gene, ctrl].values
        treat_vals = log_counts.loc[gene, treat].values
        log2fc = treat_vals.mean() - ctrl_vals.mean()
        _, pval = stats.ttest_ind(treat_vals, ctrl_vals, equal_var=False)
        if pval < 1e-5 and log2fc < -1.0:
            de_down.append(gene)

    # Enrichment on downregulated gene set
    pathways = {}
    with open('/app/data/pathway_annotations.gmt') as f:
        for line in f:
            parts = line.strip().split('\t')
            pathways[parts[0]] = set(parts[2:])

    all_genes_set = set(counts_filt.index)
    de_set = set(de_down)

    results_list = []
    for pname, pgenes in pathways.items():
        pg = pgenes & all_genes_set
        if len(pg) < 3:
            continue
        a = len(de_set & pg)
        b = len(de_set - pg)
        c_ = len(pg - de_set)
        d = len(all_genes_set - de_set - pg)
        _, pv = stats.fisher_exact([[a, b], [c_, d]], alternative='greater')
        results_list.append((pname, a, len(pg), pv))

    results_list.sort(key=lambda x: x[3])
    top = results_list[0] if results_list else None

    mapping = {
        'CELL_CYCLE_REGULATION': 'cell cycle arrest',
        'HEAT_SHOCK_RESPONSE': 'heat shock',
        'OXIDATIVE_STRESS_RESPONSE': 'oxidative stress',
    }
    perturbation = mapping.get(top[0], top[0].lower().replace('_', ' ')) if top else 'unknown'

    result = {
        'mislabeled_samples': sorted(mislabeled),
        'perturbation': perturbation,
    }

    with open('/app/pipeline_c_results.json', 'w') as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
