`/app/study.soft` contains an Affymetrix HG-U133 Plus 2.0 microarray dataset in GEO SOFT format from a clear cell renal cell carcinoma (ccRCC) study. The dataset comprises matched tumor and adjacent normal kidney tissue biopsies from 12 patients spanning disease stages 1–4 (3 patients per stage).

Perform a complete differential expression analysis and produce the following output files in `/app/`:

**`/app/design_matrix.tsv`** — Experimental design extracted from sample metadata. Columns: `sample_accession`, `condition` (Normal/Tumor), `stage` (integer 1–4; normal samples carry the stage of their matched tumor pair), `patient_id`. Rows sorted by `sample_accession`.

**`/app/gene_expression.tsv`** — Processed gene-level log2 expression matrix. First column `gene` (gene symbols), remaining columns are sample accessions (sorted alphabetically). Values rounded to 6 decimal places.

**`/app/de_stage1.tsv`** through **`/app/de_stage4.tsv`** — Per-stage differential expression results (tumor vs. normal). Columns: `gene`, `log2fc`, `pvalue`, `padj`. Sorted by `padj` ascending, then absolute `log2fc` descending. `log2fc` rounded to 6 decimal places; scientific notation for `pvalue` and `padj`.

**`/app/summary.json`** — JSON object containing:
- `total_samples`: integer count of samples
- `total_genes`: integer count of genes in the expression matrix
- `stages`: object keyed `"1"` through `"4"`, each with:
  - `sig_up_count`, `sig_down_count`: counts at padj < 0.05
  - `top5_up`, `top5_down`: lists of top 5 gene symbols ordered by significance (padj ascending, then absolute log2fc descending)