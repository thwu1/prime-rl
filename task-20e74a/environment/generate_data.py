#!/usr/bin/env python3
"""Generate synthetic data for phylogenetic tree evaluation task."""
import os
import numpy as np
from itertools import combinations


def build_random_tree_newick(tip_names, rng, min_bl=0.01, max_bl=0.3):
    """Build a random binary phylogenetic tree and return its Newick string."""
    nodes = list(tip_names)
    while len(nodes) > 1:
        indices = sorted(rng.choice(len(nodes), 2, replace=False))
        n1, n2 = nodes[indices[0]], nodes[indices[1]]
        nodes.pop(indices[1])
        nodes.pop(indices[0])
        bl1 = round(float(rng.uniform(min_bl, max_bl)), 5)
        bl2 = round(float(rng.uniform(min_bl, max_bl)), 5)
        nodes.append(f"({n1}:{bl1},{n2}:{bl2})")
    return nodes[0] + ";"


def main():
    rng = np.random.default_rng(seed=20240601)
    os.makedirs('/app/data', exist_ok=True)

    # --- 1. OTU pairwise distance matrix (35 OTUs) ---
    n_dm = 35
    dm_names = [f"otu{i:03d}" for i in range(1, n_dm + 1)]

    # Generate coordinates in 6D with structured group variation
    # to produce non-ultrametric distances (UPGMA will underperform NJ)
    coords = rng.standard_normal((n_dm, 6)) * 0.3
    coords[:12, 0] += 1.0
    coords[12:20, 0] -= 0.8
    coords[20:, 0] -= 0.2
    coords[:6, 1] += 0.6
    coords[6:12, 1] -= 0.5
    coords[12:20, 2] += 0.7
    coords[20:28, 3] += 0.5
    coords[28:, 4] -= 0.9

    dm = np.zeros((n_dm, n_dm))
    for i, j in combinations(range(n_dm), 2):
        d = np.sqrt(np.sum((coords[i] - coords[j]) ** 2))
        dm[i, j] = dm[j, i] = round(d, 6)

    with open('/app/data/distance_matrix.tsv', 'w') as f:
        f.write('\t'.join([''] + dm_names) + '\n')
        for i, name in enumerate(dm_names):
            vals = '\t'.join(f"{dm[i, j]:.6f}" for j in range(n_dm))
            f.write(f"{name}\t{vals}\n")

    # --- 2. Reference tree (deliberately suboptimal topology) ---
    ref_otus = [f"otu{i:03d}" for i in range(1, 31)]
    outgroups = ["outgroup_alpha", "outgroup_beta"]
    rng_ref = np.random.default_rng(seed=99999)
    ref_nwk = build_random_tree_newick(ref_otus + outgroups, rng_ref, 0.01, 0.2)
    with open('/app/data/reference_tree.nwk', 'w') as f:
        f.write(ref_nwk + '\n')

    # --- 3. OTU abundance table (24 samples x 30 OTUs) ---
    # Table uses OTU_X naming (maps to otuXXX in DM/tree)
    n_samples = 24
    n_otus = 30
    samples = [f"sample_{i:02d}" for i in range(1, n_samples + 1)]
    otu_cols = [f"OTU_{i}" for i in range(1, n_otus + 1)]

    # Treatment: 12 drug (1-12), 12 placebo (13-24)
    treatment = ['drug'] * 12 + ['placebo'] * 12
    # Batch partially confounded with treatment
    batch = (['A'] * 6 + ['B'] * 4 + ['C'] * 2 +
             ['A'] * 2 + ['B'] * 4 + ['C'] * 6)

    counts = np.zeros((n_samples, n_otus), dtype=int)
    for i in range(n_samples):
        if treatment[i] == 'drug':
            counts[i, :15] = rng.negative_binomial(8, 0.05, 15)
            counts[i, 15:] = rng.negative_binomial(2, 0.12, 15)
        else:
            counts[i, :15] = rng.negative_binomial(2, 0.12, 15)
            counts[i, 15:] = rng.negative_binomial(8, 0.05, 15)

    # Mild batch effect
    for i in range(n_samples):
        if batch[i] == 'A':
            counts[i, :5] += rng.poisson(5, 5)
        elif batch[i] == 'C':
            counts[i, 25:] += rng.poisson(5, 5)

    # 2 low-depth samples (below 1000 reads)
    for idx in [6, 18]:  # sample_07, sample_19
        total = counts[idx].sum()
        target = int(rng.integers(200, 450))
        probs = counts[idx] / total
        counts[idx] = rng.multinomial(target, probs)

    with open('/app/data/otu_table.tsv', 'w') as f:
        f.write('sample_id\t' + '\t'.join(otu_cols) + '\n')
        for i, s in enumerate(samples):
            f.write(s + '\t' + '\t'.join(str(c) for c in counts[i]) + '\n')

    # --- 4. Sample metadata ---
    with open('/app/data/metadata.tsv', 'w') as f:
        f.write('sample_id\ttreatment\tbatch\n')
        for i, s in enumerate(samples):
            f.write(f'{s}\t{treatment[i]}\t{batch[i]}\n')

    os.makedirs('/app/results', exist_ok=True)
    depths = counts.sum(axis=1)
    print("Data generated.")
    print(f"  DM: {n_dm} OTUs | Table: {n_samples}x{n_otus} | "
          f"Depth range: {depths.min()}-{depths.max()}")


if __name__ == '__main__':
    main()
