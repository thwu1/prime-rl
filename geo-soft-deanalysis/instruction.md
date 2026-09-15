A gene expression dataset at `/data/GSE_SYNTH.soft` contains platform annotations and sample-level microarray data from a hepatocellular carcinoma study. Produce a differential expression analysis and write all results to `/app/results/`.

## Outputs

**`/app/results/design_matrix.tsv`** — Experimental design extracted from sample metadata (tab-delimited). Columns: `sample_id`, `patient_id`, `tissue`, `stage`. Integer patient IDs, tissue as `tumor`/`normal`, stage as Roman numeral (I/II/III/IV). Sorted by sample_id.

**`/app/results/probe_gene_map.tsv`** — Platform probe-to-gene annotations (tab-delimited). Columns: `probe_id`, `gene_symbol`. Only probes with non-empty gene symbols. Sorted by probe_id.

**`/app/results/outlier_samples.txt`** — QC outlier sample IDs, one per line, sorted. A sample is an outlier if its median log2 intensity z-score exceeds 3 within its tissue group. Exclude full patient pairs where either sample is flagged from downstream analysis.

**`/app/results/differential_expression.tsv`** — Paired tumor-vs-normal results for non-outlier patient pairs (tab-delimited). Columns: `probe_id`, `gene_symbol`, `log2fc`, `pvalue`, `padj`. Gene-annotated probes only. Sorted by padj ascending, then probe_id.

**`/app/results/top_20_genes.txt`** — 20 most significant differentially expressed genes, one per line. Represent multi-probe genes by their most significant probe.