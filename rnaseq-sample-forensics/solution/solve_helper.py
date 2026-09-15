#!/usr/bin/env python3
"""
Solution: Evaluate four RNA-seq analysis pipelines and produce correct results.

Reads expression data from the SQLite database, detects technical outlier genes,
performs correct clustering and enrichment analysis, evaluates each pipeline's
methodology, and explains the batch-condition confounding.
"""
import json
import sqlite3
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans


def load_from_database():
    """Extract expression matrix and metadata from the SQLite database."""
    conn = sqlite3.connect('/app/data/experiment.db')

    counts_long = pd.read_sql(
        'SELECT gene_symbol, sample_id, raw_count FROM expression_data', conn)
    counts = counts_long.pivot(
        index='gene_symbol', columns='sample_id', values='raw_count')

    metadata = pd.read_sql(
        'SELECT sample_id, assigned_condition, processing_batch FROM samples',
        conn)

    conn.close()

    counts = counts.reindex(columns=sorted(counts.columns))
    return counts, metadata


def detect_technical_outliers(counts_filt):
    """Identify genes with extreme technical count artifacts.

    Uses max-to-median ratio to find genes where a few samples have
    counts wildly inconsistent with the rest, indicating technical
    spikes rather than biological variation.
    """
    outlier_genes = []
    for gene in counts_filt.index:
        vals = counts_filt.loc[gene].values.astype(float)
        median_val = np.median(vals)
        if median_val < 5:
            continue
        max_val = np.max(vals)
        if max_val / max(median_val, 1.0) > 20:
            outlier_genes.append(gene)
    return sorted(outlier_genes)


def correct_analysis():
    """Perform the methodologically correct analysis."""
    counts, metadata = load_from_database()
    samples = list(counts.columns)
    meta_dict = dict(zip(metadata['sample_id'], metadata['assigned_condition']))

    # Filter low-expression genes
    gene_means = counts.mean(axis=1)
    counts_filt = counts[gene_means > 10]

    # Detect technical outlier genes
    outlier_genes = detect_technical_outliers(counts_filt)
    print(f"Technical outlier genes: {outlier_genes}")

    # Log2 transform
    log_counts = np.log2(counts_filt + 1)

    # Library-size normalization: subtract per-sample median
    # Removes global scaling (batch + library size) while preserving
    # gene-specific treatment fold-changes
    sample_medians = log_counts.median(axis=0)
    log_norm = log_counts - sample_medians

    # Standardize per-gene, then PCA
    X = StandardScaler().fit_transform(log_norm.T.values)
    pca = PCA(n_components=5, random_state=42)
    pcs = pca.fit_transform(X)
    print(f"PCA variance explained: {pca.explained_variance_ratio_[:5]}")

    # K-means on top 2 PCs
    clusters = KMeans(n_clusters=2, random_state=42, n_init=20).fit_predict(pcs[:, :2])

    # Map clusters to conditions by majority vote
    cluster_cond = {}
    for c in [0, 1]:
        members = [samples[i] for i in range(len(samples)) if clusters[i] == c]
        ctrl = sum(1 for s in members if meta_dict[s] == 'Control')
        treat = sum(1 for s in members if meta_dict[s] == 'Treatment')
        cluster_cond[c] = 'Control' if ctrl > treat else 'Treatment'
        print(f"Cluster {c}: {ctrl} Control, {treat} Treatment -> {cluster_cond[c]}")

    # Identify mislabeled
    mislabeled = []
    true_labels = {}
    for i, s in enumerate(samples):
        inferred = cluster_cond[clusters[i]]
        true_labels[s] = inferred
        if inferred != meta_dict[s]:
            mislabeled.append(s)
            print(f"  MISLABELED: {s} (metadata={meta_dict[s]}, inferred={inferred})")

    # DEA on corrected labels using ALL genes (both directions)
    ctrl = [s for s in samples if true_labels[s] == 'Control']
    treat = [s for s in samples if true_labels[s] == 'Treatment']

    de_genes = []
    for gene in counts_filt.index:
        ctrl_vals = log_counts.loc[gene, ctrl].values
        treat_vals = log_counts.loc[gene, treat].values
        log2fc = treat_vals.mean() - ctrl_vals.mean()
        _, pval = stats.ttest_ind(treat_vals, ctrl_vals, equal_var=False)
        if pval < 1e-5 and abs(log2fc) > 1.0:
            de_genes.append((gene, log2fc, pval))

    up = [g for g, fc, _ in de_genes if fc > 0]
    down = [g for g, fc, _ in de_genes if fc < 0]
    print(f"\nDE genes: {len(de_genes)} ({len(up)} up, {len(down)} down)")

    # Enrichment using ALL DE genes (both up and down-regulated)
    pathways = {}
    with open('/app/data/pathway_annotations.gmt') as f:
        for line in f:
            parts = line.strip().split('\t')
            pathways[parts[0]] = set(parts[2:])

    all_genes_set = set(counts_filt.index)
    de_set = set(g for g, _, _ in de_genes)

    enrichment_results = []
    for pname, pgenes in pathways.items():
        pg = pgenes & all_genes_set
        if len(pg) < 3:
            continue
        a = len(de_set & pg)
        b = len(de_set - pg)
        c_ = len(pg - de_set)
        d = len(all_genes_set - de_set - pg)
        _, pv = stats.fisher_exact([[a, b], [c_, d]], alternative='greater')
        enrichment_results.append((pname, a, len(pg), pv))

    enrichment_results.sort(key=lambda x: x[3])
    print("\nPathway enrichment (top 5):")
    for pname, overlap, total, pv in enrichment_results[:5]:
        print(f"  {pname}: {overlap}/{total} genes, p={pv:.2e}")

    top_pathway = enrichment_results[0][0] if enrichment_results else None

    mapping = {
        'HEAT_SHOCK_RESPONSE': 'heat shock',
        'CELL_CYCLE_REGULATION': 'cell cycle arrest',
        'OXIDATIVE_STRESS_RESPONSE': 'oxidative stress',
        'P53_SIGNALING_PATHWAY': 'DNA damage',
    }
    perturbation = mapping.get(top_pathway,
                               top_pathway.lower().replace('_', ' ') if top_pathway else 'unknown')

    return sorted(mislabeled), perturbation, outlier_genes


