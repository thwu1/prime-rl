A microbiome study analyzed gut samples from patient groups and concluded there were no significant community structure differences. The study data is in `/app/data/`, including the phylogenetic tree used as the basis for all downstream analyses.

A peer reviewer suspects the tree does not faithfully capture the evolutionary relationships between taxa, which would invalidate the published results. Audit the analysis: assess tree quality against the underlying distance data, construct a corrected tree if warranted, and recompute the complete phylogenetic community analysis.

Write all outputs to `/app/results/`:

- `tree_assessment.json` — JSON object containing:
  - `fidelity_score` (float): Pearson correlation between the tree's implied pairwise tip distances and the original distance matrix
  - `topology_divergence` (float): normalized symmetric partition distance between the provided tree and your corrected tree (0 = identical topology, 1 = maximally different)
  - `original_conclusion_valid` (boolean): whether the original statistical conclusion holds after reanalysis with the corrected tree

- `corrected_tree.nwk` — Rooted phylogenetic tree that faithfully represents the pairwise evolutionary distances (Newick format)

- `community_distances.tsv` — Pairwise sample dissimilarity matrix accounting for phylogenetic branch lengths weighted by taxon abundances (tab-delimited, sample IDs as column headers and row labels)

- `group_comparison.txt` — Permutation-based multivariate test for differences between sample groups using the corrected dissimilarity matrix. Two lines: `statistic\t<value>` and `p-value\t<value>`. Use 999 permutations with seed 0.

- `sample_phylo_diversity.tsv` — Per-sample phylogenetic diversity computed from the corrected tree (tab-delimited, columns: `SampleID`, `PD`)

- `most_diverse_group.txt` — Group with highest mean phylogenetic diversity (single line)