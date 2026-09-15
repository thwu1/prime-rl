A GEO SOFT file from a clear cell renal cell carcinoma (ccRCC) gene expression study (GSE53757) is at `/opt/geo_data/GSE53757_family.soft`, with Affymetrix HG-U133 Plus 2.0 platform annotation at `/opt/geo_data/GPL570_annotation.tsv` (tab-delimited: ID, Gene Symbol, Gene Title, ENTREZ_GENE_ID).

A colleague's preliminary differential expression pipeline is at `/opt/analysis/preliminary_analysis.py`, with output in `/opt/analysis/preliminary_results/`. A peer reviewer has documented quality concerns in `/opt/analysis/qc_report.txt`.

Audit the preliminary pipeline, diagnose every methodological error responsible for the reviewer's concerns, and produce a corrected analysis. Write output to `/app/results/`:

**`phenotype_matrix.tsv`** — Tab-delimited. Columns: `sample_id`, `title`, `tissue`, `tumor_stage`, `sample_type`, `patient_id`. One row per sample.

**`gene_expression_summary.tsv`** — Tab-delimited. Columns: `gene_symbol`, `mean_tumor`, `mean_normal`, `log2fc`, `pvalue`, `padj`. One row per gene (exclude probe sets with no valid gene assignment). All numeric values rounded to 4 decimal places. Rows sorted by fold-change magnitude, largest first.

**`top_de_genes.tsv`** — Tab-delimited. Columns: `rank`, `gene_symbol`, `log2fc`, `direction`. The 20 most differentially expressed genes by fold-change magnitude. Direction is `up` if log2fc > 0, `down` otherwise.

**`stage_progression.tsv`** — Tab-delimited. Columns: `gene_symbol`, `stage_1`, `stage_2`, `stage_3`, `stage_4`. Per-stage mean gene-level expression across tumor samples for genes CA9, VHL, and VEGFA. Values rounded to 4 decimal places.