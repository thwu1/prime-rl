Pre-cached NCBI data for a clear cell renal cell carcinoma (ccRCC) gene expression study (8 paired tumor/normal samples, 16 total) are in `/app/data/`:

- `series.soft` — GEO SOFT format file (series + sample metadata + per-sample expression tables, log2-scale intensities)
- `platform_annotation.tsv` — GPL570 (Affymetrix HG-U133 Plus 2.0) probe annotation; the `Gene Symbol` column uses `---` for unmapped probes, a single symbol for single-gene probes, and ` /// ` (space-delimited) to separate multiple gene symbols for multi-mapped probes. Probes with an `AFFX-` ID prefix are Affymetrix control probes and have no valid gene assignment.
- `sra_runinfo.csv` — SRA RunInfo CSV for the same study (contains several deliberate errors)

Produce all outputs in `/app/output/`.

## Required Outputs

**`/app/output/experimental_design.tsv`** — Tab-separated clinical design matrix from GEO sample metadata. Columns (in this exact order): `sample_id`, `title`, `tissue`, `tumor_stage`, `patient_id`, `gender`, `age`, `platform_id`. Extract `tissue`, `tumor_stage`, `patient_id`, `gender`, and `age` from `!Sample_characteristics_ch1` lines (tag:value format). One row per sample (16 data rows + header), sorted by `sample_id`.

**`/app/output/probe_gene_map.json`** — JSON object mapping every probe ID in the platform annotation to its gene symbol(s) as a list of strings. Probes with gene symbol `---` or with an `AFFX-` ID prefix map to an empty list `[]`. Multi-mapped probes (symbol containing ` /// `) map to a list of the individual gene symbols. Single-gene probes map to a one-element list.

**`/app/output/reconciliation_report.json`** — Cross-database metadata reconciliation. Compare each GEO sample against its corresponding SRA run and report discrepancies in these fields:

- `organism`: GEO `!Sample_organism_ch1` vs SRA `ScientificName`
- `library_source`: GEO expression data implies `TRANSCRIPTOMIC`; flag any SRA run whose `LibrarySource` differs
- `sample_name`: GEO sample title vs SRA `SampleName`; flag mismatches (match GEO samples to SRA rows by title, falling back to positional index when title is absent from SRA)

Each discrepancy is an object with keys `geo_sample_id`, `sra_run_id`, `field`, `geo_value`, `sra_value`. Output format:
```json
{"discrepancies": [{"geo_sample_id": "...", "sra_run_id": "...", "field": "...", "geo_value": "...", "sra_value": "..."}, ...]}
```

**`/app/output/de_results.tsv`** — Differential expression results (tumor vs. normal). One row per probe in the platform annotation. Columns: `probe_id`, `gene_symbol`, `mean_normal`, `mean_tumor`, `log2_fold_change`, `t_statistic`, `p_value`, `adj_p_value`. For `gene_symbol`, use `---` for unmapped probes and join multiple symbols with ` /// `. Since each patient contributes a matched tumor/normal pair, use a paired t-test. Compute log2 fold change as `mean_tumor - mean_normal` (data is already log2 scale). Apply Benjamini-Hochberg correction for multiple testing; adjusted p-values must be in [0, 1] and >= the corresponding raw p-value. Sort rows by `adj_p_value` ascending. As a sanity check: known up-regulated ccRCC probes (e.g. `205199_at`/CA9, `210512_s_at`/VEGFA, `200989_at`/HIF1A) should have positive fold change, and known down-regulated probes (e.g. `205020_s_at`/AQP1, `205352_at`/SERPINI1) should have negative fold change.

**`/app/output/top_genes.txt`** — Unique gene symbols with adjusted p < 0.05, one per line, alphabetically sorted. Exclude unmapped (`---`) and control probes. CA9 and VEGFA (classic ccRCC markers) should appear among the significant genes if the analysis is correct.