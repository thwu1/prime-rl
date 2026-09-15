Data files in `/app/data/`:
- `distance_matrix.tsv`: pairwise evolutionary distances between 35 OTUs (`otu001`–`otu035`)
- `otu_table.tsv`: abundance counts for 24 samples across 30 OTUs (`OTU_1`–`OTU_30`)
- `metadata.tsv`: sample metadata with `treatment` and `batch` variables
- `reference_tree.nwk`: pre-built phylogenetic tree (30 OTUs + 2 outgroups)

OTU naming conventions differ across files. Restrict all analyses to OTUs present in both the distance matrix and the abundance table.

Determine which phylogenetic tree construction method — UPGMA, Neighbor-Joining (NJ), or Balanced Minimum Evolution (BME) — or the provided reference tree (after removing outgroups) best represents the evolutionary distances in the data. Evaluate all four trees on topological agreement (pairwise Robinson-Foulds distances) and distance fidelity (Pearson correlation between each tree's cophenetic/patristic distance matrix and the original distance matrix). The tree with highest distance fidelity is the best.

Assess whether the observed treatment effect on microbial community composition is genuine or an artifact of batch confounding. Exclude samples with total sequencing depth below 1000 reads. Rarefy retained samples to minimum depth among them (numpy `default_rng(42)` multinomial resampling, one draw per sample in sorted sample-ID order). Evaluate how tree choice affects PERMANOVA conclusions for treatment (weighted UniFrac, 999 permutations, seed=42). Decompose variance into unique and shared components for treatment and batch using PERMANOVA-based R² and determine whether the treatment effect is genuine (treatment unique R² > batch unique R²) or confounded.

Write to `/app/results/`:
- `tree_rf_distances.tsv`: 4×4 symmetric RF distance matrix; row/column labels: `reference`, `upgma`, `nj`, `bme`
- `cophenetic_correlations.tsv`: columns `method`, `pearson_r`; sorted descending by `pearson_r`
- `best_tree_method.txt`: single line — method name with highest cophenetic correlation
- `best_tree.nwk`: the selected tree in Newick format
- `sample_qc.tsv`: columns `sample_id`, `depth`, `status` (`pass`/`fail`); sorted by `sample_id`
- `rarefaction_depth.txt`: single integer (minimum depth among passing samples)
- `metric_impact.tsv`: columns `tree_method`, `pseudo_f`, `r_squared`; treatment PERMANOVA with each tree's weighted UniFrac
- `variance_partitioning.tsv`: columns `component`, `r_squared`; rows: `treatment_total`, `batch_total`, `treatment_unique`, `batch_unique`, `shared`, `residual`
- `assessment.txt`: single word — `genuine` or `confounded`