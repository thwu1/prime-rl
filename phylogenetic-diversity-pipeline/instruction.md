A gut microbiome study collected 16S amplicon data from 15 samples across three treatment groups. The data files are in `/app/data/`:

- `species_tree.nwk` — Reference phylogeny of microbial OTUs (Newick)
- `gene_trees.nwk` — 12 gene trees from single-copy marker loci (one per line, Newick)
- `otu_table.tsv` — Abundance table (samples × OTUs, tab-separated)
- `metadata.tsv` — Sample metadata with `Treatment` and `Site` columns
- `study_notes.txt` — Experimental design notes from the PI

**The data files have not been pre-validated or harmonized.** Inspect them carefully, read the study notes, and resolve any inconsistencies you find before running analyses.

Write an analysis that produces all of the following files in `/app/results/`:

| File | Contents |
|------|----------|
| `rf_matrix.tsv` | Pairwise topological distance matrix across all 12 gene trees. Tab-separated integers, row/column headers `GT00`–`GT11`. |
| `consensus.nwk` | Majority-rule consensus of the 12 gene trees (Newick). |
| `faith_pd.tsv` | Phylogenetic alpha diversity per sample. Columns: `SampleID`, `FaithPD` (6 decimal places), sorted by SampleID. |
| `unifrac_dm.tsv` | Abundance-weighted phylogenetic beta-diversity distance matrix (all 15 samples). Tab-separated, 6 decimal places, sample IDs as row/column headers. |
| `permanova.tsv` | Test whether community composition differs across the three `Treatment` groups using the beta-diversity distances. 999 permutations, seed 42. Columns: `test_statistic`, `p_value`, `sample_size`, `num_groups`, `R_squared` (effect size: proportion of total variance explained by grouping). |
| `pcoa_axes.tsv` | Ordination of the beta-diversity distances, first 3 axes. Columns: `SampleID`, `PC1`, `PC2`, `PC3` (6 decimal places), sorted by SampleID. |
| `pcoa_propexpl.tsv` | Variance explained by each of the first 3 ordination axes. Columns: `Axis`, `ProportionExplained` (6 decimal places). |