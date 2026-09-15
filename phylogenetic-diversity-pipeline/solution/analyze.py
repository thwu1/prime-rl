#!/usr/bin/env python3
"""
Phylogenetic microbiome diversity analysis pipeline.
Produces all required output files in /app/results/.
"""


import os
import numpy as np
import pandas as pd
from io import StringIO
from skbio import TreeNode, DistanceMatrix
from skbio.tree import majority_rule
from skbio.diversity import alpha_diversity, beta_diversity
from skbio.stats.distance import permanova
from skbio.stats.ordination import pcoa

RESULTS_DIR = "/app/results"
DATA_DIR = "/app/data"
os.makedirs(RESULTS_DIR, exist_ok=True)


def load_trees(filepath):
    """Load multiple Newick trees from a file (one per line)."""
    trees = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if line:
                trees.append(TreeNode.read(StringIO(line)))
    return trees


def compute_rf_distances(trees):
    """Compute pairwise Robinson-Foulds distances between trees."""
    n = len(trees)
    rf_matrix = np.zeros((n, n), dtype=int)
    for i in range(n):
        for j in range(i + 1, n):
            d = trees[i].compare_rfd(trees[j], proportion=False, rooted=False)
            rf_matrix[i, j] = int(d)
            rf_matrix[j, i] = int(d)
    return rf_matrix


def main():
    # ---- Step 1: Load gene trees and compute RF distances ----
    gene_trees = load_trees(os.path.join(DATA_DIR, "gene_trees.nwk"))
    n_trees = len(gene_trees)

    rf_matrix = compute_rf_distances(gene_trees)
    gt_ids = [f"GT{i:02d}" for i in range(n_trees)]
    rf_df = pd.DataFrame(rf_matrix, index=gt_ids, columns=gt_ids)
    rf_df.to_csv(os.path.join(RESULTS_DIR, "rf_matrix.tsv"), sep="\t")
    print("RF distance matrix computed.")

    # ---- Step 2: Build majority-rule consensus tree ----
    consensus_trees = majority_rule(gene_trees)
    consensus_tree = consensus_trees[0]

    # Strip support values from all nodes before writing. majority_rule sets
    # support on every node (including tips); the Newick serializer emits
    # "support:name" labels which corrupt tip names after a write-read cycle.
    for node in consensus_tree.traverse():
        node.support = None

    with open(os.path.join(RESULTS_DIR, "consensus.nwk"), "w") as f:
        f.write(str(consensus_tree).strip() + "\n")
    print("Consensus tree computed.")

    # ---- Step 3: Load and reconcile OTU table ----
    species_tree = TreeNode.read(os.path.join(DATA_DIR, "species_tree.nwk"))
    tree_tips = {tip.name for tip in species_tree.tips()}

    otu_table = pd.read_csv(os.path.join(DATA_DIR, "otu_table.tsv"), sep="\t",
                            index_col=0)
    # Filter to OTUs present in tree
    otu_cols_in_tree = [c for c in otu_table.columns if c in tree_tips]
    otu_table_filtered = otu_table[otu_cols_in_tree]
    sample_ids = list(otu_table_filtered.index)
    taxa = list(otu_table_filtered.columns)
    print(f"Filtered OTU table: {len(taxa)} OTUs retained from {len(otu_table.columns)} total.")

    # ---- Step 4: Root species tree at outgroup ----
    rooted_tree = species_tree.root_by_outgroup(["OTU09", "OTU10"])
    print("Species tree rooted at OTU09/OTU10 outgroup.")

    # ---- Step 5: Compute Faith's PD (alpha diversity) ----
    counts_matrix = otu_table_filtered.values
    faith_pd_series = alpha_diversity(
        "faith_pd", counts_matrix, ids=sample_ids,
        tree=rooted_tree, taxa=taxa
    )
    faith_df = pd.DataFrame({
        "SampleID": faith_pd_series.index,
        "FaithPD": faith_pd_series.values
    }).sort_values("SampleID")
    faith_df["FaithPD"] = faith_df["FaithPD"].map(lambda x: f"{x:.6f}")
    faith_df.to_csv(os.path.join(RESULTS_DIR, "faith_pd.tsv"), sep="\t", index=False)
    print("Faith's PD computed.")

    # ---- Step 6: Compute weighted UniFrac (beta diversity) ----
    unifrac_dm = beta_diversity(
        "weighted_unifrac", counts_matrix, ids=sample_ids,
        tree=rooted_tree, taxa=taxa
    )
    unifrac_df = unifrac_dm.to_data_frame()
    unifrac_df = unifrac_df.round(6)
    unifrac_df.to_csv(os.path.join(RESULTS_DIR, "unifrac_dm.tsv"), sep="\t")
    print("Weighted UniFrac distances computed.")

    # ---- Step 7: PERMANOVA ----
    metadata = pd.read_csv(os.path.join(DATA_DIR, "metadata.tsv"), sep="\t",
                           index_col=0)
    permanova_result = permanova(
        unifrac_dm, metadata, column="Treatment",
        permutations=999, seed=42
    )
    pseudo_f = permanova_result["test statistic"]
    p_value = permanova_result["p-value"]
    sample_size = permanova_result["sample size"]
    num_groups = permanova_result["number of groups"]

    # Derive R-squared: R² = 1 / (1 + (n - g) / ((g - 1) * F))
    n = sample_size
    g = num_groups
    r_squared = 1.0 / (1.0 + (n - g) / ((g - 1) * pseudo_f))

    perm_df = pd.DataFrame([{
        "test_statistic": round(pseudo_f, 6),
        "p_value": round(p_value, 6),
        "sample_size": int(sample_size),
        "num_groups": int(num_groups),
        "R_squared": round(r_squared, 6),
    }])
    perm_df.to_csv(os.path.join(RESULTS_DIR, "permanova.tsv"), sep="\t", index=False)
    print(f"PERMANOVA: pseudo-F={pseudo_f:.4f}, p={p_value:.4f}, R²={r_squared:.4f}")

    # ---- Step 8: PCoA ordination ----
    pcoa_result = pcoa(unifrac_dm)
    coords = pcoa_result.samples
    prop_explained = pcoa_result.proportion_explained

    # First 3 axes
    pcoa_df = pd.DataFrame({
        "SampleID": coords.index,
        "PC1": coords.iloc[:, 0].values,
        "PC2": coords.iloc[:, 1].values,
        "PC3": coords.iloc[:, 2].values,
    }).sort_values("SampleID")
    for col in ["PC1", "PC2", "PC3"]:
        pcoa_df[col] = pcoa_df[col].map(lambda x: f"{x:.6f}")
    pcoa_df.to_csv(os.path.join(RESULTS_DIR, "pcoa_axes.tsv"), sep="\t", index=False)

    # Proportion explained for first 3 axes
    propexpl_df = pd.DataFrame({
        "Axis": ["PC1", "PC2", "PC3"],
        "ProportionExplained": [f"{prop_explained.iloc[i]:.6f}" for i in range(3)],
    })
    propexpl_df.to_csv(os.path.join(RESULTS_DIR, "pcoa_propexpl.tsv"), sep="\t", index=False)
    print("PCoA computed.")

    print("\nAll results written to", RESULTS_DIR)


if __name__ == "__main__":
    main()
