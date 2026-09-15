#!/usr/bin/env python3
"""Pipeline B: Direct count-space analysis.

Performs PCA and clustering directly on raw expression counts without
log transformation, preserving linear quantitative relationships between
samples for distance-based methods.
"""
import json
import sqlite3
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans


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

    # Filter low-expression genes
    gene_means = counts.mean(axis=1)
    counts_filt = counts[gene_means > 10]

    # PCA directly on raw counts (preserve linear relationships)
    X = counts_filt.T.values.astype(float)
    pcs = PCA(n_components=5, random_state=42).fit_transform(X)
    clusters = KMeans(n_clusters=2, random_state=42, n_init=20).fit_predict(pcs[:, :2])

    # Map clusters to conditions
    cluster_cond = {}
    for c in [0, 1]:
        members = [samples[i] for i in range(len(samples)) if clusters[i] == c]
        ctrl = sum(1 for s in members if meta_dict[s] == 'Control')
        treat = sum(1 for s in members if meta_dict[s] == 'Treatment')
        cluster_cond[c] = 'Control' if ctrl >= treat else 'Treatment'

    mislabeled = []
    true_labels = {}
    for i, s in enumerate(samples):
        inferred = cluster_cond[clusters[i]]
        true_labels[s] = inferred
        if inferred != meta_dict[s]:
            mislabeled.append(s)

    # Differential expression analysis
    ctrl = [s for s in samples if true_labels[s] == 'Control']
    treat = [s for s in samples if true_labels[s] == 'Treatment']

    de_genes = set()
    for gene in counts_filt.index:
        c_vals = counts_filt.loc[gene, ctrl].values.astype(float)
        t_vals = counts_filt.loc[gene, treat].values.astype(float)
        if len(c_vals) > 1 and len(t_vals) > 1:
            fc = t_vals.mean() / max(c_vals.mean(), 1.0)
            _, pval = stats.ttest_ind(t_vals, c_vals, equal_var=False)
            if pval < 0.01 and (fc > 2.0 or fc < 0.5):
                de_genes.add(gene)

    # Pathway enrichment
    pathways = {}
    with open('/app/data/pathway_annotations.gmt') as f:
        for line in f:
            parts = line.strip().split('\t')
            pathways[parts[0]] = set(parts[2:])

    perturbation = 'unknown'
    if de_genes:
        all_genes = set(counts_filt.index)
        best_pw, best_pv = None, 1.0
        for pname, pgenes in pathways.items():
            pg = pgenes & all_genes
            if len(pg) < 3:
                continue
            a = len(de_genes & pg)
            b = len(de_genes - pg)
            c_ = len(pg - de_genes)
            d = len(all_genes - de_genes - pg)
            _, pv = stats.fisher_exact([[a, b], [c_, d]], alternative='greater')
            if pv < best_pv:
                best_pv = pv
                best_pw = pname
        if best_pw:
            perturbation = best_pw.lower().replace('_', ' ')

    result = {
        'mislabeled_samples': sorted(mislabeled),
        'perturbation': perturbation
    }

    with open('/app/pipeline_b_results.json', 'w') as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
