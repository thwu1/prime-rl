#!/usr/bin/env python3
"""Pipeline D: Feature-selected consensus clustering.

Applies data-driven feature selection to reduce dimensionality before
clustering. Selects the most variable genes to focus on informative
features, then uses consensus clustering across multiple k values to
determine optimal sample groupings without assuming k=2.
"""
import json
import sqlite3
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
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

    # Feature selection: top 100 most variable genes by variance
    gene_var = counts_filt.var(axis=1)
    top_genes = gene_var.nlargest(100).index
    selected = counts_filt.loc[top_genes]

    # Log2 + scale on selected features
    log_sel = np.log2(selected + 1)
    X = StandardScaler().fit_transform(log_sel.T.values)

    # PCA
    n_comp = min(10, X.shape[1])
    pcs = PCA(n_components=n_comp, random_state=42).fit_transform(X)

    # Consensus clustering: test k=2..5, select by silhouette score
    best_k, best_score, best_labels = 2, -1, None
    for k in range(2, 6):
        km = KMeans(n_clusters=k, random_state=42, n_init=20)
        labels = km.fit_predict(pcs[:, :5])
        score = silhouette_score(pcs[:, :5], labels)
        if score > best_score:
            best_k = k
            best_score = score
            best_labels = labels

    # Merge to 2 groups if optimal k > 2
    if best_k > 2:
        from scipy.cluster.hierarchy import linkage, fcluster
        centroids = np.array([pcs[best_labels == c, :5].mean(axis=0)
                              for c in range(best_k)])
        Z = linkage(centroids, method='ward')
        merged = fcluster(Z, t=2, criterion='maxclust')
        final = np.array([merged[best_labels[i]] - 1
                          for i in range(len(samples))])
    else:
        final = best_labels

    # Map clusters to conditions by majority vote
    cluster_cond = {}
    for c in [0, 1]:
        members = [samples[i] for i in range(len(samples)) if final[i] == c]
        ctrl = sum(1 for s in members if meta_dict[s] == 'Control')
        treat = sum(1 for s in members if meta_dict[s] == 'Treatment')
        cluster_cond[c] = 'Control' if ctrl >= treat else 'Treatment'

    mislabeled = []
    true_labels = {}
    for i, s in enumerate(samples):
        inferred = cluster_cond[final[i]]
        true_labels[s] = inferred
        if inferred != meta_dict[s]:
            mislabeled.append(s)

    # Differential expression on full gene set using inferred labels
    ctrl = [s for s in samples if true_labels[s] == 'Control']
    treat = [s for s in samples if true_labels[s] == 'Treatment']

    log_counts = np.log2(counts_filt + 1)
    de_genes = set()
    for gene in counts_filt.index:
        c_vals = log_counts.loc[gene, ctrl].values
        t_vals = log_counts.loc[gene, treat].values
        if len(c_vals) > 1 and len(t_vals) > 1:
            fc = t_vals.mean() - c_vals.mean()
            _, pval = stats.ttest_ind(t_vals, c_vals, equal_var=False)
            if pval < 0.01 and abs(fc) > 1.0:
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
        if best_pw and best_pv < 0.05:
            perturbation = best_pw.lower().replace('_', ' ')

    result = {
        'mislabeled_samples': sorted(mislabeled),
        'perturbation': perturbation
    }

    with open('/app/pipeline_d_results.json', 'w') as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