def main():
    mislabeled, perturbation, outlier_genes = correct_analysis()

    evaluations = {
        "pipeline_a": {
            "correct": False,
            "flaw_description": (
                "Batch mean-centering removes the biological treatment signal "
                "because the processing batch is completely confounded with "
                "the experimental condition (Batch1 maps to Control, Batch2 "
                "maps to Treatment), so the batch correction destroys the "
                "treatment effect along with the batch effect."
            )
        },
        "pipeline_b": {
            "correct": False,
            "flaw_description": (
                "PCA is performed directly on raw counts without log "
                "transformation or per-gene scaling, allowing a small number "
                "of high-expression genes to dominate the variance structure "
                "and obscure the biological signal from differentially "
                "expressed genes."
            )
        },
        "pipeline_c": {
            "correct": False,
            "flaw_description": (
                "Enrichment analysis is restricted to only downregulated genes, "
                "missing the upregulated heat shock response pathway and instead "
                "identifying a downstream consequence (cell cycle regulation) as "
                "the perturbation."
            )
        },
        "pipeline_d": {
            "correct": False,
            "flaw_description": (
                "Gene selection based on variance of raw counts biases the "
                "feature set toward high-expression housekeeping genes and "
                "technical outlier genes due to the mean-variance relationship "
                "in count data, causing the clustering to be driven by "
                "uninformative variation rather than biological signal."
            )
        },
    }

    confound_summary = (
        "Processing batch is completely confounded with experimental condition: "
        "all Batch1 samples (Sample_01 through Sample_12) are assigned to "
        "Control, and all Batch2 samples (Sample_13 through Sample_24) are "
        "assigned to Treatment. This means batch effects (processing date, "
        "operator, technical variation) are indistinguishable from the "
        "biological treatment effect. Batch correction methods that adjust "
        "per-batch means will remove the treatment signal along with the "
        "batch effect, making them inappropriate for this dataset."
    )

    result = {
        "pipeline_evaluations": evaluations,
        "mislabeled_samples": mislabeled,
        "technical_outlier_genes": outlier_genes,
        "perturbation": perturbation,
        "confound_summary": confound_summary,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(result, f, indent=2)

    print(f"\n=== RESULTS ===")
    print(f"Mislabeled samples: {mislabeled}")
    print(f"Technical outlier genes: {outlier_genes}")
    print(f"Perturbation: {perturbation}")
    print(f"Written to /app/results.json")


if __name__ == '__main__':
    main()
