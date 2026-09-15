#!/usr/bin/env python3
"""Solve the microbiome phylogenetic audit task.

Explores the data, diagnoses tree quality issues, reconstructs an appropriate
tree, and recomputes the full community analysis pipeline.
"""

import json
import os
import numpy as np
import pandas as pd
from scipy.stats import pearsonr

from skbio import DistanceMatrix, TreeNode
from skbio.tree import nj
from skbio.diversity import beta_diversity, alpha_diversity
from skbio.stats.distance import permanova


def main():
    # ---- Explore and load input data ----
    dm_df = pd.read_csv("/app/data/pairwise_distances.tsv", sep="\t", index_col=0)
    otu_names = list(dm_df.index)
    dm_array = dm_df.values.astype(float)
    dm = DistanceMatrix(dm_array, ids=otu_names)

    provided_tree = TreeNode.read("/app/data/provided_tree.nwk")

    counts_df = pd.read_csv("/app/data/otu_counts.tsv", sep="\t", index_col=0)
    sample_names = list(counts_df.index)
    counts_matrix = counts_df.values.astype(int)
    taxa = list(counts_df.columns)

    meta_df = pd.read_csv("/app/data/sample_metadata.tsv", sep="\t", index_col=0)
    groups = meta_df["Group"].values

    os.makedirs("/app/results", exist_ok=True)

    # ---- Assess tree quality ----
    # Compute cophenetic (tip-to-tip patristic) distances from the provided tree
    # and compare with the original distance matrix via Pearson correlation
    tree_coph = provided_tree.cophenet()
    tree_coph = tree_coph.filter(otu_names)

    n = len(otu_names)
    coph_vals, orig_vals = [], []
    for i in range(n):
        for j in range(i + 1, n):
            coph_vals.append(tree_coph[otu_names[i], otu_names[j]])
            orig_vals.append(dm_array[i, j])

    fidelity_score, _ = pearsonr(coph_vals, orig_vals)
    print(f"Tree fidelity (cophenetic correlation): {fidelity_score:.6f}")

    # ---- Construct corrected tree ----
    # The provided tree appears to assume equal evolutionary rates (ultrametric).
    # Since rates clearly vary (fidelity < 1), use neighbor-joining which
    # handles rate heterogeneity correctly.
    corrected_tree = nj(dm)
    corrected_tree = corrected_tree.root_at_midpoint()
    corrected_tree.write("/app/results/corrected_tree.nwk")
    print("Corrected tree written.")

    # ---- Compute topology divergence ----
    topology_divergence = provided_tree.compare_rfd(corrected_tree, proportion=True)
    print(f"Topology divergence (normalized RF): {topology_divergence:.4f}")

    # ---- Recompute community distances (weighted UniFrac) ----
    unifrac_dm = beta_diversity(
        "weighted_unifrac",
        counts_matrix,
        ids=sample_names,
        taxa=taxa,
        tree=corrected_tree,
        validate=True,
    )

    with open("/app/results/community_distances.tsv", "w") as f:
        f.write("\t".join([""] + sample_names) + "\n")
        for i, si in enumerate(sample_names):
            row = [si] + [f"{unifrac_dm[si, sj]:.6f}" for sj in sample_names]
            f.write("\t".join(row) + "\n")
    print("Community distances written.")

    # ---- Run permutation-based group comparison (PERMANOVA) ----
    grouping = pd.DataFrame({"Group": groups}, index=sample_names)
    perm_result = permanova(
        unifrac_dm, grouping, column="Group", permutations=999, seed=0
    )

    test_stat = perm_result["test statistic"]
    p_value = perm_result["p-value"]

    with open("/app/results/group_comparison.txt", "w") as f:
        f.write(f"statistic\t{test_stat:.6f}\n")
        f.write(f"p-value\t{p_value:.4f}\n")
    print(f"Group comparison: statistic={test_stat:.4f}, p={p_value:.4f}")

    # ---- Compute per-sample phylogenetic diversity (Faith's PD) ----
    faith_values = alpha_diversity(
        "faith_pd", counts_matrix, ids=sample_names, taxa=taxa, tree=corrected_tree
    )

    with open("/app/results/sample_phylo_diversity.tsv", "w") as f:
        f.write("SampleID\tPD\n")
        for sid in sample_names:
            f.write(f"{sid}\t{faith_values[sid]:.6f}\n")
    print("Sample phylogenetic diversity written.")

    # ---- Determine most diverse group ----
    faith_df = pd.DataFrame(
        {"SampleID": sample_names, "PD": faith_values.values, "Group": groups}
    )
    group_means = faith_df.groupby("Group")["PD"].mean()
    most_diverse = group_means.idxmax()

    with open("/app/results/most_diverse_group.txt", "w") as f:
        f.write(f"{most_diverse}\n")
    print(f"Most diverse group: {most_diverse}")

    # ---- Write tree assessment ----
    # The original conclusion was "no significant differences" (p > 0.05).
    # After correcting the tree, check if that still holds.
    original_valid = bool(p_value > 0.05)

    assessment = {
        "fidelity_score": round(fidelity_score, 6),
        "topology_divergence": round(topology_divergence, 6),
        "original_conclusion_valid": original_valid,
    }

    with open("/app/results/tree_assessment.json", "w") as f:
        json.dump(assessment, f, indent=2)
    print(f"Tree assessment: {assessment}")

    print("\nAudit complete. All results written to /app/results/")


if __name__ == "__main__":
    main()
