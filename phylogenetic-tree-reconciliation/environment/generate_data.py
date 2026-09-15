#!/usr/bin/env python3
"""Generate input data for the microbiome phylogenetic audit task.

Creates a non-ultrametric distance matrix, a UPGMA tree (which will be
inappropriate for this data), OTU abundance counts with group structure,
sample metadata, and a brief analysis summary note.
"""

import numpy as np
from scipy.spatial.distance import pdist, squareform
from scipy.cluster.hierarchy import linkage
import os


def linkage_to_newick(Z, labels):
    """Convert scipy hierarchical clustering linkage matrix to Newick string.

    Produces a rooted, binary tree with UPGMA-style branch lengths
    (height = linkage_distance / 2).
    """
    n = len(labels)
    heights = {}
    nwk = {}
    for i in range(n):
        nwk[i] = labels[i]
        heights[i] = 0.0
    for i in range(len(Z)):
        left, right = int(Z[i, 0]), int(Z[i, 1])
        h = Z[i, 2] / 2.0
        bl_left = max(h - heights[left], 1e-6)
        bl_right = max(h - heights[right], 1e-6)
        nwk[n + i] = f"({nwk[left]}:{bl_left:.6f},{nwk[right]}:{bl_right:.6f})"
        heights[n + i] = h
    return nwk[2 * n - 2] + ";\n"


def main():
    np.random.seed(42)

    n_otus = 20
    otu_names = [f"OTU{i:02d}" for i in range(1, n_otus + 1)]

    # --- Generate non-ultrametric pairwise distances ---
    # Three phylogenetic clades in a 30-dimensional feature space:
    #   Clade A: OTU01-OTU07   (7 OTUs)
    #   Clade B: OTU08-OTU13   (6 OTUs)
    #   Clade C: OTU14-OTU20   (7 OTUs)
    n_dims = 30
    center_a = np.zeros(n_dims)
    center_b = np.concatenate([np.ones(15) * 5.0, np.zeros(15)])
    center_c = np.concatenate([np.zeros(15), np.ones(15) * 5.0])
    centers = [center_a, center_b, center_c]

    clade_assignment = [0] * 7 + [1] * 6 + [2] * 7

    points = np.zeros((n_otus, n_dims))
    for i in range(n_otus):
        points[i] = centers[clade_assignment[i]] + np.random.randn(n_dims) * 1.2

    # Apply strongly varying evolutionary rates to violate ultrametricity.
    rates = np.array([
        1.0, 0.6, 2.5, 0.8, 1.1, 0.7, 1.8,   # Clade A: variable rates
        1.2, 0.5, 2.0, 1.4, 0.9, 1.6,          # Clade B: variable rates
        0.4, 1.9, 0.8, 2.2, 1.0, 1.5, 0.6      # Clade C: variable rates
    ])
    for i in range(n_otus):
        points[i] *= rates[i]

    # Compute pairwise Euclidean distances and scale to [0.02, 0.95]
    condensed = pdist(points, "euclidean")
    min_d, max_d = condensed.min(), condensed.max()
    condensed = 0.02 + 0.93 * (condensed - min_d) / (max_d - min_d)
    dm = squareform(condensed)

    # Build UPGMA tree (inappropriate for non-ultrametric data)
    Z = linkage(condensed, method="average")
    tree_nwk = linkage_to_newick(Z, otu_names)

    # --- Generate OTU abundance counts with group structure ---
    np.random.seed(123)

    n_samples = 15
    sample_names = [f"S{i:02d}" for i in range(1, n_samples + 1)]
    groups = ["Control"] * 5 + ["Treatment_A"] * 5 + ["Treatment_B"] * 5

    counts = np.zeros((n_samples, n_otus), dtype=int)

    # Control: moderate balanced abundances
    for s in range(5):
        counts[s] = np.random.poisson(50, n_otus)

    # Treatment_A: enriched in Clade A (OTU01-07), depleted in Clade C (OTU14-20)
    for s in range(5, 10):
        counts[s, 0:7] = np.random.poisson(150, 7)
        counts[s, 7:13] = np.random.poisson(40, 6)
        counts[s, 13:20] = np.random.poisson(8, 7)

    # Treatment_B: enriched in Clade C (OTU14-20), depleted in Clade A (OTU01-07)
    for s in range(10, 15):
        counts[s, 0:7] = np.random.poisson(8, 7)
        counts[s, 7:13] = np.random.poisson(40, 6)
        counts[s, 13:20] = np.random.poisson(150, 7)

    # Ensure no zero counts (avoid edge cases in diversity calculations)
    counts = np.maximum(counts, 1)

    # --- Write output files ---
    os.makedirs("/app/data", exist_ok=True)

    # Pairwise distance matrix
    with open("/app/data/pairwise_distances.tsv", "w") as f:
        f.write("\t".join([""] + otu_names) + "\n")
        for i in range(n_otus):
            row = [otu_names[i]] + [f"{dm[i, j]:.6f}" for j in range(n_otus)]
            f.write("\t".join(row) + "\n")

    # Phylogenetic tree (Newick) — built with an undisclosed method
    with open("/app/data/provided_tree.nwk", "w") as f:
        f.write(tree_nwk)

    # OTU abundance table
    with open("/app/data/otu_counts.tsv", "w") as f:
        f.write("\t".join(["SampleID"] + otu_names) + "\n")
        for i in range(n_samples):
            row = [sample_names[i]] + [str(counts[i, j]) for j in range(n_otus)]
            f.write("\t".join(row) + "\n")

    # Sample metadata
    with open("/app/data/sample_metadata.tsv", "w") as f:
        f.write("SampleID\tGroup\n")
        for i in range(n_samples):
            f.write(f"{sample_names[i]}\t{groups[i]}\n")

    # Analysis summary note (the published conclusion)
    with open("/app/data/analysis_notes.txt", "w") as f:
        f.write("Microbiome Community Analysis - Summary\n")
        f.write("=" * 40 + "\n")
        f.write("Dataset: 15 gut microbiome samples, 3 patient groups, 20 OTUs\n")
        f.write("Phylogenetic tree constructed from inter-OTU distances.\n")
        f.write("Community dissimilarity and diversity computed using tree.\n")
        f.write("Permutation test (999 permutations): not significant (p > 0.05)\n")
        f.write("\n")
        f.write("Conclusion: No statistically significant differences in community\n")
        f.write("structure were detected between Control, Treatment_A, and Treatment_B.\n")

    # Create empty results directory
    os.makedirs("/app/results", exist_ok=True)

    print("Data generation complete.")
    print(f"  Distance matrix: {n_otus}x{n_otus}")
    print(f"  OTU counts: {n_samples} samples x {n_otus} OTUs")
    print(f"  Groups: {', '.join(sorted(set(groups)))}")
    print(f"  Tree length: {len(tree_nwk)} chars")


if __name__ == "__main__":
    main()
